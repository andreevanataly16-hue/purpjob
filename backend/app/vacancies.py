"""Библиотека вакансий и расчёт Match Score (модуль 10).

Match Score - **проекция** уже посчитанного PROF.индекса на требования одной
конкретной вакансии, а не второй самостоятельный балл. Отсюда главное
ограничение модуля: он читает модуль 3 и не пишет в него ничего. Плохое
совпадение с одной вакансией не должно и не может испортить сам профиль -
вакансия может переоценивать свой уровень или странно расставлять веса, и это
свойство вакансии, а не кандидата.

Второе ограничение - продуктовое: это не инструмент «разослать сто откликов».
Ленты как бесконечного потока здесь нет, отклика нет вообще, счётчиков
просмотренных вакансий нет. Набор вакансий маленький и рукописный намеренно.

Живого парсинга в этой фазе нет: данные лежат версионируемым JSON, как эталоны
модуля 3 и сценарии модуля 5.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.prof import STATUS_SCORE
from app.reference import LEVELS, get_profile

SEED_DIR = Path(__file__).parent / "seed" / "vacancies"

# --- калибруемые константы -----------------------------------------------
#
# Насколько обязательное требование важнее желательного. Рабочая гипотеза, а не
# измеренная величина: держится константой, чтобы калибровка (Гл. 13) не
# требовала правки логики.

MANDATORY = "mandatory"
NICE_TO_HAVE = "nice_to_have"

CRITICALITY_WEIGHT = {MANDATORY: 1.0, NICE_TO_HAVE: 0.4}

CRITICALITY_RU = {MANDATORY: "обязательное", NICE_TO_HAVE: "желательное"}

# Статусы модуля 2, которые считаются подтверждением требования.
CONFIRMED_STATUSES = ("medium", "strong")

ROLE_BREADTH_RU = {
    "low": "одна функциональная область",
    "medium": "две смежные области",
    "high": "несколько разных функциональных областей",
}

ADD_EVIDENCE = "add_evidence"
ANSWER_EXISTING_PROBE = "answer_existing_probe"


@dataclass(frozen=True)
class Requirement:
    id: str
    competency_id: str | None
    taxonomy_key: str | None
    label_ru: str
    criticality: str


@dataclass(frozen=True)
class Cluster:
    cluster_label_ru: str
    reference_profile_id: str | None


@dataclass(frozen=True)
class Vacancy:
    id: str
    title_ru: str
    company_label: str
    stated_level: str
    filter_a_grade: str
    role_breadth: str
    functional_clusters: tuple[Cluster, ...]
    requirements: tuple[Requirement, ...]
    industry_context: str | None
    ai_leverage_flag: bool | None
    source_channels: tuple[str, ...]
    created_at: datetime


# --- загрузка и проверка набора -------------------------------------------


def _fail(vacancy_id: str, problem: str) -> None:
    raise ValueError(f"Вакансия {vacancy_id}: {problem}")


def _load() -> list[Vacancy]:
    """Читает набор при импорте и проверяет его.

    Проверки здесь не формальность: набор рукописный, и опечатка в
    `competency_id` тихо превратила бы требование в «вакансия-специфичное» -
    то есть поменяла бы маршрут рекомендации, ничего при этом не сломав.
    """
    known_competencies = {
        competency.competency_id
        for level in LEVELS
        for competency in get_profile(level).competencies
    }
    known_profiles = {get_profile(level).id for level in LEVELS}

    found: list[Vacancy] = []
    seen_ids: set[str] = set()

    for path in sorted(SEED_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for raw in data["vacancies"]:
            vacancy_id = raw["id"]
            if vacancy_id in seen_ids:
                _fail(vacancy_id, "такой идентификатор уже есть в наборе")
            seen_ids.add(vacancy_id)

            if raw["stated_level"] not in LEVELS:
                _fail(vacancy_id, f"уровень {raw['stated_level']} вне библиотеки эталонов")
            if raw["role_breadth"] not in ROLE_BREADTH_RU:
                _fail(vacancy_id, f"неизвестная широта роли {raw['role_breadth']}")
            if not raw["requirements"]:
                _fail(vacancy_id, "нет ни одного требования")
            if not raw["source_channels"]:
                _fail(vacancy_id, "нет источника - непонятно, откуда объявление")

            requirements = []
            for item in raw["requirements"]:
                if item["criticality"] not in CRITICALITY_WEIGHT:
                    _fail(vacancy_id, f"неизвестная критичность {item['criticality']}")
                if item["competency_id"] is not None and item["competency_id"] not in known_competencies:
                    _fail(
                        vacancy_id,
                        f"требование {item['id']} ссылается на компетенцию "
                        f"{item['competency_id']}, которой нет в эталонах",
                    )
                requirements.append(
                    Requirement(
                        id=item["id"],
                        competency_id=item["competency_id"],
                        taxonomy_key=item.get("taxonomy_key"),
                        label_ru=item["label_ru"],
                        criticality=item["criticality"],
                    )
                )

            clusters = []
            for item in raw["functional_clusters"]:
                profile_id = item["reference_profile_id"]
                if profile_id is not None and profile_id not in known_profiles:
                    _fail(vacancy_id, f"кластер ссылается на неизвестный эталон {profile_id}")
                clusters.append(
                    Cluster(
                        cluster_label_ru=item["cluster_label_ru"],
                        reference_profile_id=profile_id,
                    )
                )

            found.append(
                Vacancy(
                    id=vacancy_id,
                    title_ru=raw["title_ru"],
                    company_label=raw["company_label"],
                    stated_level=raw["stated_level"],
                    filter_a_grade=raw["filter_a_grade"],
                    role_breadth=raw["role_breadth"],
                    functional_clusters=tuple(clusters),
                    requirements=tuple(requirements),
                    industry_context=raw["industry_context"],
                    ai_leverage_flag=raw["ai_leverage_flag"],
                    source_channels=tuple(raw["source_channels"]),
                    created_at=datetime.fromisoformat(raw["created_at"]),
                )
            )

    if not found:
        raise ValueError("Набор вакансий пуст - ленту не из чего собрать.")
    return found


ALL: list[Vacancy] = _load()
BY_ID: dict[str, Vacancy] = {item.id: item for item in ALL}


def feed_for(level: str) -> list[Vacancy]:
    """Лента под заявленные уровни кандидата (FR1.2).

    Фильтр А здесь уже отработал на этапе подготовки набора: сюда попадают
    только объявления своей области. Остаётся отсечь чужой уровень - и не
    прятать при этом управленческие роли, если кандидат сам метит в Senior.
    """
    return sorted(
        (item for item in ALL if item.stated_level == level),
        key=lambda item: item.created_at,
        reverse=True,
    )


# --- расчёт совпадения ----------------------------------------------------


@dataclass(frozen=True)
class CompetencyState:
    """Что кандидат уже подтвердил - глазами модуля 10.

    Приходит из модуля 3 как есть: своей таблицы статусов у этого модуля нет и
    быть не должно.
    """

    by_competency: dict[str, str]
    by_skill: dict[str, str]


@dataclass
class RequirementView:
    requirement_id: str
    label_ru: str
    criticality: str
    status: str
    explanation_ru: str
    recommended_action: str | None = None
    competency_id: str | None = None


@dataclass
class MatchResult:
    vacancy_id: str
    overall_match_score: int
    covered: list[RequirementView] = field(default_factory=list)
    uncovered: list[RequirementView] = field(default_factory=list)
    unevaluated_clusters: list[str] = field(default_factory=list)
    cluster_scores: list[tuple[str, int]] = field(default_factory=list)


def _status_of(requirement: Requirement, state: CompetencyState) -> str:
    if requirement.competency_id:
        return state.by_competency.get(requirement.competency_id, "not_started")
    if requirement.taxonomy_key:
        return state.by_skill.get(requirement.taxonomy_key.lower(), "not_started")
    return "not_started"


def _covered_reason(requirement: Requirement, status: str) -> str:
    strength = "двумя независимыми источниками" if status == "strong" else "доказательствами в профиле"
    return f"{requirement.label_ru}: подтверждено {strength}."


def _uncovered_reason(requirement: Requirement, status: str) -> str:
    """Почему требование не закрыто - фактом, а не оценкой (FR3.2)."""
    if status == "not_started":
        if requirement.competency_id is None:
            return (
                f"{requirement.label_ru}: этого требования нет ни в одном эталоне роли, "
                "и в вашем профиле по нему пока нет ни одного доказательства."
            )
        return f"{requirement.label_ru}: в вашем профиле нет ни одного подтверждения."
    return (
        f"{requirement.label_ru}: доказательства есть, но их пока не хватает — "
        "нужен независимый источник."
    )


def _routing(requirement: Requirement) -> str:
    """Ровно два маршрута и никакого третьего (FR4.1).

    Требование, у которого есть компетенция эталона, закрывается тем же
    вопросом Contextual Probe, что и обычное белое пятно. Требование, которого
    в эталонах нет, вопросом закрыть нечем: генерировать вопрос под вакансию -
    это Vacancy-Specific Probe, а он отложен ([V2]).
    """
    return ANSWER_EXISTING_PROBE if requirement.competency_id else ADD_EVIDENCE


def compute(vacancy: Vacancy, state: CompetencyState, cluster_scores: dict[str, int]) -> MatchResult:
    """Проекция PROF.индекса на требования вакансии (FR2.1).

    Веса берутся у вакансии, а не у эталона: одна и та же компетенция может
    быть обязательной здесь и желательной там - в этом и смысл расхождения
    между профилем роли и конкретным объявлением (FR2.2, механизм 2).
    """
    total_weight = 0.0
    earned = 0.0
    covered: list[RequirementView] = []
    uncovered: list[RequirementView] = []

    for requirement in vacancy.requirements:
        status = _status_of(requirement, state)
        weight = CRITICALITY_WEIGHT[requirement.criticality]
        total_weight += weight
        earned += weight * STATUS_SCORE[status]

        if status in CONFIRMED_STATUSES:
            covered.append(
                RequirementView(
                    requirement_id=requirement.id,
                    label_ru=requirement.label_ru,
                    criticality=requirement.criticality,
                    status=status,
                    explanation_ru=_covered_reason(requirement, status),
                    competency_id=requirement.competency_id,
                )
            )
        else:
            uncovered.append(
                RequirementView(
                    requirement_id=requirement.id,
                    label_ru=requirement.label_ru,
                    criticality=requirement.criticality,
                    status=status,
                    explanation_ru=_uncovered_reason(requirement, status),
                    recommended_action=_routing(requirement),
                    competency_id=requirement.competency_id,
                )
            )

    # Сначала обязательное, потом желательное - то же правило приоритета, что
    # у белых пятен модуля 3 и следующих действий модуля 6 (FR4.2).
    uncovered.sort(key=lambda item: (-CRITICALITY_WEIGHT[item.criticality], item.label_ru))
    covered.sort(key=lambda item: (-CRITICALITY_WEIGHT[item.criticality], item.label_ru))

    return MatchResult(
        vacancy_id=vacancy.id,
        overall_match_score=round(100 * earned / total_weight) if total_weight else 0,
        covered=covered,
        uncovered=uncovered,
        # Кластер без эталона не превращается в ноль и не исчезает: про него
        # честно говорится, что платформа его не оценивала (FR2.4).
        unevaluated_clusters=[
            cluster.cluster_label_ru
            for cluster in vacancy.functional_clusters
            if cluster.reference_profile_id is None
        ],
        cluster_scores=[
            (cluster.cluster_label_ru, cluster_scores[cluster.reference_profile_id])
            for cluster in vacancy.functional_clusters
            if cluster.reference_profile_id in cluster_scores
        ],
    )


def role_breadth_note(vacancy: Vacancy) -> str:
    """Структурное описание, а не оценка качества вакансии (§3 FRD)."""
    if vacancy.role_breadth == "low" or len(vacancy.functional_clusters) < 2:
        return ""
    names = ", ".join(cluster.cluster_label_ru for cluster in vacancy.functional_clusters)
    return f"Эта вакансия объединяет {len(vacancy.functional_clusters)} функциональных кластера: {names}."
