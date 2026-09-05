"""Разбор текста вакансии на требования — «фильтр Б» (модули 10 и 15).

**Честно про происхождение.** Модуль 10 в этой фазе потребляет уже
обработанный набор вакансий: живого парсинга нет, и разбирающего движка вместе
с ним не было. FRD модуля 15 просит «переиспользовать существующую логику
фильтра Б», а переиспользовать было нечего. Поэтому движок написан здесь - и
написан так, чтобы набор модуля 10 мог быть его выходом, а не отдельной
параллельной формой.

Разбор детерминированный: те же образцы таксономии модуля 2, никакой языковой
модели. Это сознательное ограничение, а не временная заглушка - и там, где
образца нет, требование честно помечается как «вне эталонов», а не додумывается.
"""

import re
from dataclasses import dataclass

from app.reference import LEVELS, get_profile
from app.taxonomy import BY_KEY, TAXONOMY
from app.vacancies import MANDATORY, NICE_TO_HAVE

# --- как отличить обязательное от желательного ----------------------------
#
# Списки нарочно короткие и буквальные. Угадывать намерение работодателя по
# тону текста этот модуль не берётся: где формулировка неоднозначна, требование
# считается обязательным - так рекрутеру виднее, что перепроверить.

NICE_MARKERS = (
    r"будет плюсом",
    r"плюсом будет",
    r"желательн",
    r"приветствуетс",
    r"как преимущество",
    r"не обязательн",
    r"nice[ -]to[ -]have",
    r"опционально",
)

MANDATORY_MARKERS = (
    r"обязательн",
    r"требуетс",
    r"необходим",
    r"must[ -]have",
    r"без этого никак",
)

_NICE = tuple(re.compile(marker, re.IGNORECASE) for marker in NICE_MARKERS)
_MANDATORY = tuple(re.compile(marker, re.IGNORECASE) for marker in MANDATORY_MARKERS)

# Граница поиска маркера вокруг найденного упоминания: маркер из соседнего
# абзаца к этому требованию отношения не имеет.
MARKER_WINDOW = 160

# Какое доказательство закрыло бы требование. Подсказка рекрутеру, а не
# сгенерированный вопрос: живой вопрос кандидату задаёт модуль 4, и делать это
# из плагина мы не будем.
EVIDENCE_HINT_RU = {
    "Hard Skill": "Ссылка на репозиторий или разбор кейса с этим стеком",
    "Practical Understanding": "Описание решения своими словами: развилки и почему выбрали так",
    "Professional Footprint": "Публичный след: статья, доклад, профиль с активностью",
    "Complexity of Solved Tasks": "Описание задачи с числами: масштаб, нагрузка, сроки",
}

DEFAULT_HINT_RU = "Ссылка, файл или описание кейса, где это видно"

# Стек, который вакансии просят, а таксономия модуля 2 не описывает: она про
# то, что заявляют о себе кандидаты, и покрывает один сегмент. Без этого списка
# «требование вне эталонов» - канонический пример из FRD - вообще не находилось
# бы, и вся честная пометка про непокрытые требования оказалась бы мёртвой.
#
# Список короткий и будет расти по мере появления реальных объявлений. Смысл не
# в полноте, а в том, чтобы непокрытое было названо, а не пропало.
BEYOND_LIBRARY: tuple[tuple[str, str], ...] = (
    ("ClickHouse", r"clickhouse|кликхаус"),
    ("Terraform", r"terraform|терраформ"),
    ("Elasticsearch", r"elastic ?search|эластик"),
    ("Управление командой", r"управлени\w* команд|тимлид|руководств\w* командой|people management"),
    ("Найм и собеседования", r"найм|собеседовани\w* кандидат|проводить интервью"),
)

_BEYOND = tuple((name, re.compile(pattern, re.IGNORECASE)) for name, pattern in BEYOND_LIBRARY)


@dataclass(frozen=True)
class ExtractedRequirement:
    """Та же форма, что у требования вакансии в модуле 10 (§4.1 там)."""

    competency_id: str | None
    taxonomy_key: str | None
    label_ru: str
    criticality: str
    evidence_hint_ru: str
    matched_text: str


