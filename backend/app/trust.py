"""Расчёт Trust Score.

Trust отвечает не на вопрос «насколько хорош этот специалист», а на вопрос
«насколько достоверно то, на основании чего мы его оцениваем». Это разные
вещи, и смешивать их с PROF.индексом нельзя: PROF показывает покрытие
требований эталона, Trust - подтверждённость самих сведений.

Три правила, которые здесь важнее удобства кода:

1. **Только сложение.** Ни одна операция в расчёте не вычитает из общей суммы.
   Пропуск, отказ, неудачный ответ, нерешённое противоречие дают ноль вклада, а
   не минус. Проверить это можно глазами: во всём файле нет ни одного
   уменьшения накопленного балла.
2. **Ни одного балла без факта.** У каждого компонента есть объяснение, которое
   можно оспорить фактами, а не ощущением: «ответов, прошедших проверку на
   шаблонность: 3 из 4», а не «низкая достоверность».
3. **Повтор того же источника весит меньше нового.** Второе подтверждение из
   той же категории добавляет меньше, чем первое из новой, - и кандидату это
   объясняется, а не проглатывается молча.

Все коэффициенты - калибруемая гипотеза (Гл. 13), а не проверенная формула.
Держатся отдельными константами именно поэтому.
"""

import re
from dataclasses import dataclass, field

from app.enrichment import (
    DECLINED,
    TYPE_BLIND_WITNESS,
    TYPE_FILE,
    TYPE_LINK,
    TYPE_MIRROR_TASK,
    TYPE_PROBE_ANSWER,
)

# --- калибруемые константы -----------------------------------------------

AUTHENTICITY = "authenticity"
UNDERSTANDING = "understanding"
CONSISTENCY = "consistency"

COMPONENTS = (AUTHENTICITY, UNDERSTANDING, CONSISTENCY)

COMPONENT_RU = {
    AUTHENTICITY: "Признаки самостоятельной работы",
    UNDERSTANDING: "Понимание",
    CONSISTENCY: "Непротиворечивость",
}

# Вклад подтверждения: первое из новой категории источника весит полный балл,
# каждое следующее из той же категории - меньше (§4.2).
FIRST_IN_CATEGORY = 1.0
REPEAT_IN_CATEGORY = 0.25
# Одна и та же компетенция, подтверждённая двумя разными механизмами сразу.
CROSS_VERIFIED_BONUS = 0.5

# Сколько «единиц» подтверждения считаем полным баллом компонента.
COMPONENT_TARGET = {
    AUTHENTICITY: 3.0,
    UNDERSTANDING: 3.0,
    CONSISTENCY: 3.0,
}

# Вклад компонентов в общий балл. Не среднее: достоверность сведений сильнее
# зависит от того, понимает ли человек, о чём говорит.
COMPONENT_WEIGHT = {
    AUTHENTICITY: 0.3,
    UNDERSTANDING: 0.4,
    CONSISTENCY: 0.3,
}

# Порог серьёзности противоречия. Осознанно консервативный: пока нет данных,
# всё считается minor и ничего не приостанавливает (§4.4).
MAJOR_SEVERITY_MIN_SIGNALS = 3

# Признаки того, что описанный масштаб работ не тянет на заявленный уровень.
# Эвристика MVP, а не классификатор: ждёт калибровки.
JUNIOR_SCOPE_MARKERS = (
    "под руководством",
    "мне поручили",
    "по задаче от",
    "стажёр",
    "стажер",
    "помогал",
    "делал что скажут",
    "выполнял задачи",
    "меня попросили",
    "первый рабочий проект",
    "учебный проект",
)
SENIOR_CLAIM_LEVELS = ("Senior",)

_MARKER_PATTERNS = tuple(re.compile(marker, re.IGNORECASE) for marker in JUNIOR_SCOPE_MARKERS)


# --- входные данные -------------------------------------------------------


@dataclass(frozen=True)
class ProbeFacts:
    """Что модуль 4 знает про один ответ кандидата."""

    answer_id: str
    competency_id: str
    understanding_signal: bool
    paste_attempts_blocked: int
    had_follow_up: bool
    resolved_after_follow_up: bool


