"""Модуль 7: объяснимость и споры (сторона кандидата).

Здесь две идеи. Первая: любой вывод системы можно спросить «почему» одним и тем
же способом, независимо от того, какой модуль его сделал. Вторая: с любым
выводом можно не согласиться и передать его человеку.

Собственных выводов этот модуль не делает вообще. Он читает модули 3, 4 и 6 и
приводит их объяснения к одной форме - и не трогает их внутренности (§7 FRD).
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    ContradictionCase,
    DisputeCase,
    DisputeHistoryEntry,
    Evidence,
    ModeratorOverride,
    ProbeAnswer,
    ProbeQuestion,
    ProfRole,
    Statement,
    User,
)
from app.routers.auth import current_user
from app.routers.profile import parse_id, public_id
from app.schemas_xai import (
    CandidateReplyIn,
    DisputeIn,
    DisputesOut,
    ExplanationDetailOut,
    ExplanationsOut,
)
from app.xai import (
    CONTRADICTION_FINDING,
    DISPUTE_LABEL_RU,
    MODULE_3,
    MODULE_4,
    MODULE_6,
    PROBE_QUESTION_REASON,
    PROF_COMPETENCY_STATUS,
    SUBJECT_TYPE_RU,
    TRUST_COMPONENT,
    WHY_LABEL_RU,
    Explanation,
    contradiction_explanation_id,
    probe_explanation_id,
    validate,
)

router = APIRouter(prefix="/api", tags=["xai"])

# --- статусы спора --------------------------------------------------------

QUEUED = "queued"
IN_REVIEW = "in_review"
NEEDS_MORE_INFO = "needs_more_info"
RESOLVED_UPHELD = "resolved_upheld"
RESOLVED_OVERRIDDEN = "resolved_overridden"

OPEN_STATUSES = (QUEUED, IN_REVIEW, NEEDS_MORE_INFO)

STATUS_RU = {
    QUEUED: "В очереди на проверку",
    IN_REVIEW: "Смотрит модератор",
    NEEDS_MORE_INFO: "Модератор задал вопрос",
    RESOLVED_UPHELD: "Проверено, вывод оставлен",
    RESOLVED_OVERRIDDEN: "Проверено, вывод исправлен",
}

CANDIDATE_ESCALATION = "candidate_escalation"
ANOMALY_FLAG = "anomaly_flag"
SAMPLED_AUDIT = "sampled_audit"

ORIGIN_RU = {
    CANDIDATE_ESCALATION: "Кандидат не согласен с выводом",
    ANOMALY_FLAG: "Сигнал детектора аномалий",
    SAMPLED_AUDIT: "Выборочная проверка",
}

EVENT_RU = {
    "opened": "Спор открыт",
    "status_changed": "Статус изменился",
    "moderator_note_added": "Заключение модератора",
    "override_applied": "Вывод исправлен",
    "info_requested": "Модератор попросил подробности",
    "candidate_responded": "Ответ кандидата",
}

ACTOR_RU = {"candidate": "Кандидат", "moderator": "Модератор", "system": "Система"}

DISPUTE_NOTE_RU = (
    "Спор ничего не меняет в самом выводе: пока идёт проверка, статус и балл остаются "
    "прежними. Объяснять, почему вы не согласны, не обязательно."
)


# --- журнал ---------------------------------------------------------------


def append_history(
    db: Session,
    case: DisputeCase,
    event_type: str,
    actor: str,
    before_value: str | None = None,
    after_value: str | None = None,
    note_ru: str | None = None,
) -> DisputeHistoryEntry:
    """Единственный способ пополнить журнал. Правки записей не существует.

    Функция одна на оба роутера намеренно: две независимые записи истории - это
    ровно тот случай, когда они однажды разойдутся (§4.4 FRD).
    """
    entry = DisputeHistoryEntry(
        dispute_case_id=case.id,
        event_type=event_type,
        actor=actor,
        before_value=before_value,
        after_value=after_value,
        note_ru=note_ru,
    )
    db.add(entry)
    db.flush()
    return entry


def set_status(db: Session, case: DisputeCase, new_status: str, actor: str) -> None:
    """Смена статуса попадает в журнал до того, как вступит в силу (FR-Gov.3)."""
    if case.status == new_status:
        return
    append_history(db, case, "status_changed", actor, case.status, new_status)
    case.status = new_status


# --- сборка объяснений ----------------------------------------------------


def _prof_explanations(db: Session, user: User, now: datetime) -> list[Explanation]:
    """Статусы компетенций модуля 3 в канонической форме (FR1.1).

    Берём готовый ответ модуля 3 целиком, включая уже наложенные правки
    модератора: объяснение должно совпадать с тем, что кандидат видит на
    радаре, а не с тем, что было бы без правки.
    """
    from app.routers.prof import _payload

    if not db.scalar(select(ProfRole).where(ProfRole.user_id == user.id)):
        return []

    payload = _payload(db, user)
    found: list[Explanation] = []

    for snapshot in payload.snapshots:
        for component in snapshot.components:
            conclusion = component.reason
            if component.moderator_note_ru:
                conclusion = f"{conclusion} {component.moderator_note_ru}"

            found.append(
                Explanation(
                    id=component.explanation_id,
                    subject_type=PROF_COMPETENCY_STATUS,
                    subject_id=component.competency_id,
                    conclusion_ru=conclusion,
                    evidence_refs=tuple(component.statement_ids),
                    generated_by=MODULE_3,
                    created_at=now,
                    subject_label_ru=f"{component.name_ru} ({snapshot.level})",
                    subject_value_ru=component.status,
                )
            )
    return found


def _trust_explanations(db: Session, user: User, now: datetime) -> list[Explanation]:
    """Компоненты Trust Score в канонической форме (FR1.1)."""
    from app.routers.trust import _state

    payload = _state(db, user)
    found: list[Explanation] = []

    for component in payload.components:
        conclusion = component.explanation_ru
        if component.moderator_note_ru:
            conclusion = f"{conclusion} {component.moderator_note_ru}"

        found.append(
            Explanation(
                id=component.explanation_id,
                subject_type=TRUST_COMPONENT,
                subject_id=component.component_id,
                conclusion_ru=conclusion,
                evidence_refs=tuple(component.contributing_evidence_ids),
                generated_by=MODULE_6,
                created_at=now,
                subject_label_ru=component.name_ru,
                subject_value_ru=str(component.score),
            )
        )
    return found


def _contradiction_explanations(db: Session, user: User, now: datetime) -> list[Explanation]:
    cases = db.scalars(
        select(ContradictionCase)
        .where(ContradictionCase.user_id == user.id)
        .order_by(ContradictionCase.id)
    )

    found: list[Explanation] = []
    for case in cases:
        refs = []
        if case.evidence_id:
            refs.append(public_id("ev", case.evidence_id))
        if case.statement_id:
            refs.append(public_id("stmt", case.statement_id))

        found.append(
            Explanation(
                id=contradiction_explanation_id(public_id("cc", case.id)),
                subject_type=CONTRADICTION_FINDING,
                subject_id=public_id("cc", case.id),
                conclusion_ru=case.detail_ru,
                evidence_refs=tuple(refs),
                generated_by=MODULE_6,
                created_at=case.created_at or now,
                subject_label_ru="Нестыковка в профиле",
                subject_value_ru=case.status,
            )
        )
    return found


def _probe_explanations(db: Session, user: User, now: datetime) -> list[Explanation]:
    """Почему задан именно этот вопрос (FR1.1).

    Вопрос - тоже вывод системы о кандидате: она решила, что здесь пробел.
    Спорить с этим решением можно так же, как с баллом.
    """
    questions = db.scalars(
        select(ProbeQuestion).where(ProbeQuestion.user_id == user.id).order_by(ProbeQuestion.id)
    )

    found: list[Explanation] = []
    for question in questions:
        refs = []
        if question.artifact_evidence_id:
            refs.append(public_id("ev", question.artifact_evidence_id))

        answer = db.scalar(select(ProbeAnswer).where(ProbeAnswer.question_id == question.id))
        if answer is not None:
            refs.append(public_id("a", answer.id))

        found.append(
            Explanation(
                id=probe_explanation_id(public_id("q", question.id)),
                subject_type=PROBE_QUESTION_REASON,
                subject_id=public_id("q", question.id),
                conclusion_ru=question.reason_ru,
                evidence_refs=tuple(refs),
                generated_by=MODULE_4,
                created_at=question.created_at or now,
                subject_label_ru=question.text_ru,
                subject_value_ru=question.status,
            )
        )
    return found


def _vacancy_explanations(db: Session, user: User, now: datetime) -> list[Explanation]:
    """Почему система считает вакансию подходящей (модуль 11, FR2.1/FR2.3).

    Кандидат, пришедший из уведомления, и кандидат, открывший вакансию сам,
    должны попасть в одно и то же объяснение - поэтому оно собирается здесь, а
    не рисуется отдельным экраном внутри уведомления.
    """
    from app.models import ReturnTrigger
    from app.routers.retention import NEW_MATCHING_VACANCY, _explanation_text
    from app.routers.vacancies import match_for
    from app import vacancies as library
    from app.xai import VACANCY_MATCH, vacancy_explanation_id

    triggers = db.scalars(
        select(ReturnTrigger).where(
            ReturnTrigger.user_id == user.id,
            ReturnTrigger.trigger_type == NEW_MATCHING_VACANCY,
        )
    )

    found: list[Explanation] = []
    for trigger in triggers:
        vacancy = library.BY_ID.get(trigger.related_ref)
        if vacancy is None:
            continue
        result = match_for(db, user, vacancy)
        found.append(
            Explanation(
                id=vacancy_explanation_id(vacancy.id),
                subject_type=VACANCY_MATCH,
                subject_id=vacancy.id,
                conclusion_ru=_explanation_text(vacancy, result),
                # Объяснение опирается на разбор требований модуля 10, а не на
                # второе, отдельное суждение о релевантности (FR2.2).
                evidence_refs=tuple(
                    item.requirement_id for item in result.covered + result.uncovered
                ),
                generated_by="module_10",
                created_at=trigger.created_at or now,
                subject_label_ru=vacancy.title_ru,
                subject_value_ru=str(result.overall_match_score),
            )
        )
    return found


def collect(db: Session, user: User) -> list[Explanation]:
    """Все выводы системы об этом кандидате в одной форме."""
    now = datetime.now(timezone.utc)
    return [
        *_prof_explanations(db, user, now),
        *_trust_explanations(db, user, now),
        *_contradiction_explanations(db, user, now),
        *_probe_explanations(db, user, now),
        *_vacancy_explanations(db, user, now),
    ]


def find(db: Session, user: User, explanation_id: str) -> Explanation:
    """Поиск точным сравнением: идентификатор - формат, а не второй путь к данным."""
    for item in collect(db, user):
        if item.id == explanation_id:
            return item
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Такого вывода в профиле нет.")


# --- раскрытие доказательств (FR2.1) --------------------------------------


def _dead(ref: str, kind_ru: str) -> dict:
    return {
        "ref": ref,
        "kind": "unresolved",
        "resolved": False,
        "title_ru": f"{kind_ru} {ref} больше не открывается",
        "detail_ru": "Запись удалена. Это дефект: вывод ссылается на то, чего уже нет.",
    }


def resolve_refs(db: Session, owner: User, refs: list[str]) -> list[dict]:
    """Открывает каждую ссылку до настоящей записи.

    Ссылка, которая никуда не ведёт, помечается `resolved: false` и остаётся
    видимой: молча выкинуть её из списка - это и есть частичное раскрытие,
    запрещённое FR2.3.
    """
    resolved: list[dict] = []

    for ref in refs:
        prefix, _, _ = ref.partition("_")

        if prefix == "ev":
            item = db.get(Evidence, parse_id("ev", ref))
            if item is None or item.user_id != owner.id:
                resolved.append(_dead(ref, "Доказательство"))
                continue
            resolved.append(
                {
                    "ref": ref,
                    "kind": "evidence",
                    "resolved": True,
                    "title_ru": item.file_name or item.url or "Фрагмент текста",
                    "detail_ru": item.raw_text,
                    "url": item.url,
                    "file_name": item.file_name,
                }
            )

        elif prefix == "stmt":
            item = db.get(Statement, parse_id("stmt", ref))
            if item is None or item.user_id != owner.id:
                resolved.append(_dead(ref, "Компетенция"))
                continue
            resolved.append(
                {
                    "ref": ref,
                    "kind": "statement",
                    "resolved": True,
                    "title_ru": item.skill_name_ru,
                    "detail_ru": None,
                }
            )

        elif prefix == "a":
            item = db.get(ProbeAnswer, parse_id("a", ref))
            if item is None or item.user_id != owner.id:
                resolved.append(_dead(ref, "Ответ"))
                continue
            resolved.append(
                {
                    "ref": ref,
                    "kind": "answer",
                    "resolved": True,
                    "title_ru": "Ваш ответ на вопрос",
                    "detail_ru": item.text,
                }
            )

        elif prefix == "req":
            # Требование вакансии - не запись профиля: раскрывать нечего, но и
            # выбрасывать из списка нельзя (FR2.3 модуля 7).
            resolved.append(
                {
                    "ref": ref,
                    "kind": "requirement",
                    "resolved": True,
                    "title_ru": f"Требование вакансии {ref}",
                    "detail_ru": None,
                }
            )

        else:
            resolved.append(_dead(ref, "Ссылка"))

    return resolved


# --- сериализация ---------------------------------------------------------


def _open_dispute(db: Session, user: User, explanation_id: str) -> DisputeCase | None:
    return db.scalar(
        select(DisputeCase)
        .where(
            DisputeCase.user_id == user.id,
            DisputeCase.explanation_id == explanation_id,
            DisputeCase.status.in_(OPEN_STATUSES),
        )
        .order_by(DisputeCase.id.desc())
    )


def _explanation_out(db: Session, user: User, item: Explanation) -> dict:
    open_case = _open_dispute(db, user, item.id)
    return {
        "id": item.id,
        "subject_type": item.subject_type,
        "subject_type_ru": SUBJECT_TYPE_RU[item.subject_type],
        "subject_id": item.subject_id,
        "subject_label_ru": item.subject_label_ru,
        "subject_value_ru": item.subject_value_ru,
        "conclusion_ru": item.conclusion_ru,
        "evidence_refs": list(item.evidence_refs),
        "generated_by": item.generated_by,
        "candidate_consent_for_recruiter_view": item.candidate_consent_for_recruiter_view,
        "created_at": item.created_at,
        "dispute_label_ru": DISPUTE_LABEL_RU,
        # FR-Gov.1: окончательных, неоспоримых выводов в продукте нет.
        "disputable": True,
        "open_dispute_id": public_id("dc", open_case.id) if open_case else None,
    }


def serialize_case(db: Session, case: DisputeCase) -> dict:
    entries = db.scalars(
        select(DisputeHistoryEntry)
        .where(DisputeHistoryEntry.dispute_case_id == case.id)
        .order_by(DisputeHistoryEntry.id)
    )
    override = db.scalar(
        select(ModeratorOverride).where(ModeratorOverride.dispute_case_id == case.id)
    )

    return {
        "id": public_id("dc", case.id),
        "explanation_id": case.explanation_id,
        "subject_type": case.subject_type,
        "subject_type_ru": SUBJECT_TYPE_RU.get(case.subject_type, case.subject_type),
        "subject_id": case.subject_id,
        "conclusion_ru": case.explanation_conclusion_ru,
        "evidence_refs": json.loads(case.explanation_evidence_refs or "[]"),
        "origin": case.origin,
        "candidate_statement": case.candidate_statement,
        "status": case.status,
        "status_ru": STATUS_RU.get(case.status, case.status),
        "assigned_moderator": case.assigned_moderator,
        "info_request_ru": case.info_request_ru,
        "created_at": case.created_at,
        "history": [
            {
                "id": public_id("dh", entry.id),
                "event_type": entry.event_type,
                "event_ru": EVENT_RU.get(entry.event_type, entry.event_type),
                "actor": entry.actor,
                "actor_ru": ACTOR_RU.get(entry.actor, entry.actor),
                "before_value": entry.before_value,
                "after_value": entry.after_value,
                "note_ru": entry.note_ru,
                "timestamp": entry.timestamp,
            }
            for entry in entries
        ],
        "override": (
            {
                "id": public_id("mo", override.id),
                "target_type": override.target_type,
                "target_id": override.target_id,
                "previous_value": override.previous_value,
                "new_value": override.new_value,
                "rationale_ru": override.rationale_ru,
                "applied_at": override.applied_at,
            }
            if override
            else None
        ),
    }


# --- эндпоинты: объяснения ------------------------------------------------


@router.get("/explanations", response_model=ExplanationsOut)
def read_explanations(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ExplanationsOut:
    return ExplanationsOut.model_validate(
        {
            "why_label_ru": WHY_LABEL_RU,
            "explanations": [_explanation_out(db, user, item) for item in collect(db, user)],
        }
    )


@router.get("/explanations/{explanation_id}", response_model=ExplanationDetailOut)
def read_explanation(
    explanation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ExplanationDetailOut:
    """Экран «Почему такой вывод?»: факт, доказательства и кнопка спора.

    `problems` - самопроверка объяснения по правилам §4.1. Список тут не для
    красоты: пустой вывод, оценка вместо факта и ссылки в никуда - дефекты, и
    прятать их за молчанием было бы противоположностью смысла модуля.
    """
    item = find(db, user, explanation_id)
    payload = _explanation_out(db, user, item)
    payload["resolved_evidence"] = resolve_refs(db, user, list(item.evidence_refs))
    payload["problems"] = validate(item)
    return ExplanationDetailOut.model_validate(payload)


# --- эндпоинты: споры -----------------------------------------------------


def _disputes_payload(db: Session, user: User) -> DisputesOut:
    cases = db.scalars(
        select(DisputeCase).where(DisputeCase.user_id == user.id).order_by(DisputeCase.id.desc())
    )
    return DisputesOut.model_validate(
        {
            "dispute_label_ru": DISPUTE_LABEL_RU,
            "note_ru": DISPUTE_NOTE_RU,
            "cases": [serialize_case(db, case) for case in cases],
        }
    )


@router.get("/disputes", response_model=DisputesOut)
def read_disputes(user: User = Depends(current_user), db: Session = Depends(get_db)) -> DisputesOut:
    """FR3.4: кандидат видит статус и всю историю своего спора, а не «принято»."""
    return _disputes_payload(db, user)


@router.post("/disputes", response_model=DisputesOut, status_code=status.HTTP_201_CREATED)
def open_dispute(
    data: DisputeIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> DisputesOut:
    """FR3.1-FR3.3: оспорить вывод одним действием, без обязательных пояснений.

    Ничего не меняется ни в статусе компетенции, ни в балле: спор - это запрос
    на проверку. Проверяется это тестом, а не обещанием в тексте.
    """
    item = find(db, user, data.explanation_id)

    existing = _open_dispute(db, user, item.id)
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Этот вывод уже на проверке — второй спор не нужен."
        )

    case = DisputeCase(
        user_id=user.id,
        explanation_id=item.id,
        subject_type=item.subject_type,
        subject_id=item.subject_id,
        # Копия оспоренного вывода: индекс пересчитывается, а модератор должен
        # увидеть ровно то, с чем спорили (FR4.2).
        explanation_conclusion_ru=item.conclusion_ru,
        explanation_evidence_refs=json.dumps(list(item.evidence_refs), ensure_ascii=False),
        origin=CANDIDATE_ESCALATION,
        candidate_statement=(data.candidate_statement or "").strip() or None,
        status=QUEUED,
    )
    db.add(case)
    db.flush()

    # Спора без истории не бывает: запись «открыт» появляется сразу (§4.3).
    append_history(
        db, case, "opened", "candidate", after_value=QUEUED, note_ru=case.candidate_statement
    )
    db.commit()
    return _disputes_payload(db, user)


@router.post("/disputes/{case_id}/reply", response_model=DisputesOut)
def reply_to_moderator(
    case_id: str,
    data: CandidateReplyIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DisputesOut:
    """Ответ на конкретный вопрос модератора (FR4.3b)."""
    case = db.get(DisputeCase, parse_id("dc", case_id))
    if case is None or case.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Спор не найден.")
    if case.status != NEEDS_MORE_INFO:
        raise HTTPException(status.HTTP_409_CONFLICT, "По этому спору вопросов сейчас нет.")

    append_history(db, case, "candidate_responded", "candidate", note_ru=data.text.strip())
    set_status(db, case, QUEUED, "candidate")
    db.commit()
    return _disputes_payload(db, user)
