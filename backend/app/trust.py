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

from app.enrichment import DECLINED, TYPE_FILE, TYPE_LINK

# --- калибруемые константы -----------------------------------------------

AUTHENTICITY = "authenticity"
UNDERSTANDING = "understanding"
CONSISTENCY = "consistency"

COMPONENTS = (AUTHENTICITY, UNDERSTANDING, CONSISTENCY)

COMPONENT_RU = {
    AUTHENTICITY: "Самостоятельность",
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


def authenticity(probes: list[ProbeFacts]) -> ComponentScore:
    """Насколько ответы написаны самим кандидатом (FR1.2).

    Заблокированная попытка вставки ничего не отнимает: такой ответ просто не
    идёт в зачёт как самостоятельный (FR5.3). Клавиатурный почерк сюда не
    входит - его захват выключен до юридического заключения.
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
            f"Ответов, написанных без попыток вставки и прошедших проверку на шаблонность: "
            f"{len(independent)} из {len(probes)}."
        )
        if with_paste:
            explanation += (
                f" В {len(with_paste)} из них была попытка вставить текст — они просто не "
                "пошли в зачёт."
            )

    notes = []
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
    keys = [item.competency_id for item in passed] + [_category_key(e) for e in nda_confirmations]
    units = _weighted_sum(keys)
    score = _to_score(units, UNDERSTANDING)

    if not probes and not nda_confirmations:
        explanation = "Ни одного разобранного вживую ответа пока нет."
    else:
        parts = []
        if probes:
            parts.append(f"ответов Contextual Probe с подтверждённым пониманием: {len(passed)} из {len(probes)}")
        if nda_confirmations:
            parts.append(f"подтверждений под NDA: {len(nda_confirmations)}")
        explanation = "Засчитано: " + ", ".join(parts) + "."

    notes = []
    unresolved = [item for item in probes if item.had_follow_up and not item.resolved_after_follow_up]
    if unresolved:
        notes.append(
            f"Ответов, оставшихся общими после уточнения: {len(unresolved)}. Они не убавляют "
            "балл — просто пока ничего не подтверждают."
        )

    return ComponentScore(
        UNDERSTANDING, score, explanation, [e.id for e in nda_confirmations], notes
    )


def consistency(
    evidence: list[EvidenceFacts],
    open_contradictions: int,
    resolved_contradictions: int,
    open_findings: int,
) -> ComponentScore:
    """Насколько сведения профиля не спорят друг с другом (FR1.4).

    Открытое противоречие не отнимает баллов - оно просто не даёт зачесть
    доказательства как согласованные. Разница принципиальная: это ноль, а не
    минус (FR5.1).
    """
    # Считаются только доказательства, привязанные к компетенциям: источник,
    # который ни к чему не привязан, ничего не подтверждает - про него мы как
    # раз и спрашиваем отдельно.
    active = [item for item in evidence if item.status != DECLINED and item.statement_ids]
    units = _weighted_sum([_category_key(item) for item in active])

    # Разобранная нестыковка - плюс: профиль стал точнее. Открытая не отнимает
    # ничего, она просто пока не добавляет (FR5.1).
    units += resolved_contradictions * FIRST_IN_CATEGORY
    score = _to_score(units, CONSISTENCY)

    if open_contradictions:
        explanation = (
            f"Нестыковок, ожидающих разбора: {open_contradictions}. На балл они не влияют — "
            f"разбор их добавит. Доказательств в профиле: {len(active)}."
        )
    elif not active:
        explanation = "В профиле пока нет доказательств, которые можно было бы сверить между собой."
    else:
        explanation = (
            f"Нестыковок между вашими же сведениями не найдено; доказательств в профиле: "
            f"{len(active)}."
        )

    notes = []
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
