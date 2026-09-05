"""Канонический «почему» на весь продукт (модуль 7).

Модули 3, 4 и 6 уже обязаны объяснять свои выводы: у компетенции есть `reason`,
у вопроса - `reason_ru`, у компонента Trust - `explanation_ru`. Проблема была не
в отсутствии объяснений, а в том, что их три разных вида и кандидату пришлось бы
изучать три разных способа спросить «почему». Здесь они сводятся к одной форме.

Это адаптер, а не переписывание (§7 FRD): модули 3/4/6 продолжают считать так
же и хранить свои поля под своими именами. Отсюда их только читают.

Про идентификаторы. В спецификации `Explanation.id` показан как счётчик
(`expl_001`), но PROF и Trust у нас не хранятся, а пересчитываются на каждый
запрос (§8 FRD модуля 3). Счётчик означал бы, что после любого пересчёта спор
ссылается на несуществующее объяснение. Поэтому идентификатор собирается из
того, о чём объяснение, и переживает пересчёт: `expl_trust_authenticity` - это
всегда компонент «Признаки самостоятельной работы» этого кандидата.
"""

from dataclasses import dataclass
from datetime import datetime

# --- виды выводов, которые можно объяснить (§4.1) -------------------------

PROF_COMPETENCY_STATUS = "prof_competency_status"
TRUST_COMPONENT = "trust_component"
CONTRADICTION_FINDING = "contradiction_finding"
PROBE_QUESTION_REASON = "probe_question_reason"
# Модуль 11: почему система решила, что эта вакансия вам подходит.
VACANCY_MATCH = "vacancy_match"

SUBJECT_TYPES = (
    PROF_COMPETENCY_STATUS,
    TRUST_COMPONENT,
    CONTRADICTION_FINDING,
    PROBE_QUESTION_REASON,
    VACANCY_MATCH,
)

SUBJECT_TYPE_RU = {
    PROF_COMPETENCY_STATUS: "Статус компетенции в PROF.индексе",
    TRUST_COMPONENT: "Компонент Trust Score",
    CONTRADICTION_FINDING: "Нестыковка в профиле",
    PROBE_QUESTION_REASON: "Почему задан этот вопрос",
    VACANCY_MATCH: "Почему эта вакансия вам подходит",
}

MODULE_3 = "module_3"
MODULE_4 = "module_4"
MODULE_6 = "module_6"

# Единая точка входа рядом с любым баллом или статусом (FR1.3). Одна на весь
# продукт: три разных формулировки для трёх модулей - ровно та проблема,
# которую этот модуль и решает.
WHY_LABEL_RU = "Почему такой вывод?"
DISPUTE_LABEL_RU = "Оспорить и передать на модерацию"


@dataclass(frozen=True)
class Explanation:
    """Один вывод системы в канонической форме (§4.1)."""

    id: str
    subject_type: str
    subject_id: str
    conclusion_ru: str
    evidence_refs: tuple[str, ...]
    generated_by: str
    created_at: datetime

    # Что именно объясняется - чтобы экран объяснения не был безымянным.
    subject_label_ru: str = ""
    subject_value_ru: str = ""

    # Задел под показ рекрутеру (§2.2): рекрутерской стороны ещё нет, поле
    # никем не читается и сознательно всегда False.
    candidate_consent_for_recruiter_view: bool = False


# --- идентификаторы -------------------------------------------------------
#
# Разбирать их обратно не нужно и не следует: объяснения собираются списком, а
# поиск идёт точным сравнением строки. Так идентификатор остаётся деталью
# формата, а не вторым способом добраться до данных в обход сборки.


def prof_explanation_id(level: str, competency_id: str) -> str:
    return f"expl_prof_{level}_{competency_id}"


def trust_explanation_id(component_id: str) -> str:
    return f"expl_trust_{component_id}"


def contradiction_explanation_id(case_public_id: str) -> str:
    return f"expl_contradiction_{case_public_id}"


def probe_explanation_id(question_public_id: str) -> str:
    return f"expl_probe_{question_public_id}"


def vacancy_explanation_id(vacancy_id: str) -> str:
    return f"expl_vacancy_{vacancy_id}"


# --- правила, которым обязано подчиняться любое объяснение ----------------

# Голый вердикт вместо факта (FR1.2). Список не претендует на полноту: он
# ловит формулировки, которые чаще всего просачиваются в текст вывода.
BARE_VERDICT_MARKERS = (
    "низкая достоверность",
    "высокая достоверность",
    "недостаточно надёжно",
    "недостаточно надежно",
    "выглядит подозрительно",
    "не вызывает доверия",
    "сомнительно",
    "неубедительно",
    "слабый профиль",
    "плохо",
    "хорошо",
)

# Как в тексте признаётся отсутствие доказательств (FR2.2): пустой список без
# слов - дефект, отсутствие тоже должно быть сказано фактом.
ABSENCE_MARKERS = (
    "нет ни одн",
    "не на чем считать",
    "пока нет",
    "ещё не",
    "еще не",
    "не найдено",
    "ни одного",
    "пока не",
    "нет доказательств",
    "нет ни",
)


def is_bare_verdict(conclusion_ru: str) -> bool:
    """FR1.2: вывод - проверяемый факт, а не оценка в общих словах."""
    text = (conclusion_ru or "").lower()
    return any(marker in text for marker in BARE_VERDICT_MARKERS)


def states_absence(conclusion_ru: str) -> bool:
    """Сказано ли в тексте прямо, что доказательств пока нет (FR2.2)."""
    text = (conclusion_ru or "").lower()
    return any(marker in text for marker in ABSENCE_MARKERS)


def validate(explanation: Explanation) -> list[str]:
    """Что не так с объяснением. Пустой список - всё в порядке.

    Проверка живёт здесь, а не в тестах, чтобы правило было одно на всех
    производителей объяснений, а не переписывалось в каждом модуле заново.
    """
    problems: list[str] = []

    if not (explanation.conclusion_ru or "").strip():
        problems.append("вывод без текста")
    if is_bare_verdict(explanation.conclusion_ru):
        problems.append("вывод сформулирован оценкой, а не проверяемым фактом")
    if not explanation.evidence_refs and not states_absence(explanation.conclusion_ru):
        problems.append("нет ссылок на доказательства, и в тексте не сказано, что их нет")
    if explanation.subject_type not in SUBJECT_TYPES:
        problems.append(f"неизвестный вид вывода: {explanation.subject_type}")

    return problems