def _competency_by_key() -> dict[str, str]:
    """Ключ таксономии -> компетенция эталона, если она там вообще есть."""
    found: dict[str, str] = {}
    for level in LEVELS:
        for competency in get_profile(level).competencies:
            for key in competency.taxonomy_keys:
                found.setdefault(key, competency.competency_id)
    return found


_COMPETENCY_BY_KEY = _competency_by_key()


_SENTENCE_BREAK = re.compile(r"[.!?;\n•·—]|\s-\s")


def _sentence_around(text: str, position: int) -> str:
    """Предложение, в котором упомянуто требование.

    Границы предложения важнее расстояния в символах: «Обязательно Python и
    REST API. Будет плюсом Kubernetes» - здесь REST API ближе к «плюсом», но
    относится он к «обязательно», и человек читает это именно так.
    """
    start = 0
    for match in _SENTENCE_BREAK.finditer(text, 0, position):
        start = match.end()
    end_match = _SENTENCE_BREAK.search(text, position)
    end = end_match.start() if end_match else len(text)
    return text[start:end]


def _has(patterns, fragment: str) -> bool:
    return any(pattern.search(fragment) for pattern in patterns)


def _criticality_near(text: str, position: int) -> str:
    """Критичность по маркеру: сперва в своём предложении, потом рядом.

    Где однозначного маркера нет вообще, требование считается обязательным:
    рекрутеру полезнее перепроверить лишнее, чем не заметить нужное.
    """
    sentence = _sentence_around(text, position)
    if _has(_MANDATORY, sentence):
        return MANDATORY
    if _has(_NICE, sentence):
        return NICE_TO_HAVE

    window = text[max(0, position - MARKER_WINDOW) : position + MARKER_WINDOW]
    if _has(_MANDATORY, window):
        return MANDATORY
    return NICE_TO_HAVE if _has(_NICE, window) else MANDATORY


def extract(text: str) -> list[ExtractedRequirement]:
    """Требования из текста объявления.

    Порядок сохраняется по первому упоминанию: так список читается вместе с
    исходным текстом, а не как отсортированная непонятно чем выжимка.
    """
    if not (text or "").strip():
        return []

    found: dict[str, ExtractedRequirement] = {}

    for competency in TAXONOMY:
        earliest = None
        # Образцы уже скомпилированы в таксономии модуля 2 - берём их как есть,
        # а не собираем рядом второй набор регулярных выражений.
        for pattern in competency.regexes:
            match = pattern.search(text)
            if match and (earliest is None or match.start() < earliest.start()):
                earliest = match
        if earliest is None:
            continue

        found[competency.key] = ExtractedRequirement(
            competency_id=_COMPETENCY_BY_KEY.get(competency.key),
            taxonomy_key=competency.key,
            label_ru=competency.ru,
            criticality=_criticality_near(text, earliest.start()),
            evidence_hint_ru=EVIDENCE_HINT_RU.get(competency.category, DEFAULT_HINT_RU),
            matched_text=earliest.group(0),
        )

    for name, pattern in _BEYOND:
        match = pattern.search(text)
        if match is None or name in found:
            continue
        found[name] = ExtractedRequirement(
            competency_id=None,
            taxonomy_key=name,
            label_ru=name,
            criticality=_criticality_near(text, match.start()),
            evidence_hint_ru=DEFAULT_HINT_RU,
            matched_text=match.group(0),
        )

    ordered = sorted(found.values(), key=lambda item: text.lower().find(item.matched_text.lower()))

    # Обязательное вперёд - то же правило приоритета, что у белых пятен
    # модуля 3 и рекомендаций модуля 10 (FR2.3).
    return sorted(ordered, key=lambda item: 0 if item.criticality == MANDATORY else 1)


def unknown_requirements(items: list[ExtractedRequirement]) -> list[ExtractedRequirement]:
    """Требования, которых нет ни в одном эталоне роли.

    Их существование - не дефект разбора, а факт про вакансию: эталонная
    библиотека покрывает один сегмент, и делать вид, что она покрывает всё,
    было бы хуже, чем сказать прямо.
    """
    return [item for item in items if item.competency_id is None]
