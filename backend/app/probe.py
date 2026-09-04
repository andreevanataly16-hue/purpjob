"""Contextual Probe: подбор цели, генерация вопроса и разбор ответа.

Вопрос собирается на пересечении неподтверждённой компетенции и конкретной
детали из материалов самого кандидата (§5.2 FRD) - это не банк готовых
вопросов: одна и та же заготовка у двух людей даёт разные вопросы, потому что
цитата берётся из их собственного описания.

Сама формулировка сейчас собирается детерминированно, без языковой модели:
ключа API в проекте нет. Точка подключения одна - `generate_question`, у неё
интерфейс из §7 FRD (`компетенция + артефакты + режим -> вопрос`), поэтому
замена генератора не затрагивает вызывающий код. Режимов три: вопрос вокруг
артефакта, запасной шаблон и абстрактная переформулировка после отказа по NDA.

Правильного ответа модуль не хранит и ни с чем не сверяет (US3): ответ
оценивается только на конкретность, а не на совпадение со строкой-ключом.

Проверки «слишком общо» и «не прозвучал ключевой термин» - эвристики-заглушки
того же класса, что эвристика сложности в модуле 3: они ждут калибровки и не
должны выдаваться за проверенную модель.
"""

import re
from dataclasses import dataclass

from app.probe_templates import BY_COMPETENCY, DEFAULT_FOLLOW_UP, Template
from app.taxonomy import BY_KEY, TAXONOMY

# --- калибруемые пороги ---------------------------------------------------

# Ответ короче этого считаем заведомо неразвёрнутым.
MIN_ANSWER_WORDS = 12
# Ответ длиннее MIN_ANSWER_WORDS, но без единой конкретики (числа, технологии),
# всё ещё нечего проверять - до этой длины.
GENERIC_WORDS_LIMIT = 25

QUOTE_LIMIT = 170

TOO_GENERIC = "too_generic"
JARGON_TRAP = "jargon_trap"

# Режимы генерации из §7 FRD.
MODE_GROUNDED = "artifact_grounded"
MODE_NDA = "ndaAbstract"
MODE_FALLBACK = "fallback_template"

# Единственный допустимый формат ответа (US3, FR3.1).
FREE_TEXT = "free_text"

TARGET_WHITE_SPOT = "white_spot"
TARGET_CONTRADICTION = "contradiction"

_SENTENCES = re.compile(r"(?<=[.!?;])\s+|\n+")
_HAS_DIGIT = re.compile(r"\d")


@dataclass(frozen=True)
class Artifact:
    """Материал кандидата, из которого можно взять деталь для вопроса."""

    evidence_id: str
    kind: str  # text | source
    content: str


@dataclass(frozen=True)
class GeneratedQuestion:
    template_id: str
    text_ru: str
    # Объяснение «почему этот вопрос» рождается вместе с вопросом, а не
    # дописывается потом: без него вопрос показывать нельзя (FR4.1).
    reason_ru: str
    artifact_evidence_id: str | None
    grounded: bool
    nda_abstract: bool
    expected_terms: tuple[str, ...]
    follow_up: str


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCES.split(text or "") if s.strip()]


def _mentions(text: str, keys: tuple[str, ...]) -> bool:
    """Упоминается ли в тексте хоть один из навыков таксономии."""
    return any(
        any(rx.search(text) for rx in BY_KEY[key].regexes) for key in keys if key in BY_KEY
    )


def pick_detail(artifacts: list[Artifact], taxonomy_keys: tuple[str, ...]) -> Artifact | None:
    """Ищет в материалах кандидата фрагмент, к которому можно привязать вопрос.

    Предпочтение - предложению, где компетенция реально упоминается: вопрос
    должен цепляться за то, что человек написал сам, а не за случайную строку.
    """
    best: tuple[int, Artifact] | None = None

    for artifact in artifacts:
        if artifact.kind != "text":
            continue
        for sentence in _sentences(artifact.content):
            if len(sentence) < 25:
                continue
            score = 0
            if _mentions(sentence, taxonomy_keys):
                score += 10
            if _HAS_DIGIT.search(sentence):
                score += 3
            score += min(len(sentence), 200) // 50
            if best is None or score > best[0]:
                shortened = (
                    sentence if len(sentence) <= QUOTE_LIMIT
                    else sentence[:QUOTE_LIMIT].rsplit(" ", 1)[0] + "…"
                )
                best = (score, Artifact(artifact.evidence_id, "text", shortened))

    if best is not None and best[0] >= 10:
        return best[1]

    # Ссылка или файл - тоже материал кандидата, хоть и без цитаты.
    for artifact in artifacts:
        if artifact.kind == "source":
            return artifact

    return best[1] if best is not None else None


def _choose_template(
    competency_id: str, slot: str, used_template_ids: set[str], fresh_only: bool = False
) -> Template | None:
    options = [t for t in BY_COMPETENCY.get(competency_id, ()) if t.slot == slot]
    if not options:
        return None
    fresh = [t for t in options if t.id not in used_template_ids]
    if fresh:
        return fresh[0]
    return None if fresh_only else options[0]


