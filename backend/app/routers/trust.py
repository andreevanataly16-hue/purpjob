"""Модуль 6: Trust Score.

Балл собирается из того, что уже произошло в других модулях: как отвечал
кандидат вживую (модуль 4), чем подтверждал закрытый опыт (модуль 5), какие
доказательства лежат в профиле (модуль 2) и не спорят ли его собственные
сведения друг с другом (локальные проверки этого модуля).

Наружу этот модуль не ходит вообще: все проверки - по данным, которые кандидат
сам и принёс. Ни одно действие кандидата не может уменьшить балл.
"""

from dataclasses import replace
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import overrides
from app.db import get_db
from app.enrichment import (
    DECLINED,
    TYPE_BLIND_WITNESS,
    TYPE_MIRROR_TASK,
    TYPE_PROBE_ANSWER,
)
from app.models import (
    ContradictionCase,
    Evidence,
    ProbeAnswer,
    ProbeFollowUp,
    ProbeQuestion,
    ProfRole,
    Statement,
    TrustFinding,
    User,
)
from app.prof import compute_snapshot
from app.reference import get_profile
from app.routers.auth import current_user
from app.routers.prof import _statement_views
from app.routers.profile import parse_id, public_id
from app.schemas_trust import FindingResponseIn, ResolutionIn, TrustOut
from app.xai import trust_explanation_id
from app.trust import (
    AUTHENTICITY,
    has_measurement,
    COMPONENT_RU,
    CONSISTENCY,
    UNDERSTANDING,
    ComponentScore,
    EvidenceFacts,
    ProbeFacts,
    authenticity,
    consistency,
    find_level_mismatch,
    overall,
    severity_for,
    understanding,
    unlinked_sources,
)

router = APIRouter(prefix="/api/trust", tags=["trust"])

# §1 FRD: формулировка согласована, переписывать её нельзя.
LEGEND_RU = (
    "Trust Score — показатель достоверности профессионального профиля, рассчитанный на "
    "основе анализа цифрового следа и подтверждения ключевых компетенций через контекстные "
    "микро-кейсы. Не заменяет интервью, но даёт дополнительный слой информации о том, что "
    "заявленные навыки подтверждены независимыми источниками."
)

CONFIRMED = "confirmed"
NOT_ME = "not_me_or_outdated"
RESPONSES = (CONFIRMED, NOT_ME)

DELETE_ARTIFACT = "delete_artifact"
EXPLAIN = "explain"
CORRECT_CLAIM = "correct_claim"
RESOLUTION_PATHS = (DELETE_ARTIFACT, EXPLAIN, CORRECT_CLAIM)


# --- сбор входных данных --------------------------------------------------


def _probe_facts(db: Session, user: User) -> list[ProbeFacts]:
    """Что модуль 4 уже посчитал по ответам кандидата - берём как есть."""
    facts: list[ProbeFacts] = []

    answers = db.scalars(select(ProbeAnswer).where(ProbeAnswer.user_id == user.id))
    for answer in answers:
        question = db.get(ProbeQuestion, answer.question_id)
        follow_ups = list(
            db.scalars(select(ProbeFollowUp).where(ProbeFollowUp.answer_id == answer.id))
        )
        facts.append(
            ProbeFacts(
                answer_id=public_id("a", answer.id),
                competency_id=question.competency_id if question else "",
                understanding_signal=answer.understanding_signal,
                paste_attempts_blocked=answer.paste_attempts_blocked,
                had_follow_up=bool(follow_ups),
                resolved_after_follow_up=any(item.answer for item in follow_ups),
            )
        )
    return facts


def _evidence_facts(db: Session, user: User) -> list[EvidenceFacts]:
    items = db.scalars(
        select(Evidence).where(Evidence.user_id == user.id).order_by(Evidence.id)
    )
    return [
        EvidenceFacts(
            id=public_id("ev", item.id),
            type=item.type,
            source_category=item.source_category,
            status=item.status,
            statement_ids=tuple(public_id("stmt", s.id) for s in item.statements),
        )
        for item in items
    ]


