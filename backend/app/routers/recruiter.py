"""Модуль 12: рекрутерская сторона — поиск, карточка, сравнение.

Первый экран продукта, у которого другой читатель. Своего расчёта здесь нет
вообще: PROF.индекс, Trust Score и совпадение считают те же движки, что и для
кандидата. Рекрутер видит ту же структуру, а не «упрощённую версию для
рекрутера», из которой пропали основания.

Три границы приватности, и они разные - смешивать их нельзя:

1. **Видимость.** Скрытый профиль недоступен структурно: набор, с которым
   работает этот модуль, физически не содержит таких записей. Никакого
   «показать скрытых для исследования» здесь нет.
2. **Согласие на раскрытие доказательств.** Оно управляет только глубиной:
   без согласия видны компоненты и их формулировки, но не содержимое самих
   доказательств. Видимость профиля этим не управляется.
3. **Отклонённые находки.** Их не существует нигде - ни при каком согласии и
   ни при какой видимости. Это самое строгое правило из трёх.

БЕЗ ДОСТУПА И БЕЗ РОЛЕЙ. Роль рекрутера здесь - режим экрана, как и роль
модератора в модуле 7. Кто искал и кого смотрел - нигде не фиксируется. До
настоящего разграничения прав и журнала доступа это наружу не выкатывается.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import candidates as pool, growth, reveal, vacancies as library
from app.candidates import SeedCandidate
from app.db import get_db
from app.models import ReturnTrigger, RevealState, User
from app.routers.auth import current_user
from app.schemas_recruiter import CompareOut, CandidateDetailOut, RevealOut, SearchOut
from app.vacancies import CompetencyState

router = APIRouter(prefix="/api/recruiter", tags=["recruiter"])

NOT_PRODUCTION_SAFE_RU = (
    "Режим рекрутера без доступа и без ролей: его может открыть любой вошедший, и нигде не "
    "записывается, кто кого смотрел. Так можно только локально — до настоящего разграничения "
    "прав и журнала доступа это наружу не выкатывается."
)

NOTE_RU = (
    "Здесь видно не «сильный кандидат», а что именно подтверждено и чем. Профили, скрытые "
    "самими кандидатами, в поиск не попадают вообще."
)

NDA_NOTE_RU = "подтверждено через альтернативный метод (NDA)"

SORT_MATCH = "match_score"
SORT_TRUST = "trust_score"
SORT_PROF = "prof_index"
SORT_OPTIONS = (SORT_MATCH, SORT_TRUST, SORT_PROF)


def _state_of(candidate: SeedCandidate) -> CompetencyState:
    """Что кандидат подтвердил — в форме, которую понимает модуль 10."""
    rank = {"not_started": 0, "limited": 1, "medium": 2, "strong": 3}
    views = pool.statement_views(candidate)

    by_competency: dict[str, str] = {}
    for snapshot in pool.prof_snapshots(candidate):
        for component in snapshot["components"]:
            current = by_competency.get(component["competency_id"], "not_started")
            if rank[component["status"]] > rank[current]:
                by_competency[component["competency_id"]] = component["status"]

    return CompetencyState(
        by_competency=by_competency,
        by_skill={view.skill_name.lower(): view.status for view in views},
    )


def _cluster_scores(candidate: SeedCandidate) -> dict[str, int]:
    from app.reference import get_profile

    views = pool.statement_views(candidate)
    from app.prof import compute_snapshot

    return {
        get_profile(level).id: compute_snapshot(get_profile(level), views)["overall_score"]
        for level in ("Middle", "Senior")
    }


def _match(candidate: SeedCandidate, vacancy: library.Vacancy) -> library.MatchResult:
    """Тот же движок совпадения, что и у кандидата (FR1.2).

    Направление запроса ему безразлично: здесь он вызывается в цикле по пулу,
    там - по ленте вакансий. Это одна и та же операция.
    """
    return library.compute(vacancy, _state_of(candidate), _cluster_scores(candidate))


def _best_prof(candidate: SeedCandidate) -> dict:
    return max(pool.prof_snapshots(candidate), key=lambda item: item["overall_score"])


def _vacancy_or_404(vacancy_id: str) -> library.Vacancy:
    vacancy = library.BY_ID.get(vacancy_id)
    if vacancy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Такой вакансии нет.")
    return vacancy


def _candidate_or_404(db: Session, user: User, candidate_id: str) -> SeedCandidate:
    """Единственный способ достать кандидата в этом модуле.

    Скрытый профиль сюда не доходит: пул его просто не содержит, и ответ
    неотличим от «такого кандидата нет» (FR2.3).
    """
    candidate = pool.find_visible(db, user, candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Такой кандидат не найден.")
    return candidate


# --- поэтапное раскрытие (модуль 13) --------------------------------------


def reveal_state(db: Session, user: User, candidate: SeedCandidate) -> RevealState:
    """Этап, на котором этот рекрутер находится по этому кандидату.

    Кандидат может отказаться от поэтапности целиком - тогда он сразу на
    втором этапе. Это его осознанное решение, выключенное по умолчанию.
    """
    row = db.scalar(
        select(RevealState).where(
            RevealState.recruiter_user_id == user.id,
            RevealState.candidate_id == candidate.id,
        )
    )
    if row is None:
        immediate = _allows_immediate(db, candidate)
        row = RevealState(
            recruiter_user_id=user.id,
            candidate_id=candidate.id,
            current_stage=reveal.STAGE_2 if immediate else reveal.STAGE_1,
            stage2_advanced_at=growth.utcnow() if immediate else None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _allows_immediate(db: Session, candidate: SeedCandidate) -> bool:
    if not candidate.id.startswith(pool.LIVE_PREFIX):
        return False
    from app.models import VisibilityState

    state = db.get(VisibilityState, int(candidate.id.removeprefix(pool.LIVE_PREFIX)))
    return bool(state and state.allow_immediate_identity_reveal)


def _identity(db: Session, user: User, candidate: SeedCandidate) -> reveal.Identity:
    row = reveal_state(db, user, candidate)
    return reveal.identity_for(
        candidate.id, candidate.display_name, candidate.photo_label, row.current_stage
    )


# --- сериализация ---------------------------------------------------------


# Разбор требований приходит из модуля 10 в кандидатском обращении: он писался
# для того, кто читает про себя. Рекрутеру то же самое нужно сказать о третьем
# лице - смысл и факты не меняются, меняется только адресат.
_TO_THIRD_PERSON = (
    ("в вашем профиле", "в профиле кандидата"),
    ("у вас", "у кандидата"),
    ("вашей", "его"),
)


def _third_person(text: str) -> str:
    for candidate_form, recruiter_form in _TO_THIRD_PERSON:
        text = text.replace(candidate_form, recruiter_form)
    return text


def _requirement(item: library.RequirementView, covered: bool) -> dict:
    explanation = _third_person(item.explanation_ru)
    return {
        "requirement_id": item.requirement_id,
        "label_ru": item.label_ru,
        "criticality_ru": library.CRITICALITY_RU[item.criticality],
        "status": item.status,
        # Регистр тот же, что и везде: «требует дополнительной проверки», а не
        # «слабое место» (FR4.2).
        "explanation_ru": explanation
        if covered
        else f"{explanation} Требует дополнительной проверки.",
    }


def _card(candidate: SeedCandidate, result: library.MatchResult, identity: reveal.Identity) -> dict:
    snapshot = _best_prof(candidate)
    return {
        "candidate_id": candidate.id,
        # Имя и фото - единственное, что закрыто на первом этапе (модуль 13).
        "display_name": identity.label,
        "photo_label": identity.photo_label,
        "identity_revealed": identity.identity_revealed,
        "levels": list(candidate.levels),
        "prof_index": snapshot["overall_score"],
        "prof_level": snapshot["level"],
        "trust_score": pool.trust_overall(candidate),
        "match_score": result.overall_match_score,
        "covered_count": len(result.covered),
        "uncovered_count": len(result.uncovered),
        "consent_for_recruiter_view": candidate.consent_for_recruiter_view,
    }


def _detail(
    db: Session, user: User, candidate: SeedCandidate, vacancy: library.Vacancy
) -> dict:
    result = _match(candidate, vacancy)
    snapshot = _best_prof(candidate)
    row = reveal_state(db, user, candidate)
    payload = _card(candidate, result, _identity(db, user, candidate))

    components = pool.trust_components(candidate)
    from app.trust import COMPONENT_RU
    from app.xai import trust_explanation_id

    has_nda = any(
        entry.type in ("blind_witness_answer", "mirror_task_solution")
        for item in candidate.statements
        for entry in item.evidence
    ) or bool(candidate.nda_confirmations)

    payload.update(
        {
            "vacancy_id": vacancy.id,
            "vacancy_title_ru": vacancy.title_ru,
            "current_stage": row.current_stage,
            "stage_note_ru": reveal.STAGE1_NOTE_RU if row.current_stage == reveal.STAGE_1 else "",
            "advance_label_ru": reveal.ADVANCE_LABEL_RU,
            "contact_label_ru": reveal.CONTACT_LABEL_RU,
            "contacts_visible": row.current_stage == reveal.STAGE_3,
            "contact_note_ru": (
                "Контакты открываются только при встречном согласии кандидата — одного вашего "
                "запроса для этого недостаточно."
            ),
            "prof_components": [
                {
                    "competency_id": item["competency_id"],
                    "name_ru": item["name_ru"],
                    "status": item["status"],
                    "reason": _third_person(item["reason"]),
                    "weight": item["weight"],
                    "explanation_id": item.get("explanation_id", ""),
                }
                for item in snapshot["components"]
            ],
            "radar_points": snapshot["radar_points"],
            "trust_components": [
                {
                    "component_id": item.component_id,
                    "name_ru": COMPONENT_RU[item.component_id],
                    "score": item.score,
                    # Голого числа рекрутеру не показывают так же, как и
                    # кандидату (FR3.1).
                    "explanation_ru": _third_person(item.explanation_ru),
                    "explanation_id": trust_explanation_id(item.component_id),
                    "evidence_visible": candidate.consent_for_recruiter_view,
                    "evidence_refs": (
                        item.contributing_evidence_ids
                        if candidate.consent_for_recruiter_view
                        else []
                    ),
                }
                for item in components
            ],
            "consent_note_ru": (
                "Кандидат разрешил смотреть сами доказательства."
                if candidate.consent_for_recruiter_view
                else "Кандидат не открывал сами доказательства — видны выводы и на чём они "
                "основаны, но не содержимое источников."
            ),
            "nda_note_ru": NDA_NOTE_RU if has_nda else None,
            "covered": [_requirement(item, True) for item in result.covered],
            "uncovered": [_requirement(item, False) for item in result.uncovered],
            "unevaluated_clusters": result.unevaluated_clusters,
            "unevaluated_note_ru": (
                "Эта часть требований платформой не оценивалась — эталона роли для неё нет. "
                "«Не оценено» не значит «нет»."
            ),
        }
    )
    return payload


# --- эндпоинты ------------------------------------------------------------


@router.get("/search", response_model=SearchOut)
def search(
    vacancy_id: str,
    min_trust_score: int = Query(default=0, ge=0, le=100),
    level: str | None = None,
    sort_by: str = SORT_MATCH,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SearchOut:
    """FR1.1-FR1.4: ранжированный список вместо стопки резюме.

    Это ручной поиск по уже существующему пулу, а не рассылка: система никого
    ни о чём не уведомляет и ни к кому не обращается от имени рекрутера.
    """
    vacancy = _vacancy_or_404(vacancy_id)
    if sort_by not in SORT_OPTIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный порядок сортировки.")

    rows = []
    for candidate in pool.pool_for(db, user):
        if level and level not in candidate.levels:
            continue
        card = _card(candidate, _match(candidate, vacancy), _identity(db, user, candidate))
        if card["trust_score"] < min_trust_score:
            continue
        rows.append(card)

    key = {SORT_MATCH: "match_score", SORT_TRUST: "trust_score", SORT_PROF: "prof_index"}[sort_by]
    rows.sort(key=lambda item: -item[key])

    return SearchOut.model_validate(
        {
            "note_ru": NOTE_RU,
            "not_production_safe_ru": NOT_PRODUCTION_SAFE_RU,
            "vacancy_id": vacancy.id,
            "vacancy_title_ru": vacancy.title_ru,
            "available_vacancies": [
                {"id": item.id, "title_ru": item.title_ru, "stated_level": item.stated_level}
                for item in library.ALL
            ],
            "sort_by": sort_by,
            "candidates": rows,
            "computed_at": datetime.now(timezone.utc),
        }
    )


@router.get("/candidates/{candidate_id}", response_model=CandidateDetailOut)
def read_candidate(
    candidate_id: str,
    vacancy_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> CandidateDetailOut:
    """FR2.1-FR2.3: то же, что видит о себе кандидат, а не выжимка."""
    candidate = _candidate_or_404(db, user, candidate_id)
    vacancy = _vacancy_or_404(vacancy_id)
    return CandidateDetailOut.model_validate(_detail(db, user, candidate, vacancy))


@router.get("/compare", response_model=CompareOut)
def compare(
    vacancy_id: str,
    ids: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> CompareOut:
    """FR5.1-FR5.3: одна и та же структура на всех, включая разбор требований.

    Сравнение голых чисел вернуло бы ровно ту непрозрачную сортировку, против
    которой построен весь продукт.
    """
    vacancy = _vacancy_or_404(vacancy_id)
    wanted = [item.strip() for item in ids.split(",") if item.strip()]
    if not wanted:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не выбрано ни одного кандидата.")

    # Сравнение тоже начинается с первого этапа: сравнивать несколько
    # обезличенных профилей рядом - ровно тот случай, ради которого модуль 13
    # существует, и обходить его здесь нельзя (FR1.4).
    rows = [
        _detail(db, user, _candidate_or_404(db, user, item), vacancy) for item in wanted
    ]
    return CompareOut.model_validate(
        {
            "vacancy_id": vacancy.id,
            "vacancy_title_ru": vacancy.title_ru,
            "candidates": rows,
        }
    )


# --- этапы раскрытия (модуль 13) ------------------------------------------


def _fire_recruiter_interest(db: Session, candidate: SeedCandidate) -> None:
    """Закрывает повод, отложенный в модуле 8 (FR2.3).

    До появления рекрутерской стороны у `recruiter_interest` не было
    производителя вообще. Теперь он есть - и это первое место в продукте, где
    интерес рекрутера существует как событие.
    """
    if not candidate.id.startswith(pool.LIVE_PREFIX):
        return
    candidate_user_id = int(candidate.id.removeprefix(pool.LIVE_PREFIX))

    existing = db.scalar(
        select(ReturnTrigger).where(
            ReturnTrigger.user_id == candidate_user_id,
            ReturnTrigger.trigger_type == "recruiter_interest",
            ReturnTrigger.related_ref == candidate.id,
        )
    )
    if existing is not None:
        return

    db.add(
        ReturnTrigger(
            user_id=candidate_user_id,
            trigger_type="recruiter_interest",
            related_ref=candidate.id,
        )
    )


@router.post("/candidates/{candidate_id}/reveal", response_model=CandidateDetailOut)
def advance_stage(
    candidate_id: str,
    vacancy_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> CandidateDetailOut:
    """FR2.1-FR2.3: отдельное осознанное действие, а не побочный эффект.

    Именно поэтому это отдельный запрос, а не «раскрылось, когда открыл
    карточку» или «посмотрел дольше N секунд».
    """
    candidate = _candidate_or_404(db, user, candidate_id)
    vacancy = _vacancy_or_404(vacancy_id)
    row = reveal_state(db, user, candidate)

    if row.current_stage == reveal.STAGE_1:
        row.current_stage = reveal.STAGE_2
        row.stage2_advanced_at = growth.utcnow()
        row.advance_trigger = reveal.RECRUITER_MARKED_INTEREST
        _fire_recruiter_interest(db, candidate)
        db.commit()

    return CandidateDetailOut.model_validate(_detail(db, user, candidate, vacancy))


@router.post("/candidates/{candidate_id}/request-contacts", response_model=CandidateDetailOut)
def request_contacts(
    candidate_id: str,
    vacancy_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> CandidateDetailOut:
    """FR2.4: запрос контактов. Сам по себе он ничего не открывает.

    Третий этап наступает только при встречном согласии кандидата - в отличие
    от второго, где хватает решения рекрутера.
    """
    candidate = _candidate_or_404(db, user, candidate_id)
    vacancy = _vacancy_or_404(vacancy_id)
    row = reveal_state(db, user, candidate)

    if row.current_stage == reveal.STAGE_1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Сначала нужно перейти к имени и фотографии.",
        )

    row.contact_requested_at = row.contact_requested_at or growth.utcnow()
    if row.candidate_contact_opt_in and row.current_stage != reveal.STAGE_3:
        row.current_stage = reveal.STAGE_3
        row.stage3_advanced_at = growth.utcnow()
        row.advance_trigger = reveal.MUTUAL_INTEREST_CONFIRMED
    db.commit()

    return CandidateDetailOut.model_validate(_detail(db, user, candidate, vacancy))
