"""Разбор свободного текста и расчёт статуса компетенции.

Здесь живут две вещи, которые FRD требует держать детерминированными:

1. Разбор описания проекта в компетенции (FR2.2). Сейчас это не языковая
   модель, а сопоставление с таксономией: внешних вызовов нет, ключей API не
   нужно, результат воспроизводим. Функция `parse_free_text` - единственное
   место, которое придётся заменить, когда появится LLM; формат её ответа уже
   рассчитан на это (компетенция + цитата + уверенность).
2. Статус компетенции (§3.4 FRD). Правило табличное и проверяемое, не ML:
   кандидат должен понимать, почему у него именно этот статус.

Две договорённости, которые важно не потерять:

* `pending` у доказательства - это техническое состояние, а не оценка. Оно
  означает «доказательство создано», а не «доказательство под сомнением»;
  подробнее - рядом с самими константами статусов.
* Из текста в профиль попадают только положительные утверждения. «Мы
  отказались от Redis» и «я не работал с Kubernetes» компетенцию не создают.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.taxonomy import TAXONOMY

# --- значения enum из §3.1-3.2 FRD; в коде только английские -------------

NOT_STARTED = "not_started"
LIMITED = "limited"
MEDIUM = "medium"
STRONG = "strong"

# Статусы доказательства (§3.2 FRD). Семантика зафиксирована так:
#
#   pending   - доказательство создано и учитывается. Это техническое
#               состояние обработки, а НЕ уровень доверия и не «пока не
#               считается»: внешней проверки источников в MVP нет вообще, и
#               ждать от неё нечего. §3.4 FRD считает статус компетенции по
#               всем непринятым-в-отказ доказательствам, то есть по pending в
#               том числе;
#   confirmed - зарезервировано под будущую внешнюю проверку источника
#               (модуль 8/9). Сейчас его никто не выставляет;
#   declined  - кандидат отказался раскрывать источник. Единственный статус,
#               который выключает доказательство из расчёта, и он не штраф:
#               статус компетенции просто считается так, будто источника не
#               добавляли.
PENDING = "pending"
CONFIRMED = "confirmed"
DECLINED = "declined"

TYPE_LINK = "link"
TYPE_FILE = "file"
TYPE_FREE_TEXT = "free_text"
TYPE_BLIND_WITNESS = "blind_witness_answer"

EVIDENCE_TYPES = (TYPE_LINK, TYPE_FILE, TYPE_FREE_TEXT, TYPE_BLIND_WITNESS)
SOURCE_CATEGORIES = ("github", "gitlab", "linkedin", "portfolio", "article", "video", "other")

# Домены, по которым источник считается узнаваемым (FR1.2). Всё прочее - other.
_DOMAIN_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("github.com", "github"),
    ("gist.github.com", "github"),
    ("gitlab.com", "gitlab"),
    ("linkedin.com", "linkedin"),
    ("habr.com", "article"),
    ("medium.com", "article"),
    ("dev.to", "article"),
    ("youtube.com", "video"),
    ("youtu.be", "video"),
    ("vimeo.com", "video"),
    ("rutube.ru", "video"),
    ("behance.net", "portfolio"),
    ("dribbble.com", "portfolio"),
)

# Как назвать источник кандидату - для строки «почему такой статус».
_SOURCE_LABELS = {
    "github": "GitHub",
    "gitlab": "GitLab",
    "linkedin": "LinkedIn",
    "portfolio": "портфолио",
    "article": "статья",
    "video": "видео",
    "other": "ссылка",
    TYPE_FILE: "файл",
    TYPE_FREE_TEXT: "ваше описание",
    TYPE_BLIND_WITNESS: "ответ Слепого свидетеля",
}


def source_category_from_url(url: str) -> str:
    """Определяет источник по домену (FR1.2). Неизвестный домен - `other`."""
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    for domain, category in _DOMAIN_CATEGORIES:
        if host == domain or host.endswith("." + domain):
            return category
    return "other"


# --- статус компетенции (§3.4) -------------------------------------------


@dataclass(frozen=True)
class EvidenceFacts:
    """Только то, что нужно для расчёта статуса.

    Отдельный тип вместо модели БД: правило §3.4 проверяется тестами без
    базы, и его легко перенести, когда расчёт понадобится модулю 5.
    """

    type: str
    source_category: str | None
    status: str


@dataclass(frozen=True)
class StatusView:
    """Статус вместе с объяснением - показывать порознь запрещено (FR3.4)."""

    status: str
    reason: str
    next_action: str
    next_action_kind: str


def is_independent(fact: EvidenceFacts) -> bool:
    """Независимое ли доказательство.

    Файл и ответ Слепого свидетеля - да: первый существует отдельно от слов
    кандидата, второй по FR4.5 приравнен к независимому источнику. Ссылка -
    только на узнаваемую площадку: произвольный URL проверить нечем, поэтому
    он остаётся словами кандидата (в §3.4 это «unverified link»).
    """
    if fact.type in (TYPE_FILE, TYPE_BLIND_WITNESS):
        return True
    return fact.type == TYPE_LINK and fact.source_category not in (None, "other")


def category_key(fact: EvidenceFacts) -> str:
    """Ключ, по которому источники считаются «разными» для статуса Strong."""
    if fact.type == TYPE_LINK:
        return fact.source_category or "other"
    return fact.type


def _label(fact: EvidenceFacts) -> str:
    return _SOURCE_LABELS.get(category_key(fact), "источник")


def _enumerate(facts: list[EvidenceFacts]) -> str:
    """«GitHub, файл и ответ Слепого свидетеля» - без повторов."""
    labels: list[str] = []
    for fact in facts:
        label = _label(fact)
        if label not in labels:
            labels.append(label)
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " и " + labels[-1]


def compute_status(facts: list[EvidenceFacts]) -> StatusView:
    """Таблица §3.4 FRD. Отклонённые доказательства в расчёт не входят и
    статус не понижают - отказ ничего не отнимает (FR4.3)."""
    active = [f for f in facts if f.status != DECLINED]

    if not active:
        return StatusView(
            NOT_STARTED,
            "Эту компетенцию пока ничего не подтверждает.",
            "Добавьте ссылку на источник, файл или опишите проект.",
            "add_link",
        )

    independent = [f for f in active if is_independent(f)]
    distinct = {category_key(f) for f in active}

    if len(active) >= 2 and len(distinct) >= 2 and independent:
        return StatusView(
            STRONG,
            f"Подтверждено из разных источников: {_enumerate(active)}. "
            "Здесь доказательная база уже собрана.",
            "",
            "none",
        )

    if independent:
        if all(f.type == TYPE_BLIND_WITNESS for f in independent):
            reason = (
                "Подтверждено ответом Слепого свидетеля — раскрывать материалы "
                "не потребовалось."
            )
        else:
            reason = f"Есть независимое подтверждение: {_enumerate(independent)}."
        return StatusView(
            MEDIUM,
            reason + " Источник другого типа поднимет статус до «Сильно».",
            "Добавьте источник другого типа — например, файл или ссылку на площадку.",
            "add_file",
        )

    if len(active) >= 2:
        return StatusView(
            MEDIUM,
            f"Подтверждений несколько ({len(active)}), но все они с ваших слов.",
            "Независимый источник поднимет статус до «Сильно»: ссылка на площадку, "
            "файл или ответ на вопрос Слепого свидетеля.",
            "add_link",
        )

    return StatusView(
        LIMITED,
        f"Одно подтверждение ({_enumerate(active)}), и оно с ваших слов — "
        "независимого источника пока нет.",
        "Добавьте ссылку на внешний источник или ответьте на вопрос Слепого "
        "свидетеля — материалы раскрывать не нужно.",
        "blind_witness",
    )


# --- разбор свободного текста (FR2.2) ------------------------------------

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")
_EXCERPT_LIMIT = 220

# Тип утверждения о компетенции. Сейчас в профиль попадает только positive;
# остальные значения существуют, чтобы разбор можно было заменить на модель,
# не меняя формат ответа.
POSITIVE = "positive"
NEGATIVE = "negative"
HYPOTHETICAL = "hypothetical"
UNCLEAR = "unclear"

# Отрицание в русском стоит прямо перед тем, что отрицает: «отказались от
# Redis», «не работал с Kubernetes». Но действует оно только до ближайшей
# границы части предложения - иначе «не работал с Kubernetes, но занимался
# Docker» отняло бы заодно и Docker.
_CLAUSE_BREAK = re.compile(r"[,;:—]|\bи\b|\bно\b|\bа\b|\bзато\b|\bоднако\b|\bпоэтому\b")

_NEGATIONS = (
    "не работал",
    "не использ",
    "не занима",
    "не приходилось",
    "не довелось",
    "не трогал",
    "не писал",
    "не знаю",
    "нет опыта",
    "без опыта",
    "отказал",
    "отказыва",
    "ушли от",
    "ушёл от",
    "избега",
    "перестал",
    "выпилил",
    "убрал",
    "заменили",
    "вместо",
    "решили не",
    "не стал",
    "не будем",
    "не буду",
)

# «Не только Redis, но и Kafka» - это не отрицание.
_NEGATION_EXCEPTIONS = ("не только",)

_HYPOTHETICALS = (
    "если бы",
    "было бы",
    "хотел бы",
    "хочу научиться",
    "хочу освоить",
    "планиру",
    "собира",
    "предстоит",
    "буду изучать",
)


@dataclass(frozen=True)
class ParsedItem:
    skill_name: str
    skill_name_ru: str
    category: str
    excerpt: str
    confidence: str
    assertion_type: str = POSITIVE


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def assertion_type(sentence: str, match_start: int) -> str:
    """Что именно сказано про найденный навык.

    Простая защита от ложных компетенций: «мы отказались от Redis» не значит,
    что у кандидата есть опыт с Redis. Смотрим текст непосредственно перед
    упоминанием - в русском отрицание стоит прямо перед тем, что отрицает.

    Это MVP-эвристика, а не разбор смысла: она ловит очевидные конструкции и
    сознательно не претендует на большее. Когда разбор заменят моделью, тип
    утверждения будет приходить оттуда - формат ответа уже это допускает.
    """
    lowered = sentence.lower()

    # Берём кусок предложения от ближайшей границы части до самого упоминания
    # и такой же кусок после него: по-русски отрицание встаёт и до навыка
    # («не работал с Kubernetes»), и после («с Kubernetes не работал»).
    start = 0
    for separator in _CLAUSE_BREAK.finditer(lowered[:match_start]):
        start = separator.end()

    tail_start = match_start
    tail_break = _CLAUSE_BREAK.search(lowered[tail_start:])
    tail_end = tail_start + tail_break.start() if tail_break else len(lowered)

    window = lowered[start:match_start] + " " + lowered[tail_start:tail_end]

    if any(exception in lowered[:match_start] for exception in _NEGATION_EXCEPTIONS):
        return POSITIVE

    if any(marker in window for marker in _HYPOTHETICALS):
        return HYPOTHETICAL

    if any(marker in window for marker in _NEGATIONS):
        return NEGATIVE

    return POSITIVE


def _shorten(sentence: str) -> str:
    if len(sentence) <= _EXCERPT_LIMIT:
        return sentence
    return sentence[:_EXCERPT_LIMIT].rsplit(" ", 1)[0] + "…"


def parse_free_text(text: str) -> list[ParsedItem]:
    """Достаёт компетенции из текста кандидата.

    Текст не правится и не переписывается (FR2.6): цитата берётся дословно из
    того предложения, где нашлось совпадение. Ничего не сохраняется - решение
    принимает кандидат на следующем шаге (FR2.3).
    """
    sentences = _sentences(text)
    if not sentences:
        return []

    items: list[ParsedItem] = []

    for competency in TAXONOMY:
        hits = 0
        matched_sentences: list[str] = []

        for sentence in sentences:
            found_here = sum(
                1
                for rx in competency.regexes
                for match in rx.finditer(sentence)
                if assertion_type(sentence, match.start()) == POSITIVE
            )
            if found_here:
                hits += found_here
                matched_sentences.append(sentence)

        # Компетенция, о которой в тексте сказано только «не работал» или
        # «отказались от», в профиль не попадает вовсе.
        if not hits:
            continue

        # Уверенность - это не оценка качества опыта, а плотность упоминаний:
        # одно слово вскользь и абзац про одно и то же - разные вещи.
        if hits >= 3 or len(matched_sentences) >= 2:
            confidence = "high"
        elif hits == 2:
            confidence = "medium"
        else:
            confidence = "low"

        items.append(
            ParsedItem(
                skill_name=competency.key,
                skill_name_ru=competency.ru,
                category=competency.category,
                excerpt=_shorten(matched_sentences[0]),
                confidence=confidence,
                assertion_type=POSITIVE,
            )
        )

    order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda item: (order[item.confidence], item.skill_name_ru))
    return items