# --- локальные проверки непротиворечивости --------------------------------


def _refresh_contradictions(db: Session, user: User) -> None:
    """Ищет нестыковки в данных, которые кандидат принёс сам (§5.1).

    Проверка уровня работает; проверка пересечения дат не реализована - в
    профиле нет периодов работы, их никто не собирает (см. README).
    """
    roles = [role.level for role in db.scalars(select(ProfRole).where(ProfRole.user_id == user.id))]
    if not roles:
        return

    texts: list[tuple[str, str, str]] = []
    statements = db.scalars(select(Statement).where(Statement.user_id == user.id))
    for statement in statements:
        for evidence in statement.evidence:
            if evidence.status == DECLINED or not evidence.raw_text:
                continue
            texts.append((str(statement.id), str(evidence.id), evidence.raw_text))

    known = {
        (case.statement_id, case.evidence_id)
        for case in db.scalars(
            select(ContradictionCase).where(
                ContradictionCase.user_id == user.id,
                ContradictionCase.check_type == "level_mismatch",
            )
        )
    }

    created = False
    for mismatch in find_level_mismatch(roles, texts):
        key = (int(mismatch.statement_id), int(mismatch.evidence_id))
        if key in known:
            continue

        severity = severity_for(len(mismatch.markers))
        db.add(
            ContradictionCase(
                user_id=user.id,
                statement_id=key[0],
                evidence_id=key[1],
                check_type="level_mismatch",
                severity=severity,
                detail_ru=(
                    f"Вы отслеживаете уровень {mismatch.level}, а в описании этого опыта "
                    f"работа выглядит как выполнение чужих поручений "
                    f"({', '.join(mismatch.markers)}). Возможно, описание короче реальности — "
                    "или уровень стоит уточнить."
                ),
                status="open",
                visibility_suspended=severity == "major",
            )
        )
        created = True

    if created:
        db.commit()


# --- находки об атрибуции -------------------------------------------------


def _findings(db: Session, user: User, evidence: list[EvidenceFacts]) -> list[dict]:
    """Источники, про которые непонятно, зачем они в профиле (§4.3).

    Отвеченные находки исчезают: подтверждённая - потому что вопрос закрыт,
    отклонённая - потому что от неё не должно остаться следа.
    """
    answered = {
        finding.evidence_id
        for finding in db.scalars(select(TrustFinding).where(TrustFinding.user_id == user.id))
    }

    result = []
    for item in unlinked_sources(evidence):
        numeric = parse_id("ev", item.id)
        if numeric in answered:
            continue
        stored = db.get(Evidence, numeric)
        source = stored.url or stored.file_name or "источник"
        result.append(
            {
                "id": item.id,
                "finding_text_ru": (
                    f"Мы нашли среди ваших источников {source}, но он не привязан ни к одной "
                    "компетенции — это ваш профессиональный след?"
                ),
                "source_ref": source,
                "candidate_response": None,
            }
        )
    return result


# --- сборка ответа --------------------------------------------------------


def _next_actions(
    db: Session, user: User, components: list[ComponentScore], contradictions: list, findings: list
) -> list[dict]:
    """Следующее лучшее действие: конкретное и с адресом (FR3.1-FR3.3).

    Своей приоритизации у модуля нет: пробелы берутся из белых пятен модуля 3 в
    том же порядке по весу.
    """
    actions: list[dict] = []

    for case in contradictions:
        if case.status != "open":
            continue
        actions.append(
            {
                "component_id": CONSISTENCY,
                "text_ru": "Разберите нестыковку в профиле — это обычная правка, а не разбор полётов.",
                "target_kind": "contradiction",
                "target_id": public_id("cc", case.id),
                "weight": 1.0,
            }
        )

    if findings:
        actions.append(
            {
                "component_id": CONSISTENCY,
                "text_ru": f"Ответьте, ваши ли это источники ({len(findings)}) — на балл это не влияет.",
                "target_kind": "finding",
                "target_id": findings[0]["id"],
                "weight": 0.9,
            }
        )

    roles = list(db.scalars(select(ProfRole).where(ProfRole.user_id == user.id)))
    if roles:
        views = _statement_views(db, user)
        snapshot = compute_snapshot(get_profile(roles[0].level), views)
        by_id = {c["competency_id"]: c for c in snapshot["components"]}
        for competency_id in snapshot["white_spots"][:2]:
            component = by_id[competency_id]
            actions.append(
                {
                    "component_id": UNDERSTANDING,
                    "text_ru": (
                        f"Ответьте на вопрос по компетенции «{component['name_ru']}» — "
                        "это независимое подтверждение, которого сейчас не хватает."
                    ),
                    "target_kind": "probe",
                    "target_id": competency_id,
                    "weight": component["weight"],
                }
            )

    return sorted(actions, key=lambda item: -item["weight"])


