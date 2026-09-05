"""Модуль 10: лента вакансий и Match Score.

Читает модуль 3 и не пишет в него ничего. Это не аккуратность, а требование:
низкое совпадение с одной вакансией не должно уметь испортить сам профиль.
Проверяется тестом, который читает исходники этого модуля.

Отклика здесь нет. Не «пока не сделали» - его нет во всём продукте, и этот
модуль не то место, где он появится побочным эффектом показа ленты.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import vacancies as library
from app.db import get_db
from app.models import ProfRole, User
from app.reference import get_profile
from app.routers.auth import current_user
from app.schemas_vacancies import VacanciesOut, VacancyDetailOut
from app.vacancies import CompetencyState

router = APIRouter(prefix="/api/vacancies", tags=["vacancies"])

NOTE_RU = (
    "Лента маленькая и подобранная вручную. Это не витрина, куда можно разослать сто откликов: "
    "смысл в том, чтобы связать уже накопленный профиль с одной конкретной возможностью."
)

NO_ROLE_RU = "Выберите целевую роль — по ней и подбирается лента."


def _state(db: Session, user: User) -> CompetencyState:
    """Что кандидат подтвердил. Берётся у модуля 3 как есть."""
    from app.routers.prof import _payload, _statement_views

    by_competency: dict[str, str] = {}
    rank = {"not_started": 0, "limited": 1, "medium": 2, "strong": 3}

    for snapshot in _payload(db, user).snapshots:
        for component in snapshot.components:
            current = by_competency.get(component.competency_id, "not_started")
            if rank[component.status] > rank[current]:
                by_competency[component.competency_id] = component.status

    by_skill = {
        view.skill_name.lower(): view.status for view in _statement_views(db, user)
    }
    return CompetencyState(by_competency=by_competency, by_skill=by_skill)


def _cluster_scores(db: Session, user: User) -> dict[str, int]:
    """PROF.индекс кандидата против каждого эталона из библиотеки.

    Для вакансии с несколькими кластерами это и есть подсчёт «по каждому
    кластеру отдельно», а не по одному усреднённому профилю (FR2.4).
    """
    from app.prof import compute_snapshot
    from app.reference import LEVELS
    from app.routers.prof import _statement_views

    views = _statement_views(db, user)
    return {
        get_profile(level).id: compute_snapshot(get_profile(level), views)["overall_score"]
        for level in LEVELS
    }


def _levels(db: Session, user: User) -> list[str]:
    return [
        role.level
        for role in db.scalars(
            select(ProfRole).where(ProfRole.user_id == user.id).order_by(ProfRole.id)
        )
    ]


def _card(vacancy: library.Vacancy, result: library.MatchResult) -> dict:
    return {
        "id": vacancy.id,
        "title_ru": vacancy.title_ru,
        "company_label": vacancy.company_label,
        "stated_level": vacancy.stated_level,
        "role_breadth": vacancy.role_breadth,
        "role_breadth_ru": library.ROLE_BREADTH_RU[vacancy.role_breadth],
        "industry_context": vacancy.industry_context,
        "ai_leverage_flag": vacancy.ai_leverage_flag,
        # Одно объявление из нескольких каналов - одна карточка со всеми
        # источниками, а не несколько одинаковых (FR1.4).
        "source_channels": list(vacancy.source_channels),
        "created_at": vacancy.created_at,
        "overall_match_score": result.overall_match_score,
        "covered_count": len(result.covered),
        "uncovered_count": len(result.uncovered),
        "mandatory_gaps": len(
            [item for item in result.uncovered if item.criticality == library.MANDATORY]
        ),
    }


def _requirement(item: library.RequirementView) -> dict:
    return {
        "requirement_id": item.requirement_id,
        "label_ru": item.label_ru,
        "criticality": item.criticality,
        "criticality_ru": library.CRITICALITY_RU[item.criticality],
        "status": item.status,
        "explanation_ru": item.explanation_ru,
        "recommended_action": item.recommended_action,
        "competency_id": item.competency_id,
    }


def match_for(db: Session, user: User, vacancy: library.Vacancy) -> library.MatchResult:
    """Единственная точка расчёта совпадения на весь продукт.

    Модули 11 и 12 зовут её же: два параллельных расчёта «на сколько подходит»
    разошлись бы в первый же месяц.
    """
    return library.compute(vacancy, _state(db, user), _cluster_scores(db, user))


def feed(db: Session, user: User) -> list[library.Vacancy]:
    levels = _levels(db, user)
    seen: set[str] = set()
    result: list[library.Vacancy] = []
    for level in levels:
        for vacancy in library.feed_for(level):
            if vacancy.id in seen:
                continue
            seen.add(vacancy.id)
            result.append(vacancy)
    return sorted(result, key=lambda item: item.created_at, reverse=True)


@router.get("", response_model=VacanciesOut)
def read_feed(user: User = Depends(current_user), db: Session = Depends(get_db)) -> VacanciesOut:
    """FR1.1-FR1.3: лента, которую кандидат открывает сам.

    Никаких уведомлений отсюда не уходит: это pull, а push - модуль 11.
    """
    levels = _levels(db, user)
    if not levels:
        return VacanciesOut.model_validate(
            {"note_ru": NO_ROLE_RU, "levels": [], "vacancies": [], "computed_at": datetime.now(timezone.utc)}
        )

    state = _state(db, user)
    clusters = _cluster_scores(db, user)
    items = feed(db, user)

    cards = [_card(item, library.compute(item, state, clusters)) for item in items]
    cards.sort(key=lambda card: -card["overall_match_score"])

    return VacanciesOut.model_validate(
        {
            "note_ru": NOTE_RU,
            "levels": levels,
            "vacancies": cards,
            "computed_at": datetime.now(timezone.utc),
        }
    )


@router.get("/{vacancy_id}", response_model=VacancyDetailOut)
def read_vacancy(
    vacancy_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> VacancyDetailOut:
    """FR3.1: три категории требований, и у каждого пункта - причина."""
    vacancy = library.BY_ID.get(vacancy_id)
    if vacancy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Такой вакансии в ленте нет.")

    result = match_for(db, user, vacancy)
    payload = _card(vacancy, result)
    payload.update(
        {
            "note_ru": library.role_breadth_note(vacancy),
            "covered": [_requirement(item) for item in result.covered],
            "uncovered": [_requirement(item) for item in result.uncovered],
            "unevaluated_clusters": result.unevaluated_clusters,
            "unevaluated_note_ru": (
                "Эта часть требований пока не оценена платформой: эталона роли для неё в "
                "библиотеке нет. Это не значит, что у вас её нет — значит, что мы её не мерили."
            ),
            "cluster_scores": [
                {"cluster_label_ru": label, "score": score} for label, score in result.cluster_scores
            ],
        }
    )
    return VacancyDetailOut.model_validate(payload)
