"""Модуль 3: PROF.индекс.

Индекс - проекция подтверждённых компетенций кандидата (модуль 2) на эталонный
профиль роли. Свои данные модуля - только целевые уровни и режим видимости;
сам индекс не хранится, а считается на каждый запрос (§8 FRD).

Модуль 2 отсюда только читается. Всё, что меняет Statement или Evidence,
кандидат делает через API модуля 2 - здесь таких операций нет намеренно (§4).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.enrichment import DECLINED, TYPE_FILE, TYPE_LINK, EvidenceFacts, compute_status
from app.models import ProfRole, Statement, User, VisibilityState
from app.prof import StatementView, compute_snapshot
from app.reference import LEVELS, SEGMENT, get_profile
from app.routers.auth import current_user
from app.routers.profile import public_id
from app.schemas_prof import LevelIn, ProfOut, VisibilityIn

router = APIRouter(prefix="/api/prof", tags=["prof"])

# §4.3 FRD: кандидат может вести до трёх ролей одновременно. В библиотеке
# первого сегмента уровня всего два, так что предел пока недостижим.
MAX_ROLES = 3

VISIBILITY_MODES = ("hidden", "visible")


def _statement_views(db: Session, user: User) -> list[StatementView]:
    """Читает компетенции модуля 2 и считает их статусы его же правилом.

    Своей логики статусов у модуля 3 нет и быть не должно: FR2.4 требует
    переиспользовать расчёт §3.4, а не заводить рядом более мягкий порог.
    """
    statements = db.scalars(
        select(Statement).where(Statement.user_id == user.id).order_by(Statement.id)
    )

    views: list[StatementView] = []
    for item in statements:
        active = [e for e in item.evidence if e.status != DECLINED]
        view = compute_status(
            [
                EvidenceFacts(type=e.type, source_category=e.source_category, status=e.status)
                for e in item.evidence
            ]
        )
        views.append(
            StatementView(
                id=public_id("stmt", item.id),
                skill_name=item.skill_name,
                skill_name_ru=item.skill_name_ru,
                status=view.status,
                reason=view.reason,
                artifact_count=sum(1 for e in active if e.type in (TYPE_LINK, TYPE_FILE)),
                longest_text=max((len(e.raw_text or "") for e in active), default=0),
            )
        )
    return views


def _visibility(db: Session, user: User) -> VisibilityState:
    state = db.get(VisibilityState, user.id)
    if state is None:
        # Профиль по умолчанию скрыт: Self-Audit не должен требовать публикации.
        state = VisibilityState(user_id=user.id, mode="hidden")
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def _payload(db: Session, user: User) -> ProfOut:
    roles = list(
        db.scalars(select(ProfRole).where(ProfRole.user_id == user.id).order_by(ProfRole.id))
    )
    views = _statement_views(db, user)
    state = _visibility(db, user)

    return ProfOut.model_validate(
        {
            "segment": SEGMENT,
            "available_levels": list(LEVELS),
            "max_roles": MAX_ROLES,
            "snapshots": [compute_snapshot(get_profile(role.level), views) for role in roles],
            "visibility": {"mode": state.mode, "changed_at": state.changed_at},
        }
    )


@router.get("", response_model=ProfOut)
def read_prof(user: User = Depends(current_user), db: Session = Depends(get_db)) -> ProfOut:
    return _payload(db, user)


@router.post("/roles", response_model=ProfOut, status_code=status.HTTP_201_CREATED)
def add_role(
    data: LevelIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ProfOut:
    """FR1.1: чужой уровень не подгоняется молча под ближайший, а отклоняется."""
    if data.level not in LEVELS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"В библиотеке эталонов пока только {' и '.join(LEVELS)} для сегмента {SEGMENT}. "
            "Другие уровни появятся, когда будут откалиброваны эталонные профили.",
        )

    existing = list(db.scalars(select(ProfRole).where(ProfRole.user_id == user.id)))
    if any(role.level == data.level for role in existing):
        return _payload(db, user)

    if len(existing) >= MAX_ROLES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Одновременно можно вести не больше {MAX_ROLES} ролей.",
        )

    db.add(ProfRole(user_id=user.id, level=data.level))
    db.commit()
    return _payload(db, user)


@router.delete("/roles/{level}", response_model=ProfOut)
def remove_role(
    level: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ProfOut:
    role = db.scalar(
        select(ProfRole).where(ProfRole.user_id == user.id, ProfRole.level == level)
    )
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Такая роль не отслеживается.")

    db.delete(role)
    db.commit()
    return _payload(db, user)


@router.put("/visibility", response_model=ProfOut)
def set_visibility(
    data: VisibilityIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ProfOut:
    """FR4.4: публикует профиль только сам кандидат - никаких автопереключений
    по достижении какого-нибудь порога индекса."""
    if data.mode not in VISIBILITY_MODES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "В этой версии есть только «Инкогнито» и «Полная видимость».",
        )

    state = _visibility(db, user)
    state.mode = data.mode
    db.commit()
    return _payload(db, user)
