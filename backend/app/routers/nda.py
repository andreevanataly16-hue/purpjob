"""Модуль 5: NDA и альтернативная верификация.

Отсутствие публичного следа не должно означать невозможность построить
доверие. Здесь два способа подтвердить компетенцию, не показывая ничего
закрытого: структурное описание логики (Метод Слепого свидетеля) и зеркальная
задача - абстрактная схема с похожими вводными.

Ни один путь в этом модуле не просит файл, название клиента или точные
коммерческие цифры. Это ограничение содержания заготовок и сценариев, оно
проверяется при импорте библиотек и тестами, а не держится на дисциплине.

Отказ - от способа или от всех сразу - не отнимает ничего: компетенция просто
остаётся неподтверждённой, как любой другой пробел.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.declines import TARGET_NDACASE, is_declined, record_decline, revoke_declines
from app.enrichment import PENDING, TYPE_BLIND_WITNESS, TYPE_MIRROR_TASK
from app.models import (
    Evidence,
    NDABlindWitnessQuestion,
    NDACase,
    NDAMethodSwitch,
    NDAMirrorSolution,
    Statement,
    User,
)
from app.probe import (
    MODE_BLIND_WITNESS,
    build_follow_up_reason,
    follow_up_reason,
    generate_question,
    mirror_task_scenario,
    understanding_signal,
)
from app.reference import ReferenceCompetency, get_profile
from app.routers.auth import current_user
from app.routers.profile import _ensure_statement, parse_id, public_id
from app.schemas_nda import (
    BlindWitnessAnswerIn,
    CaseIn,
    DeclineIn,
    MethodIn,
    MirrorSolutionIn,
    NDAOut,
)
from app.taxonomy import BY_KEY

router = APIRouter(prefix="/api/nda", tags=["nda"])

BLIND_WITNESS = "blind_witness"
MIRROR_TASK = "mirror_task"

STATUS_RU = {
    "method_selection": "Выбор способа",
    "in_progress": "В работе",
    "confirmed": "Подтверждено",
    "declined_all": "Кандидат отказался от всех способов",
}

# §3 FRD: текст согласован с продуктом и ждёт юридической проверки. Пометка
# об этом остаётся видимой в интерфейсе, а не «теряется» по дороге.
DISCLAIMER = {
    "intro_ru": (
        "Вы можете поделиться с нами как любым проектом из своего портфолио, так и "
        "написать о проекте под NDA, не нарушая ваше соглашение."
    ),
    "allowed_ru": [
        "общая логика и архитектура решения",
        "используемые технологии и инструменты",
        "ваша личная роль и зона ответственности",
    ],
    "never_asked_ru": [
        "код",
        "точные бизнес-показатели",
        "имена клиентов",
        "внутренние документы компании",
    ],
    "legal_review_note_ru": "Формулировка требует юридической проверки.",
}

MIRROR_FRAMING = (
    "Это не замена реальному опыту, а дополнительное подтверждение того, что вы способны "
    "воспроизвести профессиональную логику — не очередное тестовое задание."
)

METHOD_LABELS = {
    BLIND_WITNESS: (
        "Метод Слепого свидетеля",
        "Несколько вопросов про структуру вашего решения: узлы, границы, критические точки. "
        "Ни файла, ни названий.",
    ),
    MIRROR_TASK: (
        "Зеркальная задача",
        "Абстрактная схема с похожими вводными: расставляете узлы и объясняете логику. "
        "Ваш проект в ней не участвует.",
    ),
}

NO_SCENARIO = "Для этой компетенции сценария пока нет — доступен Метод Слепого свидетеля."


# --- вспомогательное ------------------------------------------------------


def _competency(competency_id: str) -> ReferenceCompetency | None:
    for level in ("Middle", "Senior"):
        for item in get_profile(level).competencies:
            if item.competency_id == competency_id:
                return item
    return None


def _get_case(db: Session, user: User, case_id: str) -> NDACase:
    case = db.get(NDACase, parse_id("nda", case_id))
    if case is None or case.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Случай не найден.")
    return case


def _require_ack(case: NDACase) -> None:
    """FR1.1: без подтверждённого дисклеймера дальше выбора метода не идём."""
    if case.disclaimer_ack_at is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Сначала прочитайте, что мы спрашиваем, а что не спрашиваем никогда.",
        )


def _methods_for(competency_id: str) -> list[dict]:
    """Оба способа всегда видны, но недоступное честно помечено (FR2.1, FR4.1)."""
    has_scenario = mirror_task_scenario(competency_id) is not None
    result = []
    for value in (BLIND_WITNESS, MIRROR_TASK):
        label, description = METHOD_LABELS[value]
        available = value == BLIND_WITNESS or has_scenario
        result.append(
            {
                "value": value,
                "label_ru": label,
                "description_ru": description,
                "available": available,
                "unavailable_reason_ru": None if available else NO_SCENARIO,
            }
        )
    return result


def _suggested_method(competency_id: str) -> str:
    """Зеркальная задача - если сценарий есть; иначе Слепой свидетель.

    Это подсказка, а не предписание: оба способа показываются как равные.
    """
    return MIRROR_TASK if mirror_task_scenario(competency_id) else BLIND_WITNESS


# --- сериализация ---------------------------------------------------------


def _blind_witness_out(db: Session, case: NDACase) -> list[dict]:
    questions = db.scalars(
        select(NDABlindWitnessQuestion)
        .where(NDABlindWitnessQuestion.case_id == case.id)
        .order_by(NDABlindWitnessQuestion.position)
    )
    return [
        {
            "id": public_id("bwq", item.id),
            "position": item.position,
            "prompt_ru": item.prompt_ru,
            "reason_ru": item.reason_ru,
            "answer": item.answer,
            "follow_up_ru": item.follow_up_ru,
            "follow_up_reason_ru": item.follow_up_reason_ru,
            "follow_up_answer": item.follow_up_answer,
        }
        for item in questions
    ]


def _mirror_out(db: Session, case: NDACase) -> dict | None:
    solution = db.scalar(select(NDAMirrorSolution).where(NDAMirrorSolution.case_id == case.id))
    if solution is None:
        return None

    from app.mirror_tasks import BY_ID

    scenario = BY_ID[solution.scenario_id]
    return {
        "scenario": {
            "id": scenario.id,
            "title_ru": scenario.title_ru,
            "instructions_ru": scenario.instructions_ru,
            # Оговорка о позиционировании показывается всегда (FR2.4).
            "framing_ru": MIRROR_FRAMING,
            "nodes": [{"id": node.id, "label_ru": node.label_ru} for node in scenario.nodes],
        },
        "node_arrangement": json.loads(solution.node_arrangement or "[]"),
        "logic_explanation": solution.logic_explanation,
        "follow_up_ru": solution.follow_up_ru,
        "follow_up_reason_ru": solution.follow_up_reason_ru,
        "follow_up_answer": solution.follow_up_answer,
        "status": solution.status,
    }


def _case_out(db: Session, user: User, case: NDACase) -> dict:
    competency = _competency(case.competency_id)
    switches = len(
        list(db.scalars(select(NDAMethodSwitch).where(NDAMethodSwitch.case_id == case.id)))
    )
    return {
        "id": public_id("nda", case.id),
        "competency_id": case.competency_id,
        "competency_name_ru": competency.name_ru if competency else case.competency_id,
        "origin": case.origin,
        "status": case.status,
        "status_ru": STATUS_RU.get(case.status, case.status),
        "suggested_method": case.suggested_method,
        "chosen_method": case.chosen_method,
        "methods": _methods_for(case.competency_id),
        "disclaimer_acknowledged": case.disclaimer_ack_at is not None,
        "switch_count": switches,
        "blind_witness": _blind_witness_out(db, case),
        "mirror_task": _mirror_out(db, case),
        "created_at": case.created_at,
    }


def _state(db: Session, user: User) -> NDAOut:
    cases = list(
        db.scalars(select(NDACase).where(NDACase.user_id == user.id).order_by(NDACase.id))
    )
    serialized = [_case_out(db, user, case) for case in cases]

    active = next(
        (item for item in reversed(serialized) if item["status"] in ("method_selection", "in_progress")),
        None,
    )
    return NDAOut.model_validate(
        {
            "disclaimer": DISCLAIMER,
            "cases": serialized,
            "active_case_id": active["id"] if active else None,
        }
    )


# --- создание случая ------------------------------------------------------


def open_case(
    db: Session,
    user: User,
    *,
    competency_id: str,
    origin: str,
    statement_id: int | None = None,
    source_evidence_id: int | None = None,
) -> NDACase:
    """Точка входа и для модуля 4, и для белых пятен модуля 3.

    Если случай по этой компетенции уже открыт, возвращаем его: плодить
    дубликаты по одному и тому же пробелу незачем.
    """
    existing = db.scalar(
        select(NDACase).where(
            NDACase.user_id == user.id,
            NDACase.competency_id == competency_id,
            NDACase.status.in_(("method_selection", "in_progress")),
        )
    )
    if existing is not None:
        return existing

    case = NDACase(
        user_id=user.id,
        competency_id=competency_id,
        statement_id=statement_id,
        source_evidence_id=source_evidence_id,
        origin=origin,
        suggested_method=_suggested_method(competency_id),
        status="method_selection",
    )
    db.add(case)
    db.flush()
    return case


# --- эндпоинты ------------------------------------------------------------


@router.get("", response_model=NDAOut)
def read_nda(user: User = Depends(current_user), db: Session = Depends(get_db)) -> NDAOut:
    return _state(db, user)


@router.post("/cases", response_model=NDAOut, status_code=status.HTTP_201_CREATED)
def create_case(
    data: CaseIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> NDAOut:
    if _competency(data.competency_id) is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Такой компетенции нет в эталонном профиле."
        )

    statement_id = None
    if data.statement_id:
        statement = db.get(Statement, parse_id("stmt", data.statement_id))
        if statement is None or statement.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Компетенция не найдена.")
        statement_id = statement.id

    open_case(
        db, user, competency_id=data.competency_id, origin="white_spot", statement_id=statement_id
    )
    db.commit()
    return _state(db, user)


@router.post("/cases/{case_id}/acknowledge", response_model=NDAOut)
def acknowledge(
    case_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> NDAOut:
    """Кандидат прочитал, что у него не спросят никогда (FR1.1)."""
    from app.models import utcnow

    case = _get_case(db, user, case_id)
    if case.disclaimer_ack_at is None:
        case.disclaimer_ack_at = utcnow()
        db.commit()
    return _state(db, user)


# --- выбор способа --------------------------------------------------------


@router.post("/cases/{case_id}/method", response_model=NDAOut)
def choose_method(
    case_id: str,
    data: MethodIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> NDAOut:
    """Выбор или смена способа. Причину не спрашиваем и спрашивать не будем."""
    case = _get_case(db, user, case_id)
    _require_ack(case)

    if data.method not in (BLIND_WITNESS, MIRROR_TASK):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный способ подтверждения.")

    if data.method == MIRROR_TASK and mirror_task_scenario(case.competency_id) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, NO_SCENARIO)

    if case.chosen_method != data.method:
        db.add(
            NDAMethodSwitch(
                user_id=user.id,
                case_id=case.id,
                from_method=case.chosen_method,
                to_method=data.method,
            )
        )

    case.chosen_method = data.method
    case.status = "in_progress"

    # Отказ от всех способов снимается сам, если кандидат вернулся и выбрал.
    revoke_declines(db, user, target_type=TARGET_NDACASE, target_id=case.id)

    if data.method == BLIND_WITNESS:
        _ensure_blind_witness(db, user, case)
    else:
        _ensure_mirror_task(db, user, case)

    db.commit()
    return _state(db, user)


def _ensure_blind_witness(db: Session, user: User, case: NDACase) -> None:
    """Готовит вопросы Слепого свидетеля: структура плюс логика решений."""
    existing = list(
        db.scalars(
            select(NDABlindWitnessQuestion).where(NDABlindWitnessQuestion.case_id == case.id)
        )
    )
    if existing:
        return

    competency = _competency(case.competency_id)
    modes = (MODE_BLIND_WITNESS, "ndaAbstract")

    for position, mode in enumerate(modes, start=1):
        generated = generate_question(
            case.competency_id,
            [],
            taxonomy_keys=competency.taxonomy_keys if competency else (),
            mode=mode,
            competency_name_ru=competency.name_ru if competency else case.competency_id,
        )
        if generated is None:
            continue
        db.add(
            NDABlindWitnessQuestion(
                user_id=user.id,
                case_id=case.id,
                position=position,
                template_id=generated.template_id,
                prompt_ru=generated.text_ru,
                reason_ru=generated.reason_ru,
                expected_terms=",".join(generated.expected_terms),
            )
        )


def _ensure_mirror_task(db: Session, user: User, case: NDACase) -> None:
    existing = db.scalar(select(NDAMirrorSolution).where(NDAMirrorSolution.case_id == case.id))
    if existing is not None:
        return

    scenario = mirror_task_scenario(case.competency_id)
    if scenario is None:
        raise HTTPException(status.HTTP_409_CONFLICT, NO_SCENARIO)

    db.add(
        NDAMirrorSolution(
            user_id=user.id, case_id=case.id, scenario_id=scenario.id, status="pending"
        )
    )


# --- Метод Слепого свидетеля ---------------------------------------------


@router.post("/questions/{question_id}/answer", response_model=NDAOut)
def answer_blind_witness(
    question_id: str,
    data: BlindWitnessAnswerIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> NDAOut:
    """Ответ на структурный вопрос. Слишком общий ответ не отвергается - на
    него задаётся одно уточнение, как в модуле 4 (FR3.3)."""
    question = db.get(NDABlindWitnessQuestion, parse_id("bwq", question_id))
    if question is None or question.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вопрос не найден.")

    case = db.get(NDACase, question.case_id)
    _require_ack(case)

    terms = tuple(term for term in question.expected_terms.split(",") if term)

    if question.answer is None:
        question.answer = data.text
        reason = follow_up_reason(data.text, terms)
        if reason is not None:
            competency = _competency(case.competency_id)
            question.follow_up_ru = (
                "Уточните структуру: какие именно узлы и почему вы считаете их критическими?"
            )
            question.follow_up_reason_ru = build_follow_up_reason(
                competency.name_ru if competency else case.competency_id, reason
            )
    elif question.follow_up_ru is not None and question.follow_up_answer is None:
        question.follow_up_answer = data.text
    else:
        raise HTTPException(status.HTTP_409_CONFLICT, "На этот вопрос уже ответили.")

    _finalize_blind_witness(db, user, case)
    db.commit()
    return _state(db, user)


def _answer_is_complete(question: NDABlindWitnessQuestion) -> bool:
    if question.answer is None:
        return False
    if question.follow_up_ru is not None and question.follow_up_answer is None:
        return False
    return True


def _finalize_blind_witness(db: Session, user: User, case: NDACase) -> None:
    """Когда на все вопросы отвечено - собираем доказательство.

    Доказательство появляется только если в ответах есть что проверять: общая
    фраза даже после уточнения компетенцию не подтверждает, но и не наказывает.
    """
    questions = list(
        db.scalars(
            select(NDABlindWitnessQuestion)
            .where(NDABlindWitnessQuestion.case_id == case.id)
            .order_by(NDABlindWitnessQuestion.position)
        )
    )
    if not questions or not all(_answer_is_complete(q) for q in questions):
        return

    parts: list[str] = []
    candidate_text: list[str] = []
    for question in questions:
        parts.append(f"{question.prompt_ru}\n{question.answer}")
        candidate_text.append(question.answer or "")
        if question.follow_up_answer:
            parts.append(f"{question.follow_up_ru}\n{question.follow_up_answer}")
            candidate_text.append(question.follow_up_answer)

    if not understanding_signal("\n".join(candidate_text), ()):
        return

    _attach_evidence(db, user, case, TYPE_BLIND_WITNESS, "\n\n".join(parts))
    case.status = "confirmed"


# --- зеркальная задача ----------------------------------------------------


@router.post("/cases/{case_id}/mirror-task", response_model=NDAOut)
def submit_mirror_task(
    case_id: str,
    data: MirrorSolutionIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> NDAOut:
    """Решение зеркальной задачи: расстановка узлов плюс объяснение логики."""
    case = _get_case(db, user, case_id)
    _require_ack(case)

    solution = db.scalar(select(NDAMirrorSolution).where(NDAMirrorSolution.case_id == case.id))
    if solution is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Зеркальная задача по этому случаю не начата.")

    from app.mirror_tasks import BY_ID

    scenario = BY_ID[solution.scenario_id]
    known_nodes = {node.id for node in scenario.nodes}
    unknown = [item.node_id for item in data.node_arrangement if item.node_id not in known_nodes]
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "В схеме есть неизвестные узлы.")

    if solution.status == "submitted" and solution.follow_up_ru is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Решение уже отправлено.")

    if solution.follow_up_ru is not None and solution.follow_up_answer is None:
        solution.follow_up_answer = data.logic_explanation
    else:
        solution.node_arrangement = json.dumps(
            [item.model_dump() for item in data.node_arrangement], ensure_ascii=False
        )
        solution.logic_explanation = data.logic_explanation
        solution.status = "submitted"

        reason = follow_up_reason(data.logic_explanation, ())
        if reason is not None:
            competency = _competency(case.competency_id)
            solution.follow_up_ru = (
                "Что в вашей расстановке главное: почему узлы стоят именно в таком порядке "
                "и что сломается, если поменять их местами?"
            )
            solution.follow_up_reason_ru = build_follow_up_reason(
                competency.name_ru if competency else case.competency_id, reason
            )

    explanation = " ".join(
        part for part in (solution.logic_explanation, solution.follow_up_answer) if part
    )
    ready = solution.follow_up_ru is None or solution.follow_up_answer is not None

    if ready and understanding_signal(explanation, ()):
        arrangement = json.loads(solution.node_arrangement or "[]")
        placed = ", ".join(
            f"{item['order']}. {item['node_id']}"
            + (f" — {item['role_ru']}" if item.get("role_ru") else "")
            for item in sorted(arrangement, key=lambda i: i["order"])
        )
        _attach_evidence(
            db,
            user,
            case,
            TYPE_MIRROR_TASK,
            f"Сценарий: {scenario.title_ru}\nСхема: {placed}\n\n{explanation}",
        )
        case.status = "confirmed"

    db.commit()
    return _state(db, user)


# --- общее для обоих способов --------------------------------------------


def _attach_evidence(
    db: Session, user: User, case: NDACase, evidence_type: str, text: str
) -> Evidence:
    """Результат обоих методов - обычное доказательство модуля 2.

    Единственное отличие от любого другого источника - пометка nda: артефакт
    не раскрывался. Меньшего веса у него нет.
    """
    competency = _competency(case.competency_id)
    evidence = Evidence(
        user_id=user.id, type=evidence_type, raw_text=text, nda=True, status=PENDING
    )
    db.add(evidence)

    if case.statement_id is not None:
        statement = db.get(Statement, case.statement_id)
    else:
        key = competency.taxonomy_keys[0]
        statement = _ensure_statement(
            db,
            user,
            key=key,
            ru=BY_KEY[key].ru,
            category=BY_KEY[key].category,
            source_of_claim="nda_alternative",
        )
        case.statement_id = statement.id

    evidence.statements.append(statement)
    return evidence


@router.post("/cases/{case_id}/decline", response_model=NDAOut)
def decline_all(
    case_id: str,
    data: DeclineIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> NDAOut:
    """Отказ от всех способов (FR4.4, FR4.5).

    Тот же механизм отказа, что в модулях 2 и 4 - меняется только тип объекта.
    Компетенция остаётся в прежнем статусе, ничего не отнимается, вернуться
    можно в любой момент.
    """
    case = _get_case(db, user, case_id)
    record_decline(
        db, user, target_type=TARGET_NDACASE, target_id=case.id, reason=data.reason
    )
    case.status = "declined_all"
    db.commit()
    return _state(db, user)


@router.delete("/cases/{case_id}/decline", response_model=NDAOut)
def revoke_case_decline(
    case_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> NDAOut:
    """Отказ обратим: кандидат вернулся и хочет попробовать (FR4.4)."""
    case = _get_case(db, user, case_id)
    revoke_declines(db, user, target_type=TARGET_NDACASE, target_id=case.id)
    if case.status == "declined_all":
        case.status = "in_progress" if case.chosen_method else "method_selection"
    db.commit()
    return _state(db, user)


def case_is_declined(db: Session, user: User, case: NDACase) -> bool:
    return is_declined(db, user, target_type=TARGET_NDACASE, target_id=case.id)
