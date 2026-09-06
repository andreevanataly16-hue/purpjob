"""Модуль 7: сторона модератора.

Что здесь происходит по сути: человек смотрит на один конкретный фактический
вывод - не на профиль целиком - и решает, оставить его или исправить. Ровно на
это рассчитана вся конструкция (Гл. 13): проверять одно утверждение быстро,
а не расследовать кандидата заново.

Три правила, которые важнее удобства:

1. **Обоснование обязательно у всех трёх действий**, а не только у правки.
   Человек, меняющий вывод без объяснения, - та же проблема неоспоримого судьи,
   ради которой существует модуль, только судья сменился (FR4.3).
2. **Правка всегда адресная.** Одно поле одного объекта. Общего «поправить
   профиль» здесь нет (FR4.4).
3. **Изменить балл в обход журнала невозможно.** Не «не принято», а физически:
   модули 3 и 6 ничего не хранят, их результат пересчитывается, и единственное,
   что на него накладывается, - запись `ModeratorOverride` с обязательной
   причиной (FR-Gov.2, см. `app/overrides.py`).

БЕЗ ДОСТУПА И БЕЗ РОЛЕЙ. В этой фазе роль модератора - просто режим экрана
(§7 FRD): любой вошедший может открыть очередь и увидеть споры всех кандидатов.
Для локального прототипа это осознанно, для выката наружу - нет. До появления
настоящего RBAC (кто вправе быть модератором, и как это проверяется) поднимать
это в многопользовательскую среду нельзя.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import overrides
from app.db import get_db
from app.enrichment import LIMITED, MEDIUM, NOT_STARTED, STRONG
from app.models import (
    ContradictionCase,
    DisputeCase,
    DisputeHistoryEntry,
    ModeratorOverride,
    User,
)
from app.access import require_moderator
from app.routers.auth import current_user
from app.routers.profile import parse_id, public_id
from app.routers.xai import (
    IN_REVIEW,
    NEEDS_MORE_INFO,
    OPEN_STATUSES,
    QUEUED,
    RESOLVED_OVERRIDDEN,
    RESOLVED_UPHELD,
    append_history,
    resolve_refs,
    serialize_case,
    set_status,
)
from app.schemas_xai import InfoRequestIn, ModerationActionIn, OverrideIn, QueueOut

# Страж навешан на роутер целиком, а не на отдельные обработчики: забыть
# добавить проверку на новый обработчик проще, чем забыть завести роутер.
router = APIRouter(
    prefix="/api/moderation",
    tags=["moderation"],
    dependencies=[Depends(require_moderator)],
)

NOT_PRODUCTION_SAFE_RU = (
    "Режим модератора без доступа и без ролей: сейчас его может открыть любой вошедший, "
    "и в очереди видны споры всех кандидатов. Так можно только локально — до настоящего "
    "разграничения прав это наружу не выкатывается."
)

# Допустимые новые значения по видам правок. Список закрытый: «поправить на что
# угодно» - это способ обойти проверку, а не гибкость.
PROF_STATUSES = (NOT_STARTED, LIMITED, MEDIUM, STRONG)
CONTRADICTION_RESOLUTIONS = ("delete_artifact", "explain", "correct_claim")


def _case(db: Session, case_id: str) -> DisputeCase:
    case = db.get(DisputeCase, parse_id("dc", case_id))
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Спор не найден.")
    return case


def _owner(db: Session, case: DisputeCase) -> User:
    owner = db.get(User, case.user_id)
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Кандидат не найден.")
    return owner


def _require_open(case: DisputeCase) -> None:
    if case.status not in OPEN_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "Этот спор уже закрыт.")


# --- измеримость нагрузки (H1) -------------------------------------------


def _minutes_to_resolution(db: Session, case: DisputeCase) -> float | None:
    """Сколько прошло от открытия спора до его закрытия.

    Считается по журналу, а не отдельным полем: журнал и так неизменяем и
    датирован, а лишнее поле пришлось бы поддерживать в согласии с ним.
    """
    entries = list(
        db.scalars(
            select(DisputeHistoryEntry)
            .where(DisputeHistoryEntry.dispute_case_id == case.id)
            .order_by(DisputeHistoryEntry.id)
        )
    )
    if not entries:
        return None

    closing = [
        entry
        for entry in entries
        if entry.event_type == "status_changed"
        and entry.after_value in (RESOLVED_UPHELD, RESOLVED_OVERRIDDEN)
    ]
    if not closing:
        return None

    delta = closing[-1].timestamp - entries[0].timestamp
    return round(delta.total_seconds() / 60, 1)


def _stats(db: Session, all_cases: list[DisputeCase]) -> dict:
    """Данные для двух гипотез H1, а не журнал ради журнала.

    Первая: сколько времени уходит на разбор - тянет ли команда из двух человек
    ручную модерацию вообще. Вторая: если споры кучкуются вокруг одного вида
    выводов, значит, калибровки просит именно он, а не модерация.
    """
    durations = [
        value
        for value in (_minutes_to_resolution(db, case) for case in all_cases)
        if value is not None
    ]
    by_subject: dict[str, int] = {}
    for case in all_cases:
        by_subject[case.subject_type] = by_subject.get(case.subject_type, 0) + 1

    return {
        "resolved_count": len(durations),
        "median_minutes_to_resolve": (
            round(sorted(durations)[len(durations) // 2], 1) if durations else None
        ),
        "disputes_by_subject_type": by_subject,
    }


# --- очередь --------------------------------------------------------------


def _override_targets(db: Session, owner: User) -> dict[str, list[str]]:
    """Что вообще можно поправить у этого кандидата.

    Список собирается из его настоящих данных: модератор выбирает адрес, а не
    вписывает его руками, иначе правка легко уедет в несуществующее поле.
    """
    from app.routers.prof import _payload
    from app.routers.trust import _state

    competencies: list[str] = []
    for snapshot in _payload(db, owner).snapshots:
        for component in snapshot.components:
            if component.competency_id not in competencies:
                competencies.append(component.competency_id)

    components = [item.component_id for item in _state(db, owner).components]

    open_contradictions = [
        public_id("cc", case.id)
        for case in db.scalars(
            select(ContradictionCase).where(
                ContradictionCase.user_id == owner.id, ContradictionCase.status == "open"
            )
        )
    ]

    return {
        overrides.TARGET_PROF_STATUS: competencies,
        overrides.TARGET_TRUST_COMPONENT: components,
        overrides.TARGET_CONTRADICTION: open_contradictions,
    }


def _queue_case(db: Session, case: DisputeCase) -> dict:
    owner = _owner(db, case)
    payload = serialize_case(db, case)
    payload["candidate_email"] = owner.email
    # FR4.2: ровно то, что видел кандидат, - из копии, снятой при открытии
    # спора, а не пересчитанное заново.
    payload["resolved_evidence"] = resolve_refs(
        db, owner, json.loads(case.explanation_evidence_refs or "[]")
    )
    return payload


def _queue(db: Session, only_open: bool = True) -> QueueOut:
    all_cases = list(db.scalars(select(DisputeCase).order_by(DisputeCase.id)))
    shown = [case for case in all_cases if case.status in OPEN_STATUSES] if only_open else all_cases

    targets: dict[str, list[str]] = {}
    for case in shown:
        for key, values in _override_targets(db, _owner(db, case)).items():
            targets.setdefault(key, [])
            for value in values:
                if value not in targets[key]:
                    targets[key].append(value)

    return QueueOut.model_validate(
        {
            "not_production_safe_ru": NOT_PRODUCTION_SAFE_RU,
            "open_count": len([case for case in all_cases if case.status in OPEN_STATUSES]),
            "cases": [_queue_case(db, case) for case in shown],
            "override_targets": targets,
            "stats": _stats(db, all_cases),
        }
    )


@router.get("/queue", response_model=QueueOut)
def read_queue(
    include_resolved: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> QueueOut:
    """FR4.1: все открытые споры всех трёх происхождений в одном списке."""
    return _queue(db, only_open=not include_resolved)


@router.post("/cases/{case_id}/take", response_model=QueueOut)
def take_case(
    case_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> QueueOut:
    """Взять спор в работу. Отметка нужна, чтобы двое не разбирали одно и то же."""
    case = _case(db, case_id)
    _require_open(case)

    case.assigned_moderator = user.email
    set_status(db, case, IN_REVIEW, "moderator")
    db.commit()
    return _queue(db)


@router.post("/cases/{case_id}/uphold", response_model=QueueOut)
def uphold(
    case_id: str,
    data: ModerationActionIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> QueueOut:
    """FR4.3a: вывод остаётся - но причина обязательна и она видна кандидату.

    «Проверили, всё верно» без объяснения кандидат прочитает как отписку, и
    будет прав: это ровно тот чёрный ящик, который модуль закрывает.
    """
    case = _case(db, case_id)
    _require_open(case)

    case.assigned_moderator = case.assigned_moderator or user.email
    append_history(db, case, "moderator_note_added", "moderator", note_ru=data.rationale_ru.strip())
    set_status(db, case, RESOLVED_UPHELD, "moderator")
    db.commit()
    return _queue(db)


@router.post("/cases/{case_id}/request-info", response_model=QueueOut)
def request_info(
    case_id: str,
    data: InfoRequestIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> QueueOut:
    """FR4.3b: конкретный вопрос, а не «уточните, пожалуйста»."""
    case = _case(db, case_id)
    _require_open(case)

    case.assigned_moderator = case.assigned_moderator or user.email
    case.info_request_ru = data.question_ru.strip()
    append_history(db, case, "info_requested", "moderator", note_ru=case.info_request_ru)
    set_status(db, case, NEEDS_MORE_INFO, "moderator")
    db.commit()
    return _queue(db)


def _current_value(db: Session, owner: User, target_type: str, target_id: str) -> str:
    """Что стоит в поле сейчас - чтобы записать «было» точно, а не примерно (FR5.3)."""
    from app.routers.prof import _payload
    from app.routers.trust import _state

    if target_type == overrides.TARGET_PROF_STATUS:
        for snapshot in _payload(db, owner).snapshots:
            for component in snapshot.components:
                if component.competency_id == target_id:
                    return component.status
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Такой компетенции у кандидата нет.")

    if target_type == overrides.TARGET_TRUST_COMPONENT:
        for component in _state(db, owner).components:
            if component.component_id == target_id:
                return str(component.score)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Такого компонента Trust нет.")

    case = db.get(ContradictionCase, parse_id("cc", target_id))
    if case is None or case.user_id != owner.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Такой нестыковки у кандидата нет.")
    return case.resolution_path or case.status


def _check_new_value(target_type: str, new_value: str) -> None:
    if target_type == overrides.TARGET_PROF_STATUS and new_value not in PROF_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Статус компетенции бывает только: {', '.join(PROF_STATUSES)}.",
        )
    if target_type == overrides.TARGET_TRUST_COMPONENT:
        if not new_value.isdigit() or not 0 <= int(new_value) <= 100:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Балл компонента — число от 0 до 100.")
    if target_type == overrides.TARGET_CONTRADICTION and new_value not in CONTRADICTION_RESOLUTIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Разбор нестыковки бывает только: {', '.join(CONTRADICTION_RESOLUTIONS)}.",
        )


@router.post("/cases/{case_id}/override", response_model=QueueOut)
def apply_override(
    case_id: str,
    data: OverrideIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> QueueOut:
    """FR4.3c: исправить вывод - одно поле, с причиной, под запись.

    Порядок здесь имеет значение (FR-Gov.3): сначала запись журнала, потом
    правка. Задним числом журнал не дописывается.
    """
    case = _case(db, case_id)
    _require_open(case)

    if data.target_type not in overrides.TARGET_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Такое поле не правится через модерацию.")

    owner = _owner(db, case)
    _check_new_value(data.target_type, data.new_value)
    previous = _current_value(db, owner, data.target_type, data.target_id)

    if previous == data.new_value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Значение и так такое — правка ничего не даст.")

    case.assigned_moderator = case.assigned_moderator or user.email

    # Журнал первым: запись о правке рождается вместе с самой правкой и хранит
    # её идентификатор, чтобы эти двое не могли разойтись (§4.4).
    entry = append_history(
        db,
        case,
        "override_applied",
        "moderator",
        before_value=previous,
        after_value=data.new_value,
        note_ru=data.rationale_ru.strip(),
    )

    db.add(
        ModeratorOverride(
            dispute_case_id=case.id,
            user_id=owner.id,
            target_type=data.target_type,
            target_id=data.target_id,
            previous_value=previous,
            new_value=data.new_value,
            rationale_ru=data.rationale_ru.strip(),
            history_entry_id=entry.id,
        )
    )

    # Разбор нестыковки - единственная правка, которая ложится в свои же данные:
    # у модуля 6 это хранимое поле, а не пересчитываемое значение.
    if data.target_type == overrides.TARGET_CONTRADICTION:
        contradiction = db.get(ContradictionCase, parse_id("cc", data.target_id))
        contradiction.resolution_path = data.new_value
        contradiction.status = "resolved"
        contradiction.visibility_suspended = False

    set_status(db, case, RESOLVED_OVERRIDDEN, "moderator")
    db.commit()
    return _queue(db)