def build_reason(competency_name_ru: str, target_type: str, mode: str) -> str:
    """«Почему этот вопрос» - обязательная строка рядом с вопросом (FR4.1).

    Формулировка зависит от того, что именно проверяется: пробел в
    доказательствах или расхождение в профиле. Одной общей фразой на оба
    случая обойтись нельзя (FR4.2).
    """
    if mode == MODE_NDA:
        return (
            f"Тот же предмет проверки — {competency_name_ru}, но без привязки к вашему "
            "проекту: раскрывать материалы не нужно."
        )
    if target_type == TARGET_CONTRADICTION:
        return (
            f"Этот вопрос проверяет: {competency_name_ru} — в профиле есть расхождение "
            "по этой теме, и его стоит прояснить."
        )
    return (
        f"Этот вопрос проверяет: {competency_name_ru} — по этой теме пока недостаточно "
        "независимых подтверждений."
    )


def build_follow_up_reason(competency_name_ru: str, trigger_reason: str) -> str:
    """Уточнение тоже не должно появляться из ниоткуда (FR4.3)."""
    if trigger_reason == JARGON_TRAP:
        return (
            f"Уточнение по той же компетенции — {competency_name_ru}. В ответе не хватает "
            "детали, по которой видно практика."
        )
    return (
        f"Уточнение по той же компетенции — {competency_name_ru}. Пока в ответе нет "
        "механики, которую можно проверить."
    )


def generate_question(
    competency_id: str,
    artifacts: list[Artifact],
    taxonomy_keys: tuple[str, ...] = (),
    used_template_ids: set[str] | None = None,
    mode: str = MODE_GROUNDED,
    competency_name_ru: str = "",
    target_type: str = TARGET_WHITE_SPOT,
) -> GeneratedQuestion | None:
    """Интерфейс генерации из §7 FRD: компетенция + артефакты + режим -> вопрос.

    Возвращает None, если для компетенции нет подходящей заготовки - выдумывать
    вопрос «на всякий случай» модуль не имеет права (FR1.5).
    """
    used = used_template_ids or set()
    name = competency_name_ru or competency_id

    def build(template: Template, detail: Artifact | None, nda: bool) -> GeneratedQuestion:
        return GeneratedQuestion(
            template_id=template.id,
            text_ru=template.text.format(detail=detail.content) if detail else template.text,
            reason_ru=build_reason(name, target_type, mode),
            artifact_evidence_id=detail.evidence_id if detail else None,
            grounded=template.grounded and detail is not None,
            nda_abstract=nda,
            expected_terms=template.expected_terms,
            follow_up=template.follow_up or DEFAULT_FOLLOW_UP,
        )

    if mode == MODE_NDA:
        template = _choose_template(competency_id, "nda", used)
        return build(template, None, True) if template else None

    if mode == MODE_GROUNDED:
        detail = pick_detail(artifacts, taxonomy_keys)
        if detail is not None:
            slot = "quote" if detail.kind == "text" else "source"

            # Сначала - неиспользованная заготовка под этот артефакт.
            template = _choose_template(competency_id, slot, used, fresh_only=True)
            if template is not None:
                return build(template, detail, False)

            # Свежих под артефакт нет: лучше задать запасной вопрос, чем
            # повторить кандидату тот же самый - особенно после жалобы на него.
            spare = _choose_template(competency_id, "none", used, fresh_only=True)
            if spare is not None:
                return build(spare, None, False)

            template = _choose_template(competency_id, slot, used)
            if template is not None:
                return build(template, detail, False)

    # Запасной путь (FR2.4): артефакта нет или он не подошёл. Вопрос помечен
    # как негрунтованный, чтобы в аналитике не смешиваться с основным путём.
    template = _choose_template(competency_id, "none", used)
    return build(template, None, False) if template else None


# --- разбор ответа --------------------------------------------------------


def is_too_generic(text: str) -> bool:
    """FR3.1: в ответе нет механики, которую можно проверить.

    Эвристика, а не понимание смысла: слишком короткий ответ либо ответ без
    единой зацепки - чисел, названий технологий.
    """
    words = len((text or "").split())
    if words < MIN_ANSWER_WORDS:
        return True
    if words >= GENERIC_WORDS_LIMIT:
        return False

    has_number = bool(_HAS_DIGIT.search(text))
    has_term = any(any(rx.search(text) for rx in c.regexes) for c in TAXONOMY)
    return not (has_number or has_term)


def missing_expected_terms(text: str, expected_terms: tuple[str, ...]) -> bool:
    """FR3.2: практик почти неизбежно назовёт хоть одно из этих слов."""
    if not expected_terms:
        return False
    lowered = (text or "").lower()
    return not any(term in lowered for term in expected_terms)


def follow_up_reason(text: str, expected_terms: tuple[str, ...]) -> str | None:
    """Один уточняющий вопрос, не больше (FR3.1)."""
    if is_too_generic(text):
        return TOO_GENERIC
    if missing_expected_terms(text, expected_terms):
        return JARGON_TRAP
    return None


def understanding_signal(text: str, expected_terms: tuple[str, ...]) -> bool:
    """Показывает ли ответ понимание логики (FR5.1а).

    Сюда попадает уже полный текст - вместе с ответом на уточняющий вопрос,
    если он задавался: человек, который договорил конкретику со второй попытки,
    понимает не хуже того, кто сразу написал развёрнуто.
    """
    return follow_up_reason(text, expected_terms) is None
