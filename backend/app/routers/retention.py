"""Модуль 11: замкнутый цикл возвращения кандидата.

Своей логики подсчёта здесь нет вообще. Модуль соединяет два уже готовых
куска: механизм совпадения из модуля 10 и механизм поводов вернуться из
модуля 8 - и превращает их в один цикл.

Проверяемая этим модулем гипотеза - самая неуверенная во всём продукте:
вернётся ли человек и сделает ли что-то, если ему показать конкретную
возможность. Поэтому здесь важнее всего одно правило: **значимо только
`acted_upon`.** Показ уведомления не доказывает ничего. Много отправленных
поводов при нулевом действии - это провал гипотезы, а не работающая функция.

Живого парсинга вакансий нет: «появилась новая вакансия» изображается сверкой
дат набора с отметкой последней проверки. Когда парсинг появится, он станет
вторым производителем того же события.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import growth, vacancies as library
from app.db import get_db
from app.models import (
    ProfileGrowthEvent,
    ReturnTrigger,
    User,
    VacancyCheckpoint,
    VacancyMatchState,
)
from app.routers.auth import current_user
from app.routers.profile import parse_id, public_id
from app.routers.vacancies import feed, match_for
from app.schemas_retention import RetentionOut
from app.xai import VACANCY_MATCH, vacancy_explanation_id

router = APIRouter(prefix="/api/retention", tags=["retention"])

# --- калибруемая константа (§4.2 FRD) ------------------------------------
#
# Ниже какого совпадения не стоит и беспокоить. Число иллюстративное, не
# проверенное - держится отдельной константой, как и все прочие в проекте.
MIN_MATCH_SCORE_TO_NOTIFY = 55

NEW_MATCHING_VACANCY = "new_matching_vacancy"

NOTE_RU = (
    "Мы сообщаем не про все вакансии, а про те, где ваш профиль уже близок. И показываем, "
    "чего именно не хватает — чтобы возвращаться было ради конкретного дела, а не «посмотреть»."
)

CROSS_TEMPLATE_RU = "Эта компетенция теперь учитывается ещё в {count} подходящих вакансиях в вашей ленте."


def _checkpoint(db: Session, user: User) -> VacancyCheckpoint:
    row = db.get(VacancyCheckpoint, user.id)
    if row is None:
        # Первый заход: считаем, что всё уже виденное. Иначе кандидат получил бы
        # семь «новых» вакансий в первую же секунду - ровно та рассылка, которой
        # этот продукт не хочет быть.
        row = VacancyCheckpoint(user_id=user.id, last_checked_at=growth.utcnow())
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _explanation_text(vacancy: library.Vacancy, result: library.MatchResult) -> str:
    """Почему эта вакансия вообще всплыла - фактом, а не «вам подойдёт» (FR2.1).

    Текст собирается из разбора требований модуля 10, а не из второго,
    параллельного суждения о релевантности.
    """
    mandatory = [
        item for item in vacancy.requirements if item.criticality == library.MANDATORY
    ]
    covered_ids = {item.requirement_id for item in result.covered}
    covered_mandatory = [item for item in mandatory if item.id in covered_ids]

    missing = [
        item.label_ru
        for item in result.uncovered
        if item.criticality == library.MANDATORY
    ]

    text = (
        f"Совпадение {result.overall_match_score}% — подтверждены "
        f"{len(covered_mandatory)} из {len(mandatory)} обязательных требований"
    )
    if missing:
        text += f", не хватает независимого подтверждения по: {', '.join(missing)}"
    return text + "."


# --- обнаружение ----------------------------------------------------------


def sweep(db: Session, user: User) -> int:
    """Один проход обнаружения (§4.3). Возвращает число новых поводов.

    Повторно про ту же вакансию не напоминаем никогда - даже если профиль
    изменился и совпадение стало выше. Второе уведомление про то же самое -
    это усталость от уведомлений, а вернуться к ленте кандидат может и сам.
    """
    checkpoint = _checkpoint(db, user)
    since = _aware(checkpoint.last_checked_at)

    already = {
        trigger.related_ref
        for trigger in db.scalars(
            select(ReturnTrigger).where(
                ReturnTrigger.user_id == user.id,
                ReturnTrigger.trigger_type == NEW_MATCHING_VACANCY,
            )
        )
    }

    created = 0
    for vacancy in feed(db, user):
        if vacancy.id in already or _aware(vacancy.created_at) <= since:
            continue

        result = match_for(db, user, vacancy)
        if result.overall_match_score < MIN_MATCH_SCORE_TO_NOTIFY:
            continue

        db.add(
            ReturnTrigger(
                user_id=user.id,
                trigger_type=NEW_MATCHING_VACANCY,
                related_ref=vacancy.id,
                match_score_at_detection=result.overall_match_score,
                explanation_ref=vacancy_explanation_id(vacancy.id),
            )
        )
        created += 1

    checkpoint.last_checked_at = growth.utcnow()
    db.commit()
    return created


# --- накопительный эффект -------------------------------------------------


def _match_states(db: Session, user: User) -> dict[str, VacancyMatchState]:
    return {
        row.vacancy_id: row
        for row in db.scalars(
            select(VacancyMatchState).where(VacancyMatchState.user_id == user.id)
        )
    }


def _mark_acted_upon(db: Session, user: User, vacancy_id: str) -> None:
    """Повод считается сработавшим, только когда требование действительно
    закрылось. Открыть уведомление - не действие (§4.4 модуля 8)."""
    trigger = db.scalar(
        select(ReturnTrigger).where(
            ReturnTrigger.user_id == user.id,
            ReturnTrigger.trigger_type == NEW_MATCHING_VACANCY,
            ReturnTrigger.related_ref == vacancy_id,
            ReturnTrigger.status.in_((growth.PENDING, growth.SENT)),
        )
    )
    if trigger is None:
        return
    trigger.status = growth.ACTED_UPON
    trigger.acted_upon_at = growth.utcnow()


def recompute_across_feed(db: Session, user: User, focus_vacancy_id: str | None = None) -> list[str]:
    """Пересчитывает совпадение по всей ленте и находит побочный эффект (FR4.1).

    Новой логики подсчёта здесь нет: это цикл по вакансиям вокруг того же
    вызова модуля 10. Единственное, что добавляется, - память о прошлом
    состоянии, без которой «стало лучше ещё в двух местах» посчитать не из чего.

    Возвращает названия вакансий, где закрылось требование помимо той, ради
    которой кандидат вернулся.
    """
    states = _match_states(db, user)
    improved: list[str] = []

    for vacancy in feed(db, user):
        result = match_for(db, user, vacancy)
        covered = sorted(item.requirement_id for item in result.covered)
        row = states.get(vacancy.id)

        if row is None:
            db.add(
                VacancyMatchState(
                    user_id=user.id,
                    vacancy_id=vacancy.id,
                    match_score=result.overall_match_score,
                    covered_requirement_ids=",".join(covered),
                )
            )
            continue

        before = [item for item in row.covered_requirement_ids.split(",") if item]
        gained = [item for item in covered if item not in before]

        if gained and vacancy.id != focus_vacancy_id:
            improved.append(vacancy.title_ru)

        if gained:
            _mark_acted_upon(db, user, vacancy.id)

        row.match_score = result.overall_match_score
        row.covered_requirement_ids = ",".join(covered)

    if improved:
        # Событие роста, а не отдельная лента: накопительный эффект должен
        # попасть в ту же историю, где кандидат смотрит на свой прогресс.
        db.add(
            ProfileGrowthEvent(
                user_id=user.id,
                event_type=growth.MATCH_ACROSS_VACANCIES,
                subject_ref=",".join(sorted(improved)),
                to_value=str(len(improved)),
                description_ru=CROSS_TEMPLATE_RU.format(count=len(improved)),
                occurred_at=growth.utcnow(),
            )
        )

    db.commit()
    return improved


# --- сборка ---------------------------------------------------------------


def _trigger_out(db: Session, user: User, trigger: ReturnTrigger) -> dict:
    vacancy = library.BY_ID.get(trigger.related_ref)
    result = match_for(db, user, vacancy) if vacancy else None

    return {
        "id": public_id("rt", trigger.id),
        "vacancy_id": trigger.related_ref,
        "vacancy_title_ru": vacancy.title_ru if vacancy else trigger.related_ref,
        "company_label": vacancy.company_label if vacancy else "",
        "match_score_at_detection": trigger.match_score_at_detection or 0,
        "match_score_now": result.overall_match_score if result else 0,
        "explanation_id": trigger.explanation_ref,
        "explanation_ru": _explanation_text(vacancy, result) if vacancy and result else "",
        "status": trigger.status,
        "created_at": trigger.created_at,
    }


def _payload(db: Session, user: User) -> RetentionOut:
    triggers = list(
        db.scalars(
            select(ReturnTrigger)
            .where(
                ReturnTrigger.user_id == user.id,
                ReturnTrigger.trigger_type == NEW_MATCHING_VACANCY,
                ReturnTrigger.status.in_((growth.PENDING, growth.SENT)),
            )
            .order_by(ReturnTrigger.id)
        )
    )
    for trigger in triggers:
        if trigger.status == growth.PENDING:
            trigger.status = growth.SENT
            trigger.sent_at = growth.utcnow()
    db.commit()

    all_triggers = list(
        db.scalars(
            select(ReturnTrigger).where(
                ReturnTrigger.user_id == user.id,
                ReturnTrigger.trigger_type == NEW_MATCHING_VACANCY,
            )
        )
    )
    sent = [item for item in all_triggers if item.sent_at is not None]
    acted = [item for item in all_triggers if item.status == growth.ACTED_UPON]

    cross = list(
        db.scalars(
            select(ProfileGrowthEvent)
            .where(
                ProfileGrowthEvent.user_id == user.id,
                ProfileGrowthEvent.event_type == growth.MATCH_ACROSS_VACANCIES,
            )
            .order_by(ProfileGrowthEvent.id.desc())
        )
    )

    return RetentionOut.model_validate(
        {
            "note_ru": NOTE_RU,
            "min_match_score_to_notify": MIN_MATCH_SCORE_TO_NOTIFY,
            "triggers": [_trigger_out(db, user, item) for item in triggers],
            "cross_vacancy_events": [
                {
                    "id": public_id("pge", item.id),
                    "description_ru": item.description_ru,
                    "occurred_at": item.occurred_at,
                }
                for item in cross[:5]
            ],
            "stats": {
                "sent": len(sent),
                "acted_upon": len(acted),
                "acted_upon_ratio": round(len(acted) / len(sent), 2) if sent else None,
            },
        }
    )


# --- эндпоинты ------------------------------------------------------------


@router.get("", response_model=RetentionOut)
def read_retention(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> RetentionOut:
    recompute_across_feed(db, user)
    return _payload(db, user)


@router.post("/check", response_model=RetentionOut)
def check_for_new(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> RetentionOut:
    """Проход обнаружения вручную - замена расписанию, которого негде держать.

    В прототипе это осознанно видимое действие, а не фоновая задача: так
    понятно, что именно сработало, и это важно для замера самой гипотезы.
    """
    sweep(db, user)
    return _payload(db, user)


@router.post("/triggers/{trigger_id}/open", response_model=RetentionOut)
def open_trigger(
    trigger_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> RetentionOut:
    """Кандидат открыл повод. Это ещё не действие - и успехом не считается."""
    trigger = db.get(ReturnTrigger, parse_id("rt", trigger_id))
    if trigger is None or trigger.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Повод не найден.")

    recompute_across_feed(db, user, focus_vacancy_id=trigger.related_ref)
    return _payload(db, user)


@router.post("/triggers/{trigger_id}/dismiss", response_model=RetentionOut)
def dismiss(
    trigger_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> RetentionOut:
    trigger = db.get(ReturnTrigger, parse_id("rt", trigger_id))
    if trigger is None or trigger.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Повод не найден.")

    trigger.status = growth.DISMISSED
    db.commit()
    return _payload(db, user)
