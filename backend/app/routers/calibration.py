"""Модуль 14: обратная связь рекрутера и калибровка.

Единственное место в продукте, где система сверяется с реальностью. Всё
остальное может быть внутренне безупречным и при этом ошибаться насчёт мира;
здесь проверяется, совпал ли вывод с тем, что человек увидел вживую.

Два жёстких правила:

1. **Отзыв рекрутера не меняет балл кандидата.** Ни при каких условиях, ни
   одним путём. Это вход в общую статистику, а не оценка конкретного человека:
   иначе мнение одного рекрутера могло бы уронить чей-то профиль, и всё, на чём
   стоит модуль 6, перестало бы работать.
2. **Формулы сами не подстраиваются.** Автоматического пересчёта коэффициентов
   по накопленной обратной связи здесь нет и быть не должно. Человек смотрит на
   данные и принимает решение письменно, под запись.

Этот модуль - отборщик, а не проверяющий: партия на ручной разбор превращается
в обычные споры модуля 7 и разбирается его же очередью. Второго экрана разбора
здесь нет.
"""

import json
import random
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import calibration
from app import candidates as pool
from app.db import get_db
from app.models import (
    AuditBatch,
    CalibrationConstantChangeLog,
    ComponentFeedback,
    DisputeCase,
    ModeratorOverride,
    RecruiterFeedback,
    User,
)
from app.access import require_moderator, require_recruiter
from app.routers.auth import current_user
from app.schemas_calibration import (
    BatchIn,
    CalibrationOut,
    ChangeIn,
    FeedbackIn,
    FeedbackStateOut,
)
from app.xai import SUBJECT_TYPE_RU

# Здесь две разные двери, и разграничивать их надо тоже по-разному.
#
# Отзыв о кандидате оставляет рекрутер: он видел человека на собеседовании.
# Сводку по формулам и изменение калибруемых величин смотрит оператор - это
# роль модератора, и рекрутеру там делать нечего: менять то, как система
# считает всех, он не должен.
#
# Роутера два именно поэтому: страж на роутере целиком надёжнее, чем проверка
# в каждом обработчике, которую однажды забудут добавить.
feedback_router = APIRouter(
    prefix="/api/calibration",
    tags=["calibration"],
    dependencies=[Depends(require_recruiter)],
)

router = APIRouter(
    prefix="/api/calibration",
    tags=["calibration"],
    dependencies=[Depends(require_moderator)],
)

NOT_PRODUCTION_SAFE_RU = (
    "Экран оператора без доступа и без ролей: его может открыть любой вошедший. Так можно "
    "только локально — настоящее разграничение прав здесь ещё не появилось."
)

NOTE_RU = (
    "Здесь проверяется не кандидат, а сами формулы. Отзыв рекрутера никогда не меняет чей-то "
    "балл — он идёт только в общую статистику."
)

FEEDBACK_NOTE_RU = (
    "Один ответ — уже полный отзыв. Подробности по отдельным выводам необязательны, "
    "и на балл кандидата это не влияет никак."
)


# --- сторона рекрутера ----------------------------------------------------


