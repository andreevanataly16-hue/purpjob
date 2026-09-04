"""Право отказаться — один механизм на все модули.

Модуль 2 отказывается раскрывать источник или факт, модуль 4 — отвечать на
конкретный вопрос под NDA. Правила при этом одни и те же и живут только здесь
(FR5.5 модуля 4: второй реализации быть не должно):

* причина никогда не обязательна;
* отказ ничего и нигде не отнимает — он не понижает статус и не штрафует;
* отказ обратим: кандидат может вернуться и раскрыть.

Различается только `target_type`: evidence, statement, question или ndacase.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DeclineRecord, User

TARGET_EVIDENCE = "evidence"
TARGET_STATEMENT = "statement"
TARGET_QUESTION = "question"
# Кандидат отказался от всех способов подтверждения под NDA (модуль 5, FR4.5).
TARGET_NDACASE = "ndacase"

TARGET_TYPES = (TARGET_EVIDENCE, TARGET_STATEMENT, TARGET_QUESTION, TARGET_NDACASE)


def record_decline(
    db: Session, user: User, *, target_type: str, target_id: int, reason: str | None = None
) -> DeclineRecord:
    """Фиксирует отказ. Ничего не пересчитывает и не понижает - по замыслу."""
    if target_type not in TARGET_TYPES:
        raise ValueError(f"Неизвестный тип объекта отказа: {target_type}")

    record = DeclineRecord(
        user_id=user.id, target_type=target_type, target_id=target_id, reason=reason
    )
    db.add(record)
    return record


def revoke_declines(db: Session, user: User, *, target_type: str, target_id: int) -> int:
    """Снимает отказ. Возвращает число снятых записей."""
    records = list(
        db.scalars(
            select(DeclineRecord).where(
                DeclineRecord.user_id == user.id,
                DeclineRecord.target_type == target_type,
                DeclineRecord.target_id == target_id,
            )
        )
    )
    for record in records:
        db.delete(record)
    return len(records)


def is_declined(db: Session, user: User, *, target_type: str, target_id: int) -> bool:
    return (
        db.scalar(
            select(DeclineRecord.id).where(
                DeclineRecord.user_id == user.id,
                DeclineRecord.target_type == target_type,
                DeclineRecord.target_id == target_id,
            )
        )
        is not None
    )
