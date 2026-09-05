"""Модуль 13, сторона кандидата: кто интересуется профилем.

Это прозрачность, а не право вето. Кандидат видит, до какого этапа дошёл
каждый рекрутер, но не отменяет уже наступивший этап: сама поэтапность -
защита от предвзятости, и возможность её произвольно переключать по одному
рекрутеру эту защиту бы и разобрала.

Два решения кандидата здесь независимы и связывать их нельзя:

* «сразу показывать имя и фото» - осознанный выход из поэтапности;
* согласие на раскрытие доказательств - про глубину, а не про личность.

Включённое первое не означает второго, и наоборот.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import reveal
from app.db import get_db
from app.models import RevealState, User, VisibilityState
from app.routers.auth import current_user
from app.schemas_recruiter import RevealOut
from app.schemas_reveal import RevealSettingsIn

router = APIRouter(prefix="/api/reveal", tags=["reveal"])

NOTE_RU = (
    "Рекрутеры сначала видят только профессиональные данные: имя и фотография показываются, "
    "только если кто-то отметил интерес к профилю. Это защита от предвзятости, а не скрытность."
)


def _visibility(db: Session, user: User) -> VisibilityState:
    state = db.get(VisibilityState, user.id)
    if state is None:
        state = VisibilityState(user_id=user.id, mode="hidden")
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def _payload(db: Session, user: User) -> RevealOut:
    from app.candidates import LIVE_PREFIX

    state = _visibility(db, user)
    rows = db.scalars(
        select(RevealState)
        .where(RevealState.candidate_id == f"{LIVE_PREFIX}{user.id}")
        .order_by(RevealState.id)
    )

    return RevealOut.model_validate(
        {
            "note_ru": NOTE_RU,
            "opt_out_label_ru": reveal.OPT_OUT_LABEL_RU,
            "allow_immediate_identity_reveal": state.allow_immediate_identity_reveal,
            "consent_for_recruiter_view": state.consent_for_recruiter_view,
            "interests": [
                {
                    # Кто именно смотрел, кандидату не показывается: настоящих
                    # аккаунтов рекрутеров нет, а выдумывать их - врать.
                    "recruiter_label": f"Рекрутер #{row.recruiter_user_id}",
                    "current_stage": row.current_stage,
                    "stage_ru": reveal.STAGE_RU[row.current_stage],
                    "contact_requested": row.contact_requested_at is not None,
                    "contact_opt_in": row.candidate_contact_opt_in,
                    "created_at": row.created_at,
                }
                for row in rows
            ],
        }
    )


@router.get("", response_model=RevealOut)
def read_reveal(user: User = Depends(current_user), db: Session = Depends(get_db)) -> RevealOut:
    """FR3.1: кандидат видит, кто на каком этапе."""
    return _payload(db, user)


@router.put("/settings", response_model=RevealOut)
def update_settings(
    data: RevealSettingsIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> RevealOut:
    """FR3.2: два независимых решения, оба выключены по умолчанию."""
    state = _visibility(db, user)
    if data.allow_immediate_identity_reveal is not None:
        state.allow_immediate_identity_reveal = data.allow_immediate_identity_reveal
    if data.consent_for_recruiter_view is not None:
        state.consent_for_recruiter_view = data.consent_for_recruiter_view
    db.commit()
    return _payload(db, user)


@router.post("/interests/{recruiter_user_id}/share-contacts", response_model=RevealOut)
def share_contacts(
    recruiter_user_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> RevealOut:
    """FR3.3: встречное согласие на контакты — отдельное решение каждый раз.

    Разрешение сразу показывать имя и фото его не заменяет: это две разные
    вещи, и одна не подразумевает другую.
    """
    from app.candidates import LIVE_PREFIX

    row = db.scalar(
        select(RevealState).where(
            RevealState.recruiter_user_id == recruiter_user_id,
            RevealState.candidate_id == f"{LIVE_PREFIX}{user.id}",
        )
    )
    if row is not None:
        row.candidate_contact_opt_in = True
        if row.contact_requested_at is not None and row.current_stage == reveal.STAGE_2:
            row.current_stage = reveal.STAGE_3
            row.stage3_advanced_at = reveal_now()
            row.advance_trigger = reveal.MUTUAL_INTEREST_CONFIRMED
        db.commit()

    return _payload(db, user)


def reveal_now():
    from app import growth

    return growth.utcnow()