def _apply_moderation(
    components: list[ComponentScore], applied: list
) -> tuple[list[ComponentScore], dict[str, object], list[dict]]:
    """Ручные правки модератора поверх посчитанных компонентов (модуль 7).

    Единственный путь, которым балл Trust вообще может измениться помимо
    расчёта, - и он оставляет запись с обязательной причиной. Правило модуля 6
    «действие кандидата не уменьшает балл» этим не нарушается: здесь решает
    человек, письменно и под запись (см. `app/overrides.py`).
    """
    result: list[ComponentScore] = []
    notes: dict[str, object] = {}
    trace: list[dict] = []

    for component in components:
        override = overrides.latest(
            applied, overrides.TARGET_TRUST_COMPONENT, component.component_id
        )
        if override is None or not override.new_value.isdigit():
            result.append(component)
            continue

        new_score = max(0, min(100, int(override.new_value)))
        # Модератор посмотрел и поставил значение - это измерение, пусть и
        # человеческое. Оставить компонент неизмеренным значило бы выкинуть
        # правку из общего балла.
        result.append(replace(component, score=new_score, measured=True))
        notes[component.component_id] = overrides.note_ru(override)
        trace.append(
            {
                "component_id": component.component_id,
                "previous_value": override.previous_value,
                "new_value": override.new_value,
                "rationale_ru": override.rationale_ru,
                "dispute_case_id": public_id("dc", override.dispute_case_id),
                "history_entry_id": (
                    public_id("dh", override.history_entry_id)
                    if override.history_entry_id
                    else None
                ),
                "applied_at": override.applied_at,
            }
        )

    return result, notes, trace