@dataclass(frozen=True)
class EvidenceFacts:
    """Доказательство модуля 2 глазами Trust."""

    id: str
    type: str
    source_category: str | None
    status: str
    statement_ids: tuple[str, ...]


@dataclass(frozen=True)
class ComponentScore:
    component_id: str
    score: int
    explanation_ru: str
    contributing_evidence_ids: list[str] = field(default_factory=list)
    notes_ru: list[str] = field(default_factory=list)


# --- вспомогательное ------------------------------------------------------


# --- что вообще может быть сигналом достоверности -------------------------
#
# Ключевое различие, которое легко потерять: **существование доказательства и
# его проверенность - разные вещи.**
#
# Для PROF существования достаточно: индекс меряет покрытие требований эталона
# тем, что кандидат принёс, и это честно называется покрытием. Для Trust -
# нет. Ссылка на репозиторий, которую никто не открывал, ничего не говорит о
# достоверности: её мог вставить кто угодно и какую угодно.
#
# Поэтому в Trust идут только те доказательства, которые появились из механики
# проверки: ответ вживую (модуль 4), подтверждение под NDA структурным
# описанием или зеркальной задачей (модуль 5). Ссылки, файлы и рассказ своими
# словами в Trust не идут вообще - до тех пор, пока их некому проверить.
#
# Это не отрицательный сигнал и не наказание: непроверенное доказательство
# по-прежнему полноценно работает в PROF. Оно просто не выдаётся за
# проверенное.

# Механики, которые дают основание считать доказательство сигналом
# достоверности. Список закрытый намеренно: расширять его - значит заводить
# новую механику проверки, а не дописывать сюда тип.
TRUST_ELIGIBLE_TYPES = (TYPE_BLIND_WITNESS, TYPE_MIRROR_TASK, TYPE_PROBE_ANSWER)

# Куда встанет внешняя проверка, когда появится. Пока таких доказательств не
# бывает: подтвердить ссылку на GitHub изнутри продукта нечем, и делать вид,
# что бывает, было бы ровно тем обманом, который Trust Score и предотвращает.
EXTERNALLY_VERIFIED = "externally_verified"


def is_trust_eligible(item: EvidenceFacts) -> bool:
    """Может ли доказательство вообще считаться сигналом достоверности.

    Отказ (`declined`) не может. Ссылка или файл в состоянии `pending` - тоже:
    `pending` в модуле 2 означает «запись есть», а не «проверено», и путать
    эти две вещи нельзя.
    """
    if item.status == DECLINED:
        return False
    if item.status == EXTERNALLY_VERIFIED:
        return True
    return item.type in TRUST_ELIGIBLE_TYPES


def _category_key(item: EvidenceFacts) -> str:
    """Та же логика «разных источников», что в модуле 2, а не своя вторая."""
    if item.type == TYPE_LINK:
        return item.source_category or "other"
    return item.type


def _weighted_sum(keys: list[str]) -> float:
    """Первое подтверждение из категории весит больше повторного (§4.2)."""
    seen: set[str] = set()
    total = 0.0
    for key in keys:
        if key in seen:
            total += REPEAT_IN_CATEGORY
        else:
            total += FIRST_IN_CATEGORY
            seen.add(key)
    return total


def _to_score(units: float, component_id: str) -> int:
    """Единицы подтверждения -> 0..100. Ниже нуля значение не бывает."""
    target = COMPONENT_TARGET[component_id]
    return max(0, min(100, round(100 * units / target)))


# --- компоненты -----------------------------------------------------------


# Что этот компонент честно может о себе сказать. Формулировка вынесена
# константой, потому что она обязана появляться везде, где показывается сам
# компонент: заявление сильнее измеренного - это и есть та ошибка, ради
# исключения которой существует Trust Score.
AUTHENTICITY_CAVEAT_RU = (
    "Это наблюдаемые признаки, а не доказательство авторства. Продукт видит только то, "
    "как шла работа над ответом в его собственном окне: были ли попытки вставить текст и "
    "выдержал ли ответ проверку на общие слова. Отсутствие попытки вставки не доказывает, "
    "что человек не пользовался помощью или языковой моделью — этого мы не знаем и не "
    "утверждаем."
)