def _scores(db: Session, user: User, candidate_id: str) -> tuple[int, int]:
    """Баллы на момент отзыва - чтобы потом сравнивать с тем, что утверждалось.

    Берутся у тех же движков, что и везде: записанные руками цифры разошлись бы
    с настоящим расчётом, и вся сверка с реальностью считалась бы не по тому,
    что система на самом деле утверждала.
    """
    candidate = pool.find_visible(db, user, candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Такого кандидата нет.")

    snapshots = pool.prof_snapshots(candidate)
    prof = max((item["overall_score"] for item in snapshots), default=0)
    return pool.trust_overall(candidate), prof


def _feedback_out(db: Session, item: RecruiterFeedback) -> dict:
    count = len(
        list(db.scalars(select(ComponentFeedback).where(ComponentFeedback.feedback_id == item.id)))
    )
    return {
        "id": f"rf_{item.id:03d}",
        "candidate_id": item.candidate_id,
        "vacancy_id": item.vacancy_id,
        "relevance_outcome": item.relevance_outcome,
        "relevance_outcome_ru": calibration.OUTCOME_RU[item.relevance_outcome],
        "trust_score_at_feedback": item.trust_score_at_feedback,
        "prof_score_at_feedback": item.prof_score_at_feedback,
        "free_text_comment": item.free_text_comment,
        "component_count": count,
        "submitted_at": item.submitted_at,
    }


def _latest(db: Session, user: User, candidate_id: str) -> RecruiterFeedback | None:
    return db.scalar(
        select(RecruiterFeedback)
        .where(
            RecruiterFeedback.recruiter_user_id == user.id,
            RecruiterFeedback.candidate_id == candidate_id,
        )
        .order_by(RecruiterFeedback.id.desc())
    )


def _state(db: Session, user: User, candidate_id: str) -> FeedbackStateOut:
    submitted = _latest(db, user, candidate_id)
    verdicts: dict[str, str] = {}
    if submitted is not None:
        for item in db.scalars(
            select(ComponentFeedback).where(ComponentFeedback.feedback_id == submitted.id)
        ):
            verdicts[item.explanation_id] = item.verdict

    return FeedbackStateOut.model_validate(
        {
            "prompt_ru": calibration.OUTCOME_PROMPT_RU,
            "component_prompt_ru": calibration.COMPONENT_PROMPT_RU,
            "options": [
                {"value": value, "label_ru": calibration.OUTCOME_RU[value]}
                for value in calibration.OUTCOMES
            ],
            "verdicts": [
                {"value": value, "label_ru": calibration.VERDICT_RU[value]}
                for value in calibration.VERDICTS
            ],
            "note_ru": FEEDBACK_NOTE_RU,
            "submitted": _feedback_out(db, submitted) if submitted else None,
            "component_verdicts": verdicts,
        }
    )


@feedback_router.get("/feedback/{candidate_id}", response_model=FeedbackStateOut)
def read_feedback(
    candidate_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> FeedbackStateOut:
    return _state(db, user, candidate_id)


@feedback_router.post(
    "/feedback", response_model=FeedbackStateOut, status_code=status.HTTP_201_CREATED
)
def submit_feedback(
    data: FeedbackIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> FeedbackStateOut:
    """FR1.1-FR1.3: одно действие, и оно ничего не меняет в профиле кандидата.

    Ни одна строка ниже не пишет в данные кандидата. Это проверяется тестом,
    который читает исходник модуля, - потому что «мы же помним, что так нельзя»
    работает ровно до первой правки в спешке.
    """
    if data.relevance_outcome not in calibration.OUTCOMES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный исход.")
    for item in data.component_feedback:
        if item.verdict not in calibration.VERDICTS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестная отметка.")

    trust, prof = _scores(db, user, data.candidate_id)

    feedback = RecruiterFeedback(
        recruiter_user_id=user.id,
        candidate_id=data.candidate_id,
        vacancy_id=data.vacancy_id,
        relevance_outcome=data.relevance_outcome,
        trust_score_at_feedback=trust,
        prof_score_at_feedback=prof,
        free_text_comment=(data.free_text_comment or "").strip() or None,
    )
    db.add(feedback)
    db.flush()

    for item in data.component_feedback:
        db.add(
            ComponentFeedback(
                feedback_id=feedback.id,
                explanation_id=item.explanation_id,
                subject_type=item.subject_type,
                subject_id=item.subject_id,
                verdict=item.verdict,
                comment_ru=(item.comment_ru or "").strip() or None,
            )
        )

    db.commit()
    return _state(db, user, data.candidate_id)


# --- сторона оператора ----------------------------------------------------


def _insights(db: Session) -> list[dict]:
    """Сводка считается из отзывов на чтение, а не копится отдельным счётчиком."""
    grouped: dict[tuple[str, str], list[str]] = {}
    for item in db.scalars(select(ComponentFeedback).order_by(ComponentFeedback.id)):
        grouped.setdefault((item.subject_type, item.subject_id), []).append(item.verdict)

    found = []
    for (subject_type, subject_id), verdicts in grouped.items():
        insight = calibration.insight_for(subject_type, subject_id, verdicts)
        found.append(
            {
                "subject_type": insight.subject_type,
                "subject_type_ru": SUBJECT_TYPE_RU.get(subject_type, subject_type),
                "subject_id": insight.subject_id,
                "sample_size": insight.sample_size,
                "misleading_rate": insight.misleading_rate,
                "useful_rate": insight.useful_rate,
                "flagged_for_review": insight.flagged_for_review,
            }
        )
    return sorted(found, key=lambda item: (-item["misleading_rate"], item["subject_id"]))


def _accuracy(db: Session) -> dict:
    rows = list(db.scalars(select(RecruiterFeedback).order_by(RecruiterFeedback.id)))
    pairs = [(row.relevance_outcome, row.trust_score_at_feedback) for row in rows]
    payload = calibration.trust_accuracy(pairs)
    payload["period_label"] = "за всё время"
    return payload


def _current_values() -> dict[str, str]:
    """Текущие значения калибруемых констант - из живого кода, а не из копии."""
    from app import growth, prof, trust, vacancies

    return {
        "module3.status_score_mapping": str(prof.STATUS_SCORE),
        "module6.independence_weighting": str(trust.REPEAT_IN_CATEGORY),
        "module8.decay_countdown_days": str(growth.DECAY_COUNTDOWN_DAYS),
        "module10.criticality_weight": str(vacancies.CRITICALITY_WEIGHT),
        "module11.min_match_score_to_notify": str(_notify_threshold()),
        "module14.min_sample_size": str(calibration.MIN_SAMPLE_SIZE),
        "module14.misleading_rate_threshold": str(calibration.MISLEADING_RATE_THRESHOLD),
    }


def _notify_threshold() -> int:
    from app.routers import retention

    return retention.MIN_MATCH_SCORE_TO_NOTIFY


def _changes(db: Session) -> list[dict]:
    return [
        {
            "id": f"ccl_{row.id:03d}",
            "constant_ref": row.constant_ref,
            "label_ru": calibration.CALIBRATABLE.get(row.constant_ref, row.constant_ref),
            "previous_value": row.previous_value,
            "new_value": row.new_value,
            "rationale_ru": row.rationale_ru,
            "based_on_feedback_count": row.based_on_feedback_count,
            "trust_accuracy_before": row.trust_accuracy_before,
            "applied_at": row.applied_at,
        }
        for row in db.scalars(
            select(CalibrationConstantChangeLog).order_by(CalibrationConstantChangeLog.id.desc())
        )
    ]


def _batch_pattern(db: Session, batch: AuditBatch) -> tuple[str, dict[str, int]]:
    """Что показала партия целиком - то, чего в модуле 7 нет.

    Модуль 7 разбирает по одному случаю. Систематическая ошибка видна только
    поверх партии: если правки кучкуются вокруг одного вида выводов, дело в нём.
    """
    case_ids = json.loads(batch.dispute_case_ids or "[]")
    if not case_ids:
        return "Партия ещё не разобрана.", {}

    numeric = [int(item.split("_")[1]) for item in case_ids]
    by_type: dict[str, int] = {}
    for override in db.scalars(
        select(ModeratorOverride).where(ModeratorOverride.dispute_case_id.in_(numeric))
    ):
        case = db.get(DisputeCase, override.dispute_case_id)
        if case is None:
            continue
        by_type[case.subject_type] = by_type.get(case.subject_type, 0) + 1

    if not by_type:
        resolved = [
            case
            for case in db.scalars(select(DisputeCase).where(DisputeCase.id.in_(numeric)))
            if case.status.startswith("resolved")
        ]
        if not resolved:
            return f"Разобрано 0 из {len(case_ids)} — партия ещё в очереди модератора.", {}
        return "Партия разобрана, ни один вывод исправлять не пришлось.", {}

    top = max(by_type, key=lambda key: by_type[key])
    return (
        f"Чаще всего правили: {SUBJECT_TYPE_RU.get(top, top)} "
        f"({by_type[top]} из {sum(by_type.values())} правок). Это и есть кандидат на калибровку.",
        by_type,
    )


def _batches(db: Session) -> list[dict]:
    found = []
    for batch in db.scalars(select(AuditBatch).order_by(AuditBatch.id.desc())):
        pattern, by_type = _batch_pattern(db, batch)
        found.append(
            {
                "id": f"batch_{batch.id:03d}",
                "selection_criteria": batch.selection_criteria,
                "selection_ru": calibration.SELECTION_RU[batch.selection_criteria],
                "candidate_ids": json.loads(batch.candidate_ids or "[]"),
                "dispute_case_ids": json.loads(batch.dispute_case_ids or "[]"),
                "created_at": batch.created_at,
                "pattern_ru": pattern,
                "overridden_by_subject_type": by_type,
            }
        )
    return found


def _payload(db: Session) -> CalibrationOut:
    values = _current_values()
    return CalibrationOut.model_validate(
        {
            "not_production_safe_ru": NOT_PRODUCTION_SAFE_RU,
            "note_ru": NOTE_RU,
            "accuracy": _accuracy(db),
            "insights": _insights(db),
            "constants": [
                {
                    "constant_ref": ref,
                    "label_ru": label,
                    "current_value": values.get(ref, "—"),
                }
                for ref, label in calibration.CALIBRATABLE.items()
            ],
            "changes": _changes(db),
            "batches": _batches(db),
            "selection_options": [
                {"value": value, "label_ru": calibration.SELECTION_RU[value]}
                for value in calibration.SELECTION_CRITERIA
            ],
        }
    )


@router.get("", response_model=CalibrationOut)
def read_calibration(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> CalibrationOut:
    return _payload(db)


@router.post("/changes", response_model=CalibrationOut, status_code=status.HTTP_201_CREATED)
def record_change(
    change: ChangeIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> CalibrationOut:
    """FR3.3: единственный законный способ изменить калибруемую величину.

    Запись фиксирует решение, а не выполняет его: значение в коде меняет
    человек следующим коммитом. Так изменение проходит обычное ревью, а не
    случается из веб-формы на живой системе - и остаётся видимым в истории.
    """
    if change.constant_ref not in calibration.CALIBRATABLE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Эту величину через калибровку менять нельзя — список закрытый.",
        )

    accuracy = _accuracy(db)
    db.add(
        CalibrationConstantChangeLog(
            constant_ref=change.constant_ref,
            previous_value=_current_values().get(change.constant_ref, ""),
            new_value=change.new_value,
            rationale_ru=change.rationale_ru.strip(),
            based_on_feedback_count=accuracy["total_feedback_count"],
            trust_accuracy_before=accuracy["trust_accuracy_pct"],
            applied_by=user.email,
        )
    )
    db.commit()
    return _payload(db)


@router.post("/batches", response_model=CalibrationOut, status_code=status.HTTP_201_CREATED)
def create_batch(
    request: BatchIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> CalibrationOut:
    """FR4.1-FR4.2: отбираем профили, а разбирает их очередь модуля 7.

    Отбор по расхождению - по умолчанию: у команды из двух человек нет ресурса
    на равномерную случайную выборку, и случаи, где вывод разошёлся с исходом,
    дают на единицу времени несопоставимо больше.
    """
    from app.routers.xai import SAMPLED_AUDIT, append_history

    if request.selection_criteria not in calibration.SELECTION_CRITERIA:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный способ отбора.")

    rows = list(db.scalars(select(RecruiterFeedback).order_by(RecruiterFeedback.id)))
    if not rows:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Пока нет ни одного отзыва — отбирать не из чего.",
        )

    if request.selection_criteria == calibration.HIGH_DIVERGENCE:
        chosen = [
            row
            for row in rows
            if calibration.outcomes_agree(row.relevance_outcome, row.trust_score_at_feedback)
            is False
        ]
    else:
        chosen = random.sample(rows, min(request.size, len(rows)))

    chosen = chosen[: request.size]
    if not chosen:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Расхождений между выводом и исходом пока не нашлось.",
        )

    batch = AuditBatch(
        selection_criteria=request.selection_criteria,
        candidate_ids=json.dumps([row.candidate_id for row in chosen], ensure_ascii=False),
    )
    db.add(batch)
    db.flush()

    case_ids: list[str] = []
    for row in chosen:
        case = DisputeCase(
            user_id=user.id,
            explanation_id=f"expl_audit_{row.candidate_id}",
            subject_type="trust_component",
            subject_id=row.candidate_id,
            explanation_conclusion_ru=(
                f"Выборочная проверка: Trust {row.trust_score_at_feedback} против исхода "
                f"«{calibration.OUTCOME_RU[row.relevance_outcome]}» после собеседования."
            ),
            explanation_evidence_refs="[]",
            origin=SAMPLED_AUDIT,
            status="queued",
        )
        db.add(case)
        db.flush()
        append_history(db, case, "opened", "system", after_value="queued")
        case_ids.append(f"dc_{case.id:03d}")

    batch.dispute_case_ids = json.dumps(case_ids, ensure_ascii=False)
    db.commit()
    return _payload(db)
