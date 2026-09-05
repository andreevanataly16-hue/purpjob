"""Модуль 8: накопительный профиль и история роста.

Этот модуль ничего не считает сам. Он смотрит на то, что уже посчитали модули
2, 3, 6 и 7, и записывает изменения - поэтому логика статусов и баллов живёт
там, где ей положено, а не дублируется здесь второй раз.

Три гарантии, ради которых модуль существует:

1. **Ничего не пропадает.** Закрытие эпизода поиска работы не делает с
   профилем ничего. Проверяется тестом, а не обещанием.
2. **Подтверждённое переиспользуется.** Статус компетенции принадлежит
   кандидату, а не роли: вторая роль читает те же самые записи и не порождает
   ни одного нового вопроса по уже подтверждённому.
3. **Рост видно.** Отдельный журнал - что и когда стало сильнее.

Про наблюдение вместо подписки. Красивее была бы подписка на события других
модулей, но статусы у нас нигде не хранятся: они пересчитываются на каждый
запрос. Поэтому наблюдатель сравнивает текущий вывод модулей с тем, что уже
записано в журнале, и дописывает разницу. Он по-прежнему ничего не вычисляет
сам - только смотрит на чужой результат.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import growth
from app.db import get_db
from app.enrichment import DECLINED
from app.models import (
    CompetencyFreshness,
    DisputeCase,
    Evidence,
    ModeratorOverride,
    ProfileGrowthEvent,
    ProfRole,
    ReturnTrigger,
    Statement,
    User,
)
from app.routers.auth import current_user
from app.routers.profile import public_id
from app.schemas_growth import GrowthOut

router = APIRouter(prefix="/api/growth", tags=["growth"])

NOTE_RU = (
    "Подтверждённое остаётся вашим. Его не спрашивают заново — ни через месяц, ни при новой "
    "целевой роли, ни после того, как один поиск закончился."
)

# Сколько белое пятно должно провисеть, прежде чем о нём напоминать. Величина
# в FRD намеренно не зафиксирована - это калибруемая гипотеза, как и всё
# остальное в проекте.
WHITE_SPOT_STALE_DAYS = 1

_STATUS_RANK = {"not_started": 0, "limited": 1, "medium": 2, "strong": 3}


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# --- журнал ---------------------------------------------------------------


def _events(db: Session, user: User) -> list[ProfileGrowthEvent]:
    return list(
        db.scalars(
            select(ProfileGrowthEvent)
            .where(ProfileGrowthEvent.user_id == user.id)
            .order_by(ProfileGrowthEvent.occurred_at, ProfileGrowthEvent.id)
        )
    )


def _append(
    db: Session,
    user: User,
    event_type: str,
    subject_ref: str,
    subject_ru: str,
    occurred_at: datetime,
    from_value: str | None = None,
    to_value: str | None = None,
) -> None:
    db.add(
        ProfileGrowthEvent(
            user_id=user.id,
            event_type=event_type,
            subject_ref=subject_ref,
            from_value=from_value,
            to_value=to_value,
            description_ru=growth.describe(event_type, subject_ru, from_value, to_value),
            occurred_at=_aware(occurred_at),
        )
    )


def _seen(events: list[ProfileGrowthEvent], event_type: str) -> set[str]:
    return {item.subject_ref for item in events if item.event_type == event_type}


def _best_known(events: list[ProfileGrowthEvent], event_type: str, subject_ref: str) -> str | None:
    """Самое сильное значение, которое журнал уже помнит про этот объект.

    История роста показывает, что выросло. Если статус временно просел и
    вернулся обратно, нового роста не случилось - и записывать нечего.
    """
    values = [
        item.to_value
        for item in events
        if item.event_type == event_type and item.subject_ref == subject_ref and item.to_value
    ]
    return values[-1] if values else None


# --- наблюдение за другими модулями --------------------------------------


def _watch_evidence(db: Session, user: User, events: list[ProfileGrowthEvent]) -> None:
    known = _seen(events, growth.EVIDENCE_ADDED)
    for item in db.scalars(
        select(Evidence).where(Evidence.user_id == user.id).order_by(Evidence.id)
    ):
        ref = public_id("ev", item.id)
        if ref in known or item.status == DECLINED:
            continue
        title = item.file_name or item.url or "рассказ своими словами"
        _append(db, user, growth.EVIDENCE_ADDED, ref, title, item.created_at)


def _watch_roles(db: Session, user: User, events: list[ProfileGrowthEvent]) -> None:
    known = _seen(events, growth.ROLE_ADDED)
    for role in db.scalars(
        select(ProfRole).where(ProfRole.user_id == user.id).order_by(ProfRole.id)
    ):
        ref = f"role_{role.level}"
        if ref in known:
            continue
        _append(db, user, growth.ROLE_ADDED, ref, role.level, role.created_at)


def _watch_statuses(db: Session, user: User, events: list[ProfileGrowthEvent]) -> None:
    """Статусы компетенций берутся из модуля 3 как есть - своего расчёта нет."""
    from app.routers.prof import _statement_views

    for view in _statement_views(db, user):
        known = _best_known(events, growth.STATUS_UPGRADED, view.id) or "not_started"
        if _STATUS_RANK[view.status] <= _STATUS_RANK[known]:
            continue

        statement = db.get(Statement, int(view.id.split("_")[1]))
        _append(
            db,
            user,
            growth.STATUS_UPGRADED,
            view.id,
            view.skill_name_ru,
            statement.updated_at if statement else growth.utcnow(),
            from_value=known,
            to_value=view.status,
        )


def _watch_trust(db: Session, user: User, events: list[ProfileGrowthEvent]) -> None:
    from app.routers.trust import _state

    for component in _state(db, user).components:
        known = int(_best_known(events, growth.TRUST_INCREASED, component.component_id) or 0)
        if component.score <= known:
            continue
        _append(
            db,
            user,
            growth.TRUST_INCREASED,
            component.component_id,
            component.name_ru,
            growth.utcnow(),
            from_value=str(known),
            to_value=str(component.score),
        )


def _watch_disputes(db: Session, user: User, events: list[ProfileGrowthEvent]) -> None:
    """Спор, решённый в пользу кандидата, - тоже рост профиля (модуль 7)."""
    known = _seen(events, growth.DISPUTE_RESOLVED)
    overrides = db.scalars(
        select(ModeratorOverride)
        .where(ModeratorOverride.user_id == user.id)
        .order_by(ModeratorOverride.id)
    )
    for override in overrides:
        ref = public_id("mo", override.id)
        if ref in known:
            continue
        case = db.get(DisputeCase, override.dispute_case_id)
        if case is None or case.origin != "candidate_escalation":
            continue
        _append(
            db,
            user,
            growth.DISPUTE_RESOLVED,
            ref,
            override.target_id,
            override.applied_at,
            from_value=override.previous_value,
            to_value=override.new_value,
        )


def _watch_reuse(db: Session, user: User, events: list[ProfileGrowthEvent]) -> None:
    """FR2.4: перенос подтверждения в новую роль - видимое событие, а не деталь.

    Именно этот момент делает принцип «не спрашиваем дважды» осязаемым для
    кандидата, поэтому он записывается отдельно, а не растворяется в пересчёте.
    """
    from app.reference import get_profile
    from app.routers.prof import _statement_views

    known = _seen(events, growth.REUSED_ACROSS_ROLE)
    views = _statement_views(db, user)
    roles = list(
        db.scalars(select(ProfRole).where(ProfRole.user_id == user.id).order_by(ProfRole.id))
    )
    if len(roles) < 2:
        return

    statements = {
        public_id("stmt", item.id): item
        for item in db.scalars(select(Statement).where(Statement.user_id == user.id))
    }

    # Первая роль - не перенос, а начало. Переносом считается то, что новая
    # роль получила уже готовым.
    for role in roles[1:]:
        profile = get_profile(role.level)
        for competency in profile.competencies:
            matched = [
                view
                for view in views
                if view.skill_name in competency.taxonomy_keys
                and view.status in growth.CONFIRMED_STATUSES
            ]
            if not matched:
                continue

            earliest = min(
                (
                    _aware(statements[view.id].created_at)
                    for view in matched
                    if view.id in statements
                ),
                default=None,
            )
            # Строго позже - значит, компетенция появилась уже под новую роль.
            # Отметки времени в базе идут с точностью до секунды, поэтому
            # равенство считаем переносом, а не новой работой.
            if earliest is None or earliest > _aware(role.created_at):
                continue

            ref = f"{role.level}:{competency.competency_id}"
            if ref in known:
                continue
            _append(
                db,
                user,
                growth.REUSED_ACROSS_ROLE,
                ref,
                competency.name_ru,
                role.created_at,
                to_value=matched[0].status,
            )


# --- актуальность ---------------------------------------------------------


def confirmed_competencies(db: Session, user: User) -> dict[str, str]:
    """Компетенции эталона, подтверждённые кандидатом, с их названиями.

    Читается из модуля 3: подтверждение принадлежит кандидату, а не роли, и
    объединяется по всем ролям сразу (FR2.1).
    """
    from app.reference import get_profile
    from app.routers.prof import _statement_views

    views = _statement_views(db, user)
    roles = list(db.scalars(select(ProfRole).where(ProfRole.user_id == user.id)))

    found: dict[str, str] = {}
    for role in roles:
        for competency in get_profile(role.level).competencies:
            if competency.competency_id in found:
                continue
            if any(
                view.skill_name in competency.taxonomy_keys
                and view.status in growth.CONFIRMED_STATUSES
                for view in views
            ):
                found[competency.competency_id] = competency.name_ru
    return found


def _evidence_at_by_competency(db: Session, user: User) -> dict[str, datetime]:
    """Когда компетенцию подтверждали в последний раз - по её же материалам.

    Считать по любому свежему доказательству нельзя: тогда добавленная ссылка
    на статью про Kubernetes «освежала» бы и Python, и тестирование, и всё
    остальное разом. Актуальность компетенции обновляет только то, что
    подтверждает эту компетенцию.
    """
    from app.reference import get_profile
    from app.routers.prof import _statement_views

    views = {view.id: view for view in _statement_views(db, user)}
    roles = list(db.scalars(select(ProfRole).where(ProfRole.user_id == user.id)))

    latest_by_statement: dict[str, datetime] = {}
    for statement in db.scalars(select(Statement).where(Statement.user_id == user.id)):
        times = [
            _aware(item.created_at)
            for item in statement.evidence
            if item.status != DECLINED
        ]
        if times:
            latest_by_statement[public_id("stmt", statement.id)] = max(times)

    found: dict[str, datetime] = {}
    for role in roles:
        for competency in get_profile(role.level).competencies:
            times = [
                latest_by_statement[statement_id]
                for statement_id, view in views.items()
                if view.skill_name in competency.taxonomy_keys
                and view.status in growth.CONFIRMED_STATUSES
                and statement_id in latest_by_statement
            ]
            if times:
                found[competency.competency_id] = max(found.get(competency.competency_id, times[0]), *times)
    return found


def _watch_freshness(db: Session, user: User) -> None:
    """Заводит и продвигает отсчёт актуальности. Ничего не понижает сам.

    Множитель тут не хранится: он считается из даты по чистой функции. Хранить
    его отдельно означало бы, что где-то есть записанное понижение - а понижения
    как записанного факта в продукте быть не должно.
    """
    confirmed = confirmed_competencies(db, user)
    rows = {
        row.competency_id: row
        for row in db.scalars(
            select(CompetencyFreshness).where(CompetencyFreshness.user_id == user.id)
        )
    }
    evidence_at = _evidence_at_by_competency(db, user)

    for competency_id in confirmed:
        moment = evidence_at.get(competency_id, growth.utcnow())
        row = rows.get(competency_id)
        if row is None:
            db.add(
                CompetencyFreshness(
                    user_id=user.id,
                    competency_id=competency_id,
                    last_confirmed_at=moment,
                    decay_countdown_started_at=moment,
                )
            )
            continue

        # Дата подтверждения только двигается вперёд: новое доказательство по
        # этой компетенции обновляет актуальность, а ручное «Актуализировать»
        # её не теряет.
        if moment > _aware(row.last_confirmed_at):
            row.last_confirmed_at = moment
            row.decay_countdown_started_at = moment


def effective_confirmed_at(db: Session, user: User) -> dict[str, datetime]:
    """Когда компетенция подтверждена, с точки зрения актуальности.

    Считается, а не берётся из записи. Записанная дата двигалась бы наблюдателем
    следом за новыми доказательствами, и любой запрос, пришедший раньше
    наблюдателя, видел бы устаревшее значение - индекс и блок актуальности
    разъезжались бы на одном и том же экране. Здесь этой возможности нет: обе
    стороны считают одно и то же из одних данных.

    Ручное «Актуализировать» переживает пересчёт, потому что берётся максимум:
    новое доказательство и нажатие кнопки одинаково двигают дату вперёд.
    """
    stored = {
        row.competency_id: _aware(row.last_confirmed_at)
        for row in db.scalars(
            select(CompetencyFreshness).where(CompetencyFreshness.user_id == user.id)
        )
    }
    from_evidence = _evidence_at_by_competency(db, user)

    keys = set(stored) | set(from_evidence)
    return {
        key: max(
            [value for value in (stored.get(key), from_evidence.get(key)) if value is not None]
        )
        for key in keys
    }


def freshness_list(db: Session, user: User) -> list[dict]:
    confirmed = confirmed_competencies(db, user)
    effective = effective_confirmed_at(db, user)

    result = []
    for competency_id, moment in effective.items():
        if competency_id not in confirmed:
            continue
        item = growth.freshness_for(competency_id, moment)
        name_ru = confirmed[competency_id]
        result.append(
            {
                "competency_id": item.competency_id,
                "name_ru": name_ru,
                "status": item.status,
                "status_ru": growth.FRESHNESS_RU[item.status],
                "market_weight_multiplier": item.multiplier,
                "last_confirmed_at": item.last_confirmed_at,
                "days_since": item.days_since,
                "days_to_decay": item.days_to_decay,
                "hint_ru": growth.decay_text(name_ru, item),
            }
        )
    return sorted(result, key=lambda entry: (entry["market_weight_multiplier"], entry["name_ru"]))


def multipliers(db: Session, user: User) -> dict[str, float]:
    """Множители для сборки PROF.индекса - единственный их потребитель (§0)."""
    return {
        competency_id: growth.freshness_for(competency_id, moment).multiplier
        for competency_id, moment in effective_confirmed_at(db, user).items()
    }


# --- поводы вернуться -----------------------------------------------------


def _open_white_spots(db: Session, user: User) -> dict[str, str]:
    from app.reference import get_profile
    from app.routers.prof import _payload

    payload = _payload(db, user)
    found: dict[str, str] = {}
    for snapshot in payload.snapshots:
        names = {c.competency_id: c.name_ru for c in get_profile(snapshot.level).competencies}
        for competency_id in snapshot.white_spots:
            found.setdefault(competency_id, names.get(competency_id, competency_id))
    return found


def _watch_triggers(db: Session, user: User) -> None:
    """Два повода вернуться и ни одного лишнего (FR5.1).

    Закрытие повода отмечается сразу же: считается только то, что человек
    вернулся и что-то сделал, а не то, что ему показали напоминание.
    """
    triggers = list(
        db.scalars(select(ReturnTrigger).where(ReturnTrigger.user_id == user.id))
    )
    open_spots = _open_white_spots(db, user)
    fresh = {
        item["competency_id"]: item
        for item in freshness_list(db, user)
    }

    # Что уже закрылось - закрываем и в поводах.
    for trigger in triggers:
        if trigger.status in (growth.ACTED_UPON, growth.DISMISSED):
            continue
        done = (
            trigger.trigger_type == growth.WHITE_SPOT_REMINDER
            and trigger.related_ref not in open_spots
        ) or (
            trigger.trigger_type == growth.DECAY_WARNING
            and fresh.get(trigger.related_ref, {}).get("status") == growth.FRESH
        )
        if done:
            trigger.status = growth.ACTED_UPON
            trigger.acted_upon_at = growth.utcnow()

    active = {
        (trigger.trigger_type, trigger.related_ref)
        for trigger in triggers
        if trigger.status in (growth.PENDING, growth.SENT)
    }

    # Напоминание о белом пятне - только если оно провисело достаточно долго.
    roles = list(db.scalars(select(ProfRole).where(ProfRole.user_id == user.id)))
    oldest_role = min((_aware(role.created_at) for role in roles), default=None)
    if oldest_role and growth.utcnow() - oldest_role >= timedelta(days=WHITE_SPOT_STALE_DAYS):
        for competency_id in list(open_spots)[:1]:
            if (growth.WHITE_SPOT_REMINDER, competency_id) in active:
                continue
            db.add(
                ReturnTrigger(
                    user_id=user.id,
                    trigger_type=growth.WHITE_SPOT_REMINDER,
                    related_ref=competency_id,
                )
            )

    for competency_id, item in fresh.items():
        state = growth.freshness_for(competency_id, item["last_confirmed_at"])
        if not growth.needs_decay_warning(state):
            continue
        if (growth.DECAY_WARNING, competency_id) in active:
            continue
        db.add(
            ReturnTrigger(
                user_id=user.id,
                trigger_type=growth.DECAY_WARNING,
                related_ref=competency_id,
            )
        )


def _trigger_text(db: Session, user: User, trigger: ReturnTrigger) -> str:
    if trigger.trigger_type == growth.WHITE_SPOT_REMINDER:
        return growth.WHITE_SPOT_TEXT_RU
    names = confirmed_competencies(db, user)
    name_ru = names.get(trigger.related_ref, trigger.related_ref)
    moment = effective_confirmed_at(db, user).get(trigger.related_ref)
    if moment is None:
        return growth.WHITE_SPOT_TEXT_RU
    return growth.decay_text(name_ru, growth.freshness_for(trigger.related_ref, moment))


# --- сборка ---------------------------------------------------------------


def sync(db: Session, user: User) -> None:
    """Один проход наблюдателя. Вызывается при чтении истории роста."""
    events = _events(db, user)

    _watch_evidence(db, user, events)
    _watch_roles(db, user, events)
    _watch_statuses(db, user, events)
    _watch_trust(db, user, events)
    _watch_disputes(db, user, events)
    _watch_reuse(db, user, events)
    _watch_freshness(db, user)
    db.commit()

    _watch_triggers(db, user)
    db.commit()


def _payload(db: Session, user: User) -> GrowthOut:
    events = _events(db, user)

    periods: list[dict] = []
    for item in events:
        label = growth.month_label(_aware(item.occurred_at))
        if not periods or periods[-1]["label_ru"] != label:
            periods.append({"label_ru": label, "events": []})
        periods[-1]["events"].append(
            {
                "id": public_id("pge", item.id),
                "event_type": item.event_type,
                "subject_ref": item.subject_ref,
                "description_ru": item.description_ru,
                "from_value": item.from_value,
                "to_value": item.to_value,
                "occurred_at": item.occurred_at,
            }
        )
    periods.reverse()
    for period in periods:
        period["events"].reverse()

    triggers = list(
        db.scalars(
            select(ReturnTrigger)
            .where(
                ReturnTrigger.user_id == user.id,
                ReturnTrigger.status.in_((growth.PENDING, growth.SENT)),
            )
            .order_by(ReturnTrigger.id)
        )
    )
    # Показ на экране - единственный канал доставки, который тут есть. Отмечаем
    # его честно как `sent` и никогда не считаем успехом (FR5.4).
    for trigger in triggers:
        if trigger.status == growth.PENDING:
            trigger.status = growth.SENT
            trigger.sent_at = growth.utcnow()
    db.commit()

    all_triggers = list(
        db.scalars(select(ReturnTrigger).where(ReturnTrigger.user_id == user.id))
    )
    sent = [item for item in all_triggers if item.sent_at is not None]
    acted = [item for item in all_triggers if item.status == growth.ACTED_UPON]

    return GrowthOut.model_validate(
        {
            "note_ru": NOTE_RU,
            "periods": periods,
            "freshness": freshness_list(db, user),
            "triggers": [
                {
                    "id": public_id("rt", trigger.id),
                    "trigger_type": trigger.trigger_type,
                    "related_ref": trigger.related_ref,
                    "text_ru": _trigger_text(db, user, trigger),
                    "status": trigger.status,
                    "created_at": trigger.created_at,
                }
                for trigger in triggers
            ],
            "stats": {
                "triggers_sent": len(sent),
                "triggers_acted_upon": len(acted),
                "acted_upon_ratio": round(len(acted) / len(sent), 2) if sent else None,
                "confirmed_competencies": len(confirmed_competencies(db, user)),
                "reused_across_roles": len(
                    [e for e in events if e.event_type == growth.REUSED_ACROSS_ROLE]
                ),
            },
        }
    )


# --- эндпоинты ------------------------------------------------------------


@router.get("", response_model=GrowthOut)
def read_growth(user: User = Depends(current_user), db: Session = Depends(get_db)) -> GrowthOut:
    """FR4.4: история доступна одинаково в обоих режимах видимости.

    Скрытый профиль - это тот же Self-Audit, а не урезанная версия продукта.
    """
    sync(db, user)
    return _payload(db, user)


@router.post("/freshness/{competency_id}/refresh", response_model=GrowthOut)
def refresh_competency(
    competency_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> GrowthOut:
    """«Актуализировать»: одно нажатие возвращает полный вес (FR5.3).

    Доказывать заново ничего не нужно - в этом весь смысл модуля. Подтверждение
    никуда не девалось, устарела только его рыночная актуальность.
    """
    row = db.scalar(
        select(CompetencyFreshness).where(
            CompetencyFreshness.user_id == user.id,
            CompetencyFreshness.competency_id == competency_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Такой подтверждённой компетенции нет.")

    row.last_confirmed_at = growth.utcnow()
    row.decay_countdown_started_at = growth.utcnow()
    db.commit()

    sync(db, user)
    return _payload(db, user)


@router.post("/triggers/{trigger_id}/dismiss", response_model=GrowthOut)
def dismiss_trigger(
    trigger_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> GrowthOut:
    """Напоминание можно закрыть. Это не действие - и успехом не считается."""
    from app.routers.profile import parse_id

    trigger = db.get(ReturnTrigger, parse_id("rt", trigger_id))
    if trigger is None or trigger.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Напоминание не найдено.")

    trigger.status = growth.DISMISSED
    db.commit()
    return _payload(db, user)