def authenticity(probes: list[ProbeFacts]) -> ComponentScore:
    """Признаки того, что ответ писали здесь и сейчас (FR1.2).

    **Важно, чем это НЕ является.** Компонент не доказывает авторство и не
    определяет использование языковой модели. Он считает два наблюдаемых
    признака: попытки вставить текст в поле ответа и результат проверки на
    общие слова. Оба - гипотеза, а не улика.

    Раньше компонент назывался «Самостоятельность», и это обещало больше, чем
    измеряется: отсутствие вставки не доказывает отсутствие посторонней помощи.
    Название и объяснение ослаблены до фактически наблюдаемого; сама формула не
    менялась - менялось то, что она о себе заявляет.

    Античита здесь нет и не планируется: клавиатурный почерк выключен до
    юридического заключения, слежки за окном браузера нет.
    """
    independent = [
        item for item in probes if item.paste_attempts_blocked == 0 and item.understanding_signal
    ]
    units = _weighted_sum([item.competency_id for item in independent])
    score = _to_score(units, AUTHENTICITY)

    if not probes:
        explanation = "Пока не на чем считать: вы ещё не отвечали на вопросы вживую."
    else:
        with_paste = [item for item in probes if item.paste_attempts_blocked > 0]
        explanation = (
            f"Ответов, написанных без попыток вставки и прошедших проверку на общие слова: "
            f"{len(independent)} из {len(probes)}."
        )
        if with_paste:
            explanation += (
                f" В {len(with_paste)} из них была попытка вставить текст — они просто не "
                "пошли в зачёт."
            )

    notes = [AUTHENTICITY_CAVEAT_RU]
    if len(independent) > len({item.competency_id for item in independent}):
        notes.append(
            "Несколько ответов пришлись на одну компетенцию — повтор добавляет меньше, "
            "чем ответ по новой теме."
        )

    return ComponentScore(AUTHENTICITY, score, explanation, [], notes)


def understanding(probes: list[ProbeFacts], nda_confirmations: list[EvidenceFacts]) -> ComponentScore:
    """Показал ли кандидат логику того, что заявил (FR1.3).

    Считаются ответы Contextual Probe, прошедшие проверку, и подтверждения под
    NDA: структурное описание и зеркальная задача проверяют ровно то же самое.
    """
    passed = [item for item in probes if item.understanding_signal]
    # Пригодность проверяется явно: сюда должны попадать только доказательства
    # из механик проверки, а не всё, что не отклонено.
    eligible = [item for item in nda_confirmations if is_trust_eligible(item)]
    keys = [item.competency_id for item in passed] + [_category_key(e) for e in eligible]
    units = _weighted_sum(keys)
    score = _to_score(units, UNDERSTANDING)

    if not probes and not eligible:
        explanation = "Ни одного разобранного вживую ответа пока нет."
    else:
        parts = []
        if probes:
            parts.append(f"ответов Contextual Probe с подтверждённым пониманием: {len(passed)} из {len(probes)}")
        if eligible:
            parts.append(f"подтверждений под NDA: {len(eligible)}")
        explanation = "Засчитано: " + ", ".join(parts) + "."

    notes = []
    unresolved = [item for item in probes if item.had_follow_up and not item.resolved_after_follow_up]
    if unresolved:
        notes.append(
            f"Ответов, оставшихся общими после уточнения: {len(unresolved)}. Они не убавляют "
            "балл — просто пока ничего не подтверждают."
        )

    return ComponentScore(UNDERSTANDING, score, explanation, [e.id for e in eligible], notes)


