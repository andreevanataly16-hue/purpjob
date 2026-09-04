"""Модуль 4: Contextual Probe.

Вопрос задаётся только по компетенции, которая ещё не подтверждена, и строится
вокруг детали из материалов самого кандидата. Ответ - всегда свободный текст:
вариантов ответа здесь нет и правильной строки, с которой что-то сверяется,
тоже. Рядом с каждым вопросом стоит объяснение, почему он задан.

Ничего наказывающего в модуле нет и быть не может: пропуск, отказ по NDA и
неудачный ответ дают ноль, а не минус (FR6.4).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.declines import TARGET_QUESTION, is_declined, record_decline, revoke_declines
from app.enrichment import (
    DECLINED,
    PENDING,
    TYPE_BLIND_WITNESS,
    TYPE_FILE,
    TYPE_FREE_TEXT,
    TYPE_LINK,
    TYPE_PROBE_ANSWER,
    parse_free_text,
)
from app.models import (
    Evidence,
    ProbeAnswer,
    ProbeFeedback,
    ProbeFollowUp,
    ProbeQuestion,
    ProfRole,
    Statement,
    User,
)
from app.probe import (
    FREE_TEXT,
    MODE_GROUNDED,
    TARGET_WHITE_SPOT,
    Artifact,
    build_follow_up_reason,
    follow_up_reason,
    generate_question,
    understanding_signal,
)
from app.prof import compute_snapshot
from app.reference import ReferenceCompetency, get_profile
from app.routers.auth import current_user
from app.routers.nda import open_case
from app.routers.prof import _statement_views
from app.routers.profile import _ensure_statement, parse_id, public_id
from app.schemas_probe import (
    AnswerIn,
    DeclineIn,
    FeedbackIn,
    FollowUpAnswerIn,
    HistoryOut,
    NextIn,
    ProbeOut,
)
from app.taxonomy import BY_KEY

router = APIRouter(prefix="/api/probe", tags=["probe"])

# §4.5 FRD: значения и подписи меняются только парой.
FEEDBACK_REASONS: tuple[tuple[str, str], ...] = (
    ("not_related_to_project", "Не относится к моему проекту"),
    ("dont_understand", "Не понимаю вопрос"),
    ("too_narrow_framework", "Слишком узкий/специфичный фреймворк"),
    ("context_error", "Ошибка в контексте"),
    ("other", "Другое"),
)
REASON_VALUES = {value for value, _ in FEEDBACK_REASONS}

STATUS_RU = {
    "pending": "Ждёт ответа",
    "answered": "Отвечен",
    "skipped": "Пропущен",
    "declined_nda": "Отклонён по NDA",
    "flagged_bad": "Отмечен как неподходящий",
    "retired": "Снят: компетенция уже подтверждена",
}

NO_ROLE = (
    "Сначала выберите целевой уровень в PROF.индексе — вопросы задаются только по "
    "требованиям эталона, а не «на всякий случай»."
)
NO_GAPS = (
    "Спрашивать нечего: каждое требование эталона уже чем-то подтверждено. "
    "Вопрос ради вопроса здесь не задаётся."
)
NO_TEMPLATE = (
    "Для этой компетенции заготовки вопроса пока нет. Подтвердите её ссылкой, файлом "
    "или описанием проекта."
)


# --- цели: белые пятна модуля 3 -------------------------------------------


def _white_spots(db: Session, user: User) -> list[ReferenceCompetency]:
    """Белые пятна в том же порядке, что и в модуле 3 (FR1.2).

    Своей приоритизации у модуля 4 нет. Если кандидат ведёт две роли, берётся
    наибольший вес компетенции среди них.
    """
    roles = list(db.scalars(select(ProfRole).where(ProfRole.user_id == user.id)))
    if not roles:
        return []

    views = _statement_views(db, user)
    merged: dict[str, ReferenceCompetency] = {}

    for role in roles:
        profile = get_profile(role.level)
        snapshot = compute_snapshot(profile, views)
        by_id = {c.competency_id: c for c in profile.competencies}
        for competency_id in snapshot["white_spots"]:
            competency = by_id[competency_id]
            current = merged.get(competency_id)
            if current is None or competency.weight > current.weight:
                merged[competency_id] = competency

    return sorted(merged.values(), key=lambda c: (-c.weight, c.name_ru))


def _competency_by_id(competency_id: str) -> ReferenceCompetency | None:
    for level in ("Middle", "Senior"):
        for competency in get_profile(level).competencies:
            if competency.competency_id == competency_id:
                return competency
    return None


def _retire_stale(db: Session, user: User, spots: list[ReferenceCompetency]) -> None:
    """FR1.3: вопрос по уже подтверждённой компетенции снимается сам.

    Без последствий для кандидата: его просто не просят «дозакрыть» то, что
    больше не нужно.
    """
    if not spots:
        return

    open_ids = {competency.competency_id for competency in spots}
    changed = False
    for question in db.scalars(
        select(ProbeQuestion).where(
            ProbeQuestion.user_id == user.id, ProbeQuestion.status == "pending"
        )
    ):
        if question.competency_id not in open_ids:
            question.status = "retired"
            changed = True
    if changed:
        db.commit()


# --- материалы кандидата --------------------------------------------------


def _artifacts(db: Session, user: User, competency: ReferenceCompetency) -> list[Artifact]:
    """Собирает материалы кандидата по компетенции (§5.2, шаг 2)."""
    statements = db.scalars(
        select(Statement).where(
            Statement.user_id == user.id, Statement.skill_name.in_(competency.taxonomy_keys)
        )
    )

    artifacts: list[Artifact] = []
    seen: set[int] = set()

    for statement in statements:
        for evidence in statement.evidence:
            if evidence.status == DECLINED or evidence.id in seen:
                continue
            seen.add(evidence.id)

            if evidence.type in (TYPE_FREE_TEXT, TYPE_BLIND_WITNESS, TYPE_PROBE_ANSWER):
                if evidence.raw_text:
                    artifacts.append(
                        Artifact(public_id("ev", evidence.id), "text", evidence.raw_text)
                    )
            elif evidence.type == TYPE_LINK and evidence.url:
                artifacts.append(Artifact(public_id("ev", evidence.id), "source", evidence.url))
            elif evidence.type == TYPE_FILE and evidence.file_name:
                artifacts.append(
                    Artifact(public_id("ev", evidence.id), "source", evidence.file_name)
                )

    return artifacts


def _used_templates(db: Session, user: User, competency_id: str) -> set[str]:
    return set(
        db.scalars(
            select(ProbeQuestion.template_id).where(
                ProbeQuestion.user_id == user.id,
                ProbeQuestion.competency_id == competency_id,
            )
        )
    )


def _create_question(
    db: Session, user: User, competency: ReferenceCompetency, mode: str = MODE_GROUNDED
) -> ProbeQuestion | None:
    generated = generate_question(
        competency.competency_id,
        _artifacts(db, user, competency),
        taxonomy_keys=competency.taxonomy_keys,
        used_template_ids=_used_templates(db, user, competency.competency_id),
        mode=mode,
        competency_name_ru=competency.name_ru,
        target_type=TARGET_WHITE_SPOT,
    )
    if generated is None:
        return None

    question = ProbeQuestion(
        user_id=user.id,
        competency_id=competency.competency_id,
        target_type=TARGET_WHITE_SPOT,
        artifact_evidence_id=(
            parse_id("ev", generated.artifact_evidence_id)
            if generated.artifact_evidence_id
            else None
        ),
        template_id=generated.template_id,
        text_ru=generated.text_ru,
        reason_ru=generated.reason_ru,
        grounded=generated.grounded,
        nda_abstract=generated.nda_abstract,
        expected_terms=",".join(generated.expected_terms),
        follow_up_text=generated.follow_up,
        status="pending",
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return question


# --- сборка ответа API ----------------------------------------------------


def _pending_question(db: Session, user: User) -> ProbeQuestion | None:
    return db.scalar(
        select(ProbeQuestion)
        .where(ProbeQuestion.user_id == user.id, ProbeQuestion.status == "pending")
        .order_by(ProbeQuestion.id.desc())
    )


def _open_follow_up(db: Session, user: User) -> ProbeFollowUp | None:
    return db.scalar(
        select(ProbeFollowUp)
        .where(ProbeFollowUp.user_id == user.id, ProbeFollowUp.answer.is_(None))
        .order_by(ProbeFollowUp.id.desc())
    )


def _question_out(question: ProbeQuestion) -> dict:
    competency = _competency_by_id(question.competency_id)
    return {
        "id": public_id("q", question.id),
        "competency_id": question.competency_id,
        "competency_name_ru": competency.name_ru if competency else question.competency_id,
        "target_type": question.target_type,
        "template_id": question.template_id,
        "text_ru": question.text_ru,
        "reason_ru": question.reason_ru,
        "grounded": question.grounded,
        "nda_abstract": question.nda_abstract,
        "artifact_evidence_id": (
            public_id("ev", question.artifact_evidence_id)
            if question.artifact_evidence_id
            else None
        ),
        "answer_format": FREE_TEXT,
        "status": question.status,
        "status_ru": STATUS_RU.get(question.status, question.status),
        "created_at": question.created_at,
    }


def _state(db: Session, user: User) -> ProbeOut:
    spots = _white_spots(db, user)
    _retire_stale(db, user, spots)

    question = _pending_question(db, user)
    follow_up = _open_follow_up(db, user)

    counts = {
        name: len(
            list(
                db.scalars(
                    select(ProbeQuestion).where(
                        ProbeQuestion.user_id == user.id, ProbeQuestion.status == name
                    )
                )
            )
        )
        for name in ("answered", "skipped", "declined_nda")
    }

    has_roles = bool(list(db.scalars(select(ProfRole).where(ProfRole.user_id == user.id))))
    reason = None
    if not question and not follow_up:
        if not has_roles:
            reason = NO_ROLE
        elif not spots:
            reason = NO_GAPS

    follow_up_out = None
    if follow_up is not None:
        parent_answer = db.get(ProbeAnswer, follow_up.answer_id)
        follow_up_out = {
            "id": public_id("fu", follow_up.id),
            "question_id": public_id("q", parent_answer.question_id),
            "trigger_reason": follow_up.trigger_reason,
            "text_ru": follow_up.text_ru,
            "reason_ru": follow_up.reason_ru,
            "answer": follow_up.answer,
        }

    return ProbeOut.model_validate(
        {
            "available": bool(question or follow_up or spots),
            "unavailable_reason": reason,
            "question": _question_out(question) if question else None,
            "follow_up": follow_up_out,
            "next_target": (
                {
                    "competency_id": spots[0].competency_id,
                    "name_ru": spots[0].name_ru,
                    "weight": spots[0].weight,
                    "target_type": TARGET_WHITE_SPOT,
                }
                if spots
                else None
            ),
            "answered_count": counts["answered"],
            "skipped_count": counts["skipped"],
            "declined_count": counts["declined_nda"],
            "answer_format": FREE_TEXT,
            "keystroke_capture": settings.keystroke_capture_enabled,
            "feedback_reasons": [
                {"value": value, "label": label} for value, label in FEEDBACK_REASONS
            ],
        }
    )


def _get_question(db: Session, user: User, question_id: str) -> ProbeQuestion:
    question = db.get(ProbeQuestion, parse_id("q", question_id))
    if question is None or question.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вопрос не найден.")
    return question


# --- эндпоинты ------------------------------------------------------------


@router.get("", response_model=ProbeOut)
def read_probe(user: User = Depends(current_user), db: Session = Depends(get_db)) -> ProbeOut:
    return _state(db, user)


@router.get("/history", response_model=list[HistoryOut])
def read_history(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[HistoryOut]:
    """История вопросов (FR4.4).

    Кандидат в любой момент может посмотреть, что у него спрашивали и почему -
    не только в момент ответа.
    """
    questions = db.scalars(
        select(ProbeQuestion)
        .where(ProbeQuestion.user_id == user.id)
        .order_by(ProbeQuestion.id.desc())
    )

    history: list[dict] = []
    for question in questions:
        answer = db.scalar(select(ProbeAnswer).where(ProbeAnswer.question_id == question.id))
        follow_ups = (
            list(
                db.scalars(
                    select(ProbeFollowUp).where(ProbeFollowUp.answer_id == answer.id)
                )
            )
            if answer
            else []
        )

        history.append(
            {
                **_question_out(question),
                "answer_text": answer.text if answer else None,
                "understanding_signal": answer.understanding_signal if answer else False,
                "new_competency_signal": answer.new_competency_signal if answer else False,
                "declined": is_declined(
                    db, user, target_type=TARGET_QUESTION, target_id=question.id
                ),
                "follow_ups": [
                    {
                        "id": public_id("fu", item.id),
                        "question_id": public_id("q", question.id),
                        "trigger_reason": item.trigger_reason,
                        "text_ru": item.text_ru,
                        "reason_ru": item.reason_ru,
                        "answer": item.answer,
                    }
                    for item in follow_ups
                ],
            }
        )

    return [HistoryOut.model_validate(item) for item in history]


@router.post("/next", response_model=ProbeOut)
def next_question(
    data: NextIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ProbeOut:
    """Готовит вопрос по самому весомому белому пятну или по выбранному."""
    spots = _white_spots(db, user)
    _retire_stale(db, user, spots)

    if not spots:
        return _state(db, user)

    if data.competency_id:
        competency = next((c for c in spots if c.competency_id == data.competency_id), None)
        if competency is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Эта компетенция уже подтверждена — вопросы по ней не задаются.",
            )
    else:
        competency = spots[0]

    existing = _pending_question(db, user)
    if existing is not None:
        if existing.competency_id == competency.competency_id:
            return _state(db, user)
        # Одновременно висит один вопрос: прежний снимаем без последствий.
        existing.status = "retired"
        db.commit()

    if _create_question(db, user, competency) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, NO_TEMPLATE)

    return _state(db, user)


@router.post("/questions/{question_id}/answer", response_model=ProbeOut)
def answer_question(
    question_id: str,
    data: AnswerIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProbeOut:
    """Принимает ответ в свободной форме и разводит два сигнала (§5.6)."""
    question = _get_question(db, user, question_id)
    if question.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "На этот вопрос уже ответили.")

    answer = ProbeAnswer(
        user_id=user.id,
        question_id=question.id,
        text=data.text,
        format=FREE_TEXT,
        typed_duration_ms=data.typed_duration_ms,
        paste_attempts_blocked=data.paste_attempts_blocked,
        # Метаданные набора сохраняются только при явно включённом флаге.
        keystroke_meta=data.keystroke_meta if settings.keystroke_capture_enabled else None,
    )
    db.add(answer)
    question.status = "answered"
    db.flush()

    expected_terms = _expected_terms(question)
    reason = follow_up_reason(data.text, expected_terms)

    if reason is not None:
        # Ответ слишком общий: пока это не подтверждение, а повод уточнить.
        competency = _competency_by_id(question.competency_id)
        db.add(
            ProbeFollowUp(
                user_id=user.id,
                answer_id=answer.id,
                trigger_reason=reason,
                text_ru=question.follow_up_text,
                reason_ru=build_follow_up_reason(
                    competency.name_ru if competency else question.competency_id, reason
                ),
            )
        )
    else:
        _finalize(db, user, question, answer, data.text)

    db.commit()
    return _state(db, user)


def _expected_terms(question: ProbeQuestion) -> tuple[str, ...]:
    return tuple(term for term in question.expected_terms.split(",") if term)


def _finalize(
    db: Session, user: User, question: ProbeQuestion, answer: ProbeAnswer, full_text: str
) -> None:
    """Ответ прошёл проверку на конкретность - только теперь он что-то значит.

    Таблица §5.6: подтверждение понимания и открытие незаявленной компетенции -
    два независимых сигнала. Ответ, который не прошёл Semantic Depth даже после
    уточнения, не даёт ни одного из них и при этом ничего не отнимает.
    """
    answer.understanding_signal = True

    competency = _competency_by_id(question.competency_id)
    evidence = Evidence(
        user_id=user.id, type=TYPE_PROBE_ANSWER, raw_text=full_text, status=PENDING
    )
    db.add(evidence)
    db.flush()
    answer.evidence_id = evidence.id

    primary_key = competency.taxonomy_keys[0]
    evidence.statements.append(
        _ensure_statement(
            db,
            user,
            key=primary_key,
            ru=BY_KEY[primary_key].ru,
            category=BY_KEY[primary_key].category,
            source_of_claim="probe",
        )
    )

    # Незаявленная компетенция, всплывшая под живым вопросом (FR6.3).
    known = set(db.scalars(select(Statement.skill_name).where(Statement.user_id == user.id)))
    probed = set(competency.taxonomy_keys)
    revealed = [
        item
        for item in parse_free_text(full_text)
        if item.skill_name not in probed and item.skill_name not in known
    ]

    for item in revealed:
        evidence.statements.append(
            _ensure_statement(
                db,
                user,
                key=item.skill_name,
                ru=item.skill_name_ru,
                category=item.category,
                source_of_claim="probe",
            )
        )

    answer.new_competency_signal = bool(revealed)


@router.post("/follow-ups/{follow_up_id}/answer", response_model=ProbeOut)
def answer_follow_up(
    follow_up_id: str,
    data: FollowUpAnswerIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProbeOut:
    """Ответ на уточняющий вопрос - вторая и последняя попытка."""
    follow_up = db.get(ProbeFollowUp, parse_id("fu", follow_up_id))
    if follow_up is None or follow_up.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Уточняющий вопрос не найден.")
    if follow_up.answer is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "На уточнение уже ответили.")

    follow_up.answer = data.text

    answer = db.get(ProbeAnswer, follow_up.answer_id)
    question = db.get(ProbeQuestion, answer.question_id)

    # Оцениваем только то, что написал кандидат: текст самого уточняющего
    # вопроса иначе засчитывался бы ему как конкретика.
    candidate_text = f"{answer.text}\n{data.text}"
    full_text = f"{answer.text}\n\n{follow_up.text_ru}\n{data.text}"

    if understanding_signal(candidate_text, _expected_terms(question)):
        _finalize(db, user, question, answer, full_text)
    # Иначе не происходит ничего: ни доказательства, ни штрафа (§5.6, строка 3).

    db.commit()
    return _state(db, user)


@router.post("/questions/{question_id}/skip", response_model=ProbeOut)
def skip_question(
    question_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ProbeOut:
    """Пропуск не создаёт ничего и ничего не отнимает (FR6.4)."""
    question = _get_question(db, user, question_id)
    if question.status == "pending":
        question.status = "skipped"
        db.commit()
    return _state(db, user)


@router.post("/questions/{question_id}/decline", response_model=ProbeOut)
def decline_question(
    question_id: str,
    data: DeclineIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProbeOut:
    """«Это касается NDA» (US5).

    Отказ пишется тем же механизмом, что и в модуле 2 - меняется только тип
    объекта. Взамен предлагается тот же предмет проверки без привязки к
    закрытому материалу; отказ от переформулировки - обычный пропуск.
    """
    question = _get_question(db, user, question_id)
    if question.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Этот вопрос уже закрыт.")

    record_decline(
        db, user, target_type=TARGET_QUESTION, target_id=question.id, reason=data.reason
    )
    question.status = "declined_nda"

    # Дальше дело ведёт модуль 5: он показывает, что мы не спрашиваем никогда,
    # и даёт выбрать способ подтверждения - структурные вопросы или зеркальную
    # задачу. Своей переформулировки у модуля 4 больше нет (§4.1 модуля 5).
    open_case(
        db,
        user,
        competency_id=question.competency_id,
        origin="probe",
        source_evidence_id=question.artifact_evidence_id,
    )
    db.commit()
    return _state(db, user)


@router.delete("/questions/{question_id}/decline", response_model=ProbeOut)
def revoke_question_decline(
    question_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ProbeOut:
    """Отказ обратим - ровно как в модуле 2 (FR5.4)."""
    question = _get_question(db, user, question_id)
    revoke_declines(db, user, target_type=TARGET_QUESTION, target_id=question.id)
    if question.status == "declined_nda":
        question.status = "skipped"
    db.commit()
    return _state(db, user)


@router.post("/questions/{question_id}/feedback", response_model=ProbeOut)
def report_question(
    question_id: str,
    data: FeedbackIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProbeOut:
    """«Вопрос не подходит»: жалоба сохраняется, вопрос заменяется (§4.5)."""
    if data.reason not in REASON_VALUES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестная причина.")

    question = _get_question(db, user, question_id)
    db.add(
        ProbeFeedback(
            user_id=user.id,
            question_id=question.id,
            template_id=question.template_id,
            reason=data.reason,
            comment=data.comment,
        )
    )
    question.status = "flagged_bad"
    db.commit()

    # Кандидат не должен остаться с пустым экраном из-за плохого вопроса.
    competency = next(
        (c for c in _white_spots(db, user) if c.competency_id == question.competency_id), None
    )
    if competency is not None:
        _create_question(db, user, competency)

    return _state(db, user)