def _state(db: Session, user: User) -> TrustOut:
    _refresh_contradictions(db, user)

    probes = _probe_facts(db, user)
    evidence = _evidence_facts(db, user)
    nda_confirmations = [
        item
        for item in evidence
        if item.type in (TYPE_BLIND_WITNESS, TYPE_MIRROR_TASK) and item.status != DECLINED
    ]

    cases = list(
        db.scalars(
            select(ContradictionCase)
            .where(ContradictionCase.user_id == user.id)
            .order_by(ContradictionCase.id)
        )
    )
    open_cases = [case for case in cases if case.status == "open"]
    resolved_cases = [case for case in cases if case.status == "resolved"]
    findings = _findings(db, user, evidence)

    components = [
        authenticity(probes),
        understanding(probes, nda_confirmations),
        consistency(evidence, len(open_cases), len(resolved_cases), len(findings)),
    ]
    applied = overrides.for_user(db, user)
    components, moderator_notes, moderation_trace = _apply_moderation(components, applied)

    statements = {
        public_id("stmt", item.id): item.skill_name_ru
        for item in db.scalars(select(Statement).where(Statement.user_id == user.id))
    }

    return TrustOut.model_validate(
        {
            "overall_score": overall(components),
            "overall_measured": has_measurement(components),
            "computed_at": datetime.now(timezone.utc),
            # Версия растёт с каждым пересчётом и с каждой ручной правкой
            # (FR5.4 модуля 7): по `moderation_trace` от изменившегося балла
            # можно дойти до записи журнала, которая его изменила.
            "version": 1 + len(probes) + len(evidence) + len(cases) + len(applied),
            "legend_ru": LEGEND_RU,
            "components": [
                {
                    "component_id": item.component_id,
                    "name_ru": COMPONENT_RU[item.component_id],
                    "score": item.score,
                    "measured": item.measured,
                    "explanation_ru": item.explanation_ru,
                    "contributing_evidence_ids": item.contributing_evidence_ids,
                    "notes_ru": item.notes_ru,
                    "explanation_id": trust_explanation_id(item.component_id),
                    "moderator_note_ru": moderator_notes.get(item.component_id),
                }
                for item in components
            ],
            "moderation_trace": moderation_trace,
            "next_actions": _next_actions(db, user, components, cases, findings),
            "findings": findings,
            "contradictions": [
                {
                    "id": public_id("cc", case.id),
                    "check_type": case.check_type,
                    "detected_by": case.detected_by,
                    "severity": case.severity,
                    "detail_ru": case.detail_ru,
                    "statement_id": public_id("stmt", case.statement_id) if case.statement_id else None,
                    "statement_name_ru": statements.get(
                        public_id("stmt", case.statement_id) if case.statement_id else ""
                    ),
                    "evidence_id": public_id("ev", case.evidence_id) if case.evidence_id else None,
                    "resolution_path": case.resolution_path,
                    "explanation_text": case.explanation_text,
                    "corrected_value": case.corrected_value,
                    "status": case.status,
                    "visibility_suspended": case.visibility_suspended,
                    "created_at": case.created_at,
                }
                for case in cases
            ],
        }
    )


# --- эндпоинты ------------------------------------------------------------


@router.get("", response_model=TrustOut)
def read_trust(user: User = Depends(current_user), db: Session = Depends(get_db)) -> TrustOut:
    return _state(db, user)


@router.post("/findings/{finding_id}/respond", response_model=TrustOut)
def respond_to_finding(
    finding_id: str,
    data: FindingResponseIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> TrustOut:
    """Case 1: «это совпадает с вашим профилем?» (FR4.1).

    Отказ не требует причины, ничего не отнимает и не оставляет следа: сам
    источник удаляется, а от находки не остаётся ничего, кроме факта ответа.
    """
    if data.response not in RESPONSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный ответ.")

    evidence = db.get(Evidence, parse_id("ev", finding_id))
    if evidence is None or evidence.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Источник не найден.")

    db.add(
        TrustFinding(
            user_id=user.id,
            evidence_id=evidence.id if data.response == CONFIRMED else None,
            candidate_response=data.response,
        )
    )

    if data.response == NOT_ME:
        # «Не моё» - значит, следа быть не должно вообще: удаляем источник.
        db.delete(evidence)

    db.commit()
    return _state(db, user)


@router.post("/contradictions/{case_id}/resolve", response_model=TrustOut)
def resolve_contradiction(
    case_id: str,
    data: ResolutionIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> TrustOut:
    """Case 2: три пути разбора (FR4.2).

    Ни один из них не наказание: это приведение профиля в порядок, и выбирает
    его кандидат.
    """
    if data.path not in RESOLUTION_PATHS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный способ разбора.")

    case = db.get(ContradictionCase, parse_id("cc", case_id))
    if case is None or case.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Нестыковка не найдена.")

    if data.path == EXPLAIN and not (data.explanation_text or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Напишите, в чём дело.")
    if data.path == CORRECT_CLAIM and not (data.corrected_value or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Укажите, как правильно.")

    if data.path == DELETE_ARTIFACT and case.evidence_id is not None:
        evidence = db.get(Evidence, case.evidence_id)
        if evidence is not None:
            # Кандидат сам убирает свой артефакт - это не системное удаление.
            db.delete(evidence)
        case.evidence_id = None

    case.resolution_path = data.path
    case.explanation_text = data.explanation_text
    case.corrected_value = data.corrected_value
    case.status = "resolved"
    case.visibility_suspended = False

    db.commit()
    return _state(db, user)