def consistency(
    evidence: list[EvidenceFacts],
    open_contradictions: int,
    resolved_contradictions: int,
    open_findings: int,
) -> ComponentScore:
    """Насколько сведения профиля не спорят друг с другом (FR1.4).

    **Считаются только разобранные нестыковки, а не количество доказательств.**
    Раньше компонент рос от числа и разнообразия источников - но пять ссылок
    разных видов не доказывают, что они между собой согласуются. Это было
    покрытие под именем непротиворечивости, и такое имя обещало больше, чем
    измерялось.

    Полноценного разбора противоречий по смыслу в продукте нет: есть локальные
    проверки модуля 6, которые ловят несколько очевидных случаев. Поэтому
    честная модель здесь такая - засчитывается только то, что действительно
    проверено и разобрано, а всё остальное честно называется неизмеренным.

    Неизмеренное - это не ноль и не плохой результат: у компонента нет данных,
    и так и написано. Открытое противоречие тоже ничего не отнимает (FR5.1).
    """
    # Доказательства здесь больше не считаются вовсе - ни в плюс, ни в минус.
    # Они остаются в объяснении как контекст: сколько всего есть, что можно
    # было бы сверить, когда появится чем.
    active = [item for item in evidence if item.status != DECLINED and item.statement_ids]

    units = resolved_contradictions * FIRST_IN_CATEGORY
    score = _to_score(units, CONSISTENCY)

    if open_contradictions:
        explanation = (
            f"Нестыковок, ожидающих разбора: {open_contradictions}. На балл они не влияют — "
            "разбор их добавит."
        )
    elif resolved_contradictions:
        explanation = (
            f"Разобранных нестыковок: {resolved_contradictions}. Профиль от разбора стал точнее."
        )
    elif active:
        explanation = (
            f"Пока не измерено: проверок на противоречия между вашими сведениями "
            f"({len(active)} доказательств) продукт делает мало, и ни одна из них "
            "ничего не нашла. Это не оценка — просто нечего засчитать."
        )
    else:
        explanation = "В профиле пока нет доказательств, которые можно было бы сверить между собой."

    notes = [
        "Здесь считаются только разобранные нестыковки. Количество доказательств "
        "непротиворечивость не доказывает — оно работает в PROF.индексе, где меряется "
        "именно покрытие."
    ]
    if open_findings:
        notes.append(
            f"Источников, про которые мы не знаем, ваши ли они: {open_findings}. Ответ на "
            "вопрос ничего не отнимает в любом случае."
        )

    return ComponentScore(CONSISTENCY, score, explanation, [item.id for item in active], notes)


# --- общий балл -----------------------------------------------------------


def overall(components: list[ComponentScore]) -> int:
    """Взвешенная сумма компонентов - не среднее (FR1.5).

    Здесь тоже только сложение: каждый компонент добавляет свою долю, и ни при
    каких данных итог не уходит ниже нуля.
    """
    total = 0.0
    for component in components:
        total += component.score * COMPONENT_WEIGHT[component.component_id]
    return max(0, min(100, round(total)))


# --- локальные проверки непротиворечивости (§5.1) ------------------------


@dataclass(frozen=True)
class LevelMismatch:
    """Заявленный уровень против того, как кандидат описывает свою работу."""

    statement_id: str
    evidence_id: str
    level: str
    markers: tuple[str, ...]


def find_level_mismatch(
    claimed_levels: list[str], texts: list[tuple[str, str, str]]
) -> list[LevelMismatch]:
    """FR-Cons.2: заявлен Senior, а работа описана как чужие поручения.

    Эвристика MVP на очевидных формулировках, а не классификатор уровня. Она
    ничего не решает за кандидата: находка идёт в разбор, где он сам выбирает,
    что с ней делать.

    `texts` - тройки (statement_id, evidence_id, текст).
    """
    if not any(level in SENIOR_CLAIM_LEVELS for level in claimed_levels):
        return []

    found: list[LevelMismatch] = []
    for statement_id, evidence_id, text in texts:
        markers = tuple(
            pattern.pattern for pattern in _MARKER_PATTERNS if pattern.search(text or "")
        )
        if markers:
            found.append(
                LevelMismatch(
                    statement_id=statement_id,
                    evidence_id=evidence_id,
                    level="Senior",
                    markers=markers,
                )
            )
    return found


def severity_for(markers_count: int) -> str:
    """Порог серьёзности - калибруемая величина, по умолчанию мягкая."""
    return "major" if markers_count >= MAJOR_SEVERITY_MIN_SIGNALS else "minor"


def unlinked_sources(evidence: list[EvidenceFacts]) -> list[EvidenceFacts]:
    """Кандидатские источники, не привязанные ни к одной компетенции.

    Локальный производитель находок Case 1: система не лезет наружу и не
    собирает ничего пассивно - она спрашивает только про то, что кандидат сам
    же и принёс (FR-Cons.3).
    """
    return [
        item
        for item in evidence
        if item.type in (TYPE_LINK, TYPE_FILE)
        and item.status != DECLINED
        and not item.statement_ids
    ]
