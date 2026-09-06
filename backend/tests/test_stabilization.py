"""Регрессии стабилизационного спринта.

Эти проверки фиксируют не поведение отдельного модуля, а границы, которые
однажды уже поехали и могут поехать снова:

* существование доказательства - не то же самое, что его проверенность;
* непротиворечивость - не количество источников;
* система не заявляет больше, чем измеряет;
* время само по себе не понижает подтверждённый опыт.

Файл отдельный намеренно: это не «тесты модуля N», а тесты того, что модули не
начнут снова обещать друг за друга.
"""

import inspect
from datetime import datetime, timedelta, timezone

from app import growth, trust as trust_logic
from app.db import SessionLocal
from app.enrichment import (
    DECLINED,
    PENDING,
    TYPE_BLIND_WITNESS,
    TYPE_FILE,
    TYPE_FREE_TEXT,
    TYPE_LINK,
    TYPE_MIRROR_TASK,
    TYPE_PROBE_ANSWER,
)
from app.models import CompetencyFreshness, Evidence
from app.trust import (
    AUTHENTICITY,
    CONSISTENCY,
    EvidenceFacts,
    ProbeFacts,
    consistency,
    is_trust_eligible,
    understanding,
)

PROF = "/api/prof"
TRUST = "/api/trust"
GROWTH = "/api/growth"
ROLES = "/api/prof/roles"
PARSE = "/api/profile/parse"
ACCEPT = "/api/profile/statements/accept"
LINK = "/api/profile/evidence/link"
PROFILE = "/api/profile"

CASE_TEXT = (
    "Переписал биллинг с нуля на Python, вынес его в отдельный микросервис. "
    "Под нагрузкой в 3000 rps старая схема не держала, поэтому добавили Redis "
    "и переработали индексы в PostgreSQL."
)


def setup_candidate(client, level="Middle"):
    client.post(ROLES, json={"level": level})
    parsed = client.post(PARSE, json={"raw_text": CASE_TEXT}).json()
    client.post(ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]})


def statement_ids(client):
    return [item["id"] for item in client.get(PROFILE).json()["statements"]]


def evidence(type_=TYPE_LINK, status=PENDING, category="github", statements=("stmt_001",)):
    return EvidenceFacts(
        id="ev_001", type=type_, source_category=category, status=status, statement_ids=statements
    )


def component(payload, component_id):
    return next(c for c in payload["components"] if c["component_id"] == component_id)


# --- 1. Пригодность доказательства для Trust ------------------------------


def test_existing_evidence_is_not_the_same_as_verified_evidence():
    """Ссылка, которую никто не открывал, не может быть сигналом достоверности.

    `pending` в модуле 2 значит «запись есть», а не «проверено». Разница
    принципиальная: иначе Trust растёт от того, что человек вставил ссылку.
    """
    assert is_trust_eligible(evidence(TYPE_LINK, PENDING)) is False
    assert is_trust_eligible(evidence(TYPE_FILE, PENDING)) is False
    assert is_trust_eligible(evidence(TYPE_FREE_TEXT, PENDING)) is False


def test_verification_mechanics_stay_eligible():
    """То, что пришло из механики проверки, сигналом достоверности остаётся."""
    assert is_trust_eligible(evidence(TYPE_BLIND_WITNESS)) is True
    assert is_trust_eligible(evidence(TYPE_MIRROR_TASK)) is True
    assert is_trust_eligible(evidence(TYPE_PROBE_ANSWER)) is True


def test_declined_evidence_never_raises_trust():
    for type_ in (TYPE_BLIND_WITNESS, TYPE_MIRROR_TASK, TYPE_PROBE_ANSWER, TYPE_LINK):
        assert is_trust_eligible(evidence(type_, DECLINED)) is False


def test_adding_a_plain_link_does_not_bump_trust(signed_client):
    """Главная регрессия: обычная ссылка не двигает Trust как проверенная."""
    setup_candidate(signed_client)
    before = signed_client.get(TRUST).json()

    signed_client.post(
        LINK, json={"url": "https://github.com/dev/anything", "statement_ids": statement_ids(signed_client)}
    )

    after = signed_client.get(TRUST).json()
    assert after["overall_score"] == before["overall_score"]
    for item in after["components"]:
        assert item["score"] == component(before, item["component_id"])["score"]


def test_the_same_link_still_works_for_prof(signed_client):
    """Обратная сторона: в PROF доказательство работает как работало.

    Развести Trust и PROF - не значит обесценить доказательство. Покрытие
    эталона считается по тому, что кандидат принёс, и это честное покрытие.
    """
    setup_candidate(signed_client)
    before = signed_client.get(PROF).json()["snapshots"][0]["overall_score"]

    signed_client.post(
        LINK, json={"url": "https://github.com/dev/billing", "statement_ids": statement_ids(signed_client)}
    )

    assert signed_client.get(PROF).json()["snapshots"][0]["overall_score"] > before


def test_nda_evidence_is_not_penalised(signed_client):
    """Закрытый материал не наказывается за то, что он закрыт."""
    nda = [evidence(TYPE_BLIND_WITNESS, statements=("stmt_001",))]
    with_nda = understanding([], nda)
    without = understanding([], [])

    assert with_nda.score >= without.score
    assert "не" not in with_nda.explanation_ru.lower().split("засчитано")[0]


def test_future_external_verification_has_a_place_to_land():
    """Крючок под внешнюю проверку есть, а самой проверки нет - и это честно."""
    source = inspect.getsource(trust_logic)
    assert "EXTERNALLY_VERIFIED" in source

    verified = EvidenceFacts(
        id="ev_009",
        type=TYPE_LINK,
        source_category="github",
        status=trust_logic.EXTERNALLY_VERIFIED,
        statement_ids=("stmt_001",),
    )
    assert is_trust_eligible(verified) is True

    # Но сейчас такой статус никто не выставляет: интеграций нет.
    from app import enrichment

    assert trust_logic.EXTERNALLY_VERIFIED not in inspect.getsource(enrichment)


# --- 2. Смысл непротиворечивости ------------------------------------------


def test_many_sources_do_not_mean_high_consistency():
    """Пять ссылок разных видов не доказывают, что они согласуются."""
    many = [
        EvidenceFacts(f"ev_{i}", TYPE_LINK, category, PENDING, ("stmt_001",))
        for i, category in enumerate(("github", "article", "certificate", "portfolio", "other"), 1)
    ]

    assert consistency(many, 0, 0, 0).score == consistency([], 0, 0, 0).score


def test_consistency_counts_only_resolved_contradictions():
    none_resolved = consistency([], 0, 0, 0)
    resolved = consistency([], 0, 2, 0)

    assert resolved.score > none_resolved.score


def test_open_contradiction_is_never_a_punishment():
    without = consistency([], 0, 0, 0)
    with_open = consistency([], 3, 0, 0)

    assert with_open.score == without.score


def test_unmeasured_consistency_says_so_instead_of_looking_bad():
    """Неизмеренное - не ноль и не плохой результат: так и написано."""
    result = consistency([evidence()], 0, 0, 0)

    assert "не измерено" in result.explanation_ru.lower()
    assert "не оценка" in result.explanation_ru.lower()


def test_consistency_explanation_matches_what_was_actually_used():
    """Объяснение не должно ссылаться на данные, которых в расчёте нет."""
    result = consistency([evidence() for _ in range(4)], 0, 1, 0)

    assert "Разобранных нестыковок: 1" in result.explanation_ru
    assert any("только разобранные нестыковки" in note for note in result.notes_ru)


def test_consistency_no_longer_reads_evidence_categories():
    """Проверка кодом: взвешивание источников из компонента убрано."""
    source = inspect.getsource(consistency)
    assert "_weighted_sum" not in source
    assert "_category_key" not in source


# --- 3. Заявление о самостоятельности -------------------------------------


def test_authenticity_does_not_claim_proven_authorship(signed_client):
    """Система обязана говорить, что это признаки, а не доказательство."""
    setup_candidate(signed_client)
    item = component(signed_client.get(TRUST).json(), AUTHENTICITY)

    caveat = " ".join(item["notes_ru"]).lower()
    assert "не доказательство авторства" in caveat
    assert "не утверждаем" in caveat or "не знаем" in caveat


def test_authenticity_label_no_longer_overclaims(signed_client):
    setup_candidate(signed_client)
    item = component(signed_client.get(TRUST).json(), AUTHENTICITY)

    assert item["name_ru"] == "Признаки самостоятельной работы"


def test_authenticity_names_the_signals_it_actually_uses():
    source = inspect.getsource(trust_logic.authenticity)
    assert "paste_attempts_blocked" in source
    assert "understanding_signal" in source

    caveat = trust_logic.AUTHENTICITY_CAVEAT_RU.lower()
    assert "вставить текст" in caveat
    assert "общие слова" in caveat


def test_no_surveillance_was_added():
    """Ослабление заявления - не повод строить античит.

    Проверяется отсутствие механики, а не слова: упоминание клавиатурного
    почерка в комментарии как раз объясняет, почему его нет.
    """
    source = inspect.getsource(trust_logic)
    for forbidden in ("keystroke_meta", "blur_events", "focus_lost", "screenshot", "webcam"):
        assert forbidden not in source.lower()

    facts = inspect.getsource(trust_logic.ProbeFacts)
    assert "keystroke" not in facts.lower()


def test_authenticity_component_id_is_unchanged():
    """Идентификатор менять нельзя: на него ссылаются объяснения и отметки."""
    assert AUTHENTICITY == "authenticity"


# --- 4. Время не понижает PROF --------------------------------------------


def test_time_alone_never_lowers_prof(signed_client):
    """Тридцать дней сами по себе не делают доказанный опыт слабее."""
    setup_candidate(signed_client)
    signed_client.post(
        LINK, json={"url": "https://github.com/dev/billing", "statement_ids": statement_ids(signed_client)}
    )
    signed_client.get(GROWTH)

    before = signed_client.get(PROF).json()["snapshots"][0]["overall_score"]

    long_ago = datetime.now(timezone.utc) - timedelta(days=400)
    with SessionLocal() as db:
        for item in db.query(Evidence).all():
            item.created_at = long_ago
        for row in db.query(CompetencyFreshness).all():
            row.last_confirmed_at = long_ago
            row.decay_countdown_started_at = long_ago
        db.commit()

    assert signed_client.get(PROF).json()["snapshots"][0]["overall_score"] == before


def test_time_alone_never_lowers_trust(signed_client):
    setup_candidate(signed_client)
    signed_client.get(GROWTH)
    before = signed_client.get(TRUST).json()["overall_score"]

    with SessionLocal() as db:
        long_ago = datetime.now(timezone.utc) - timedelta(days=400)
        for item in db.query(Evidence).all():
            item.created_at = long_ago
        db.commit()

    assert signed_client.get(TRUST).json()["overall_score"] == before


def test_old_evidence_is_never_deleted(signed_client):
    setup_candidate(signed_client)
    signed_client.post(
        LINK, json={"url": "https://github.com/dev/billing", "statement_ids": statement_ids(signed_client)}
    )
    before = len(signed_client.get(PROFILE).json()["evidence"])

    with SessionLocal() as db:
        for item in db.query(Evidence).all():
            item.created_at = datetime.now(timezone.utc) - timedelta(days=400)
        db.commit()
    signed_client.get(GROWTH)

    assert len(signed_client.get(PROFILE).json()["evidence"]) == before


def test_refresh_button_creates_no_evidence(signed_client):
    """Нажатие кнопки - не доказательство, и им притворяться не должно."""
    setup_candidate(signed_client)
    signed_client.post(
        LINK, json={"url": "https://github.com/dev/billing", "statement_ids": statement_ids(signed_client)}
    )
    payload = signed_client.get(GROWTH).json()
    if not payload["freshness"]:
        return

    before = len(signed_client.get(PROFILE).json()["evidence"])
    competency_id = payload["freshness"][0]["competency_id"]
    signed_client.post(f"{GROWTH}/freshness/{competency_id}/refresh")

    assert len(signed_client.get(PROFILE).json()["evidence"]) == before


def test_prof_no_longer_applies_a_freshness_multiplier():
    """Проверка кодом: понижающего множителя в сборке индекса нет."""
    from app.routers import prof as prof_router

    source = inspect.getsource(prof_router)
    assert "_apply_freshness" not in source


def test_freshness_data_is_kept_for_the_future():
    """Данные актуальности остаются - убрано только их влияние на балл."""
    assert hasattr(growth, "freshness_for")
    assert CompetencyFreshness.__tablename__ == "competency_freshness"


# --- 5. Роли и разграничение доступа --------------------------------------


def test_registration_gives_the_least_privileged_role(signed_client):
    """Регистрация не должна выдавать прав над чужими данными."""
    from app.access import CANDIDATE, role_of
    from app.models import User

    with SessionLocal() as db:
        user = db.query(User).first()
        assert user.role == CANDIDATE
        assert role_of(user) == CANDIDATE


def test_candidate_cannot_reach_recruiter_routes(signed_client):
    """Прямой запрос к API, а не спрятанная кнопка."""
    assert signed_client.get("/api/recruiter/search", params={"vacancy_id": "vac_001"}).status_code == 403
    assert signed_client.get(
        "/api/recruiter/candidates/cand_001", params={"vacancy_id": "vac_001"}
    ).status_code == 403
    assert signed_client.post("/api/plugin/lookup", json={"contact_hash": "x" * 71}).status_code == 403


def test_candidate_cannot_reach_moderator_routes(signed_client):
    assert signed_client.get("/api/moderation/queue").status_code == 403
    assert signed_client.post(
        "/api/moderation/cases/dc_001/uphold", json={"rationale_ru": "потому что"}
    ).status_code == 403


def test_candidate_cannot_reach_the_operator_dashboard(signed_client):
    assert signed_client.get("/api/calibration").status_code == 403
    assert signed_client.post(
        "/api/calibration/changes",
        json={"constant_ref": "module8.decay_countdown_days", "new_value": "1", "rationale_ru": "нет"},
    ).status_code == 403


def test_recruiter_cannot_perform_moderator_actions(recruiter_client):
    """Роли не наследуются: рекрутер не становится модератором."""
    assert recruiter_client.get("/api/moderation/queue").status_code == 403
    assert recruiter_client.post(
        "/api/moderation/cases/dc_001/override",
        json={
            "target_type": "trust_component_score",
            "target_id": "understanding",
            "new_value": "100",
            "rationale_ru": "хочется",
        },
    ).status_code == 403
    assert recruiter_client.get("/api/calibration").status_code == 403


def test_moderator_does_not_get_recruiter_capabilities(moderator_client):
    """И наоборот: у модератора нет причины смотреть базу кандидатов."""
    assert moderator_client.get(
        "/api/recruiter/search", params={"vacancy_id": "vac_001"}
    ).status_code == 403
    assert moderator_client.post(
        "/api/plugin/invites", json={"note_ru": None}
    ).status_code == 403


def test_role_from_the_request_body_is_ignored(signed_client):
    """Роль определяется на сервере, и подменить её запросом нельзя."""
    for attempt in (
        {"role": "moderator"},
        {"actor_role": "moderator"},
        {"user": {"role": "moderator"}},
    ):
        response = signed_client.post("/api/moderation/cases/dc_001/uphold", json={**attempt, "rationale_ru": "x"})
        assert response.status_code == 403

    # И заголовком тоже.
    assert signed_client.get(
        "/api/moderation/queue", headers={"X-Role": "moderator", "Role": "moderator"}
    ).status_code == 403


def test_guards_sit_on_routers_not_on_handlers():
    """Забыть проверку на новом обработчике проще, чем забыть завести роутер."""
    from app.routers import calibration, moderation, plugin, recruiter

    for module in (moderation, recruiter, plugin):
        source = inspect.getsource(module)
        assert "dependencies=[Depends(require_" in source

    operator = inspect.getsource(calibration)
    assert "dependencies=[Depends(require_moderator)]" in operator
    assert "dependencies=[Depends(require_recruiter)]" in operator


def test_there_is_no_endpoint_that_grants_a_role():
    """«Стать модератором» запросом нельзя: такого пути нет вообще.

    Проверяется не слово «role» в адресе - `/api/prof/roles` про целевую роль
    кандидата (Middle, Senior) и к правам отношения не имеет, - а отсутствие
    записи роли где-либо в обработчиках.
    """
    from app.main import app

    paths = app.openapi()["paths"]
    for path in paths:
        assert "/api/roles" not in path
        assert "grant" not in path.lower()
        assert "permission" not in path.lower()

    # Ни один обработчик не присваивает роль: это делает только скрипт
    # администратора, работающий с базой напрямую.
    from pathlib import Path as _Path

    routers = _Path(__file__).resolve().parents[1] / "app" / "routers"
    for module in routers.glob("*.py"):
        source = module.read_text(encoding="utf-8")
        assert ".role =" not in source, module.name
        assert "user.role" not in source, module.name


# --- 6. Журнал обращений ---------------------------------------------------


def test_sensitive_access_leaves_an_audit_entry(recruiter_client):
    from app.models import AccessLog

    recruiter_client.get("/api/recruiter/search", params={"vacancy_id": "vac_001"})

    with SessionLocal() as db:
        entries = db.query(AccessLog).all()
        assert entries
        entry = entries[-1]
        assert entry.actor_role == "recruiter"
        assert "/api/recruiter/search" in entry.action
        assert entry.at is not None


def test_moderator_actions_are_logged_too(moderator_client):
    from app.models import AccessLog

    moderator_client.get("/api/moderation/queue")

    with SessionLocal() as db:
        roles = {entry.actor_role for entry in db.query(AccessLog).all()}
        assert "moderator" in roles


def test_candidate_browsing_own_profile_is_not_logged(signed_client):
    """Журнал - про обращение к чужим данным, а не тотальная слежка."""
    from app.models import AccessLog

    signed_client.get("/api/profile")
    signed_client.get("/api/trust")

    with SessionLocal() as db:
        assert db.query(AccessLog).count() == 0


def test_audit_log_stores_no_content():
    """В журнал не должно попадать то, что кандидат закрыл под NDA."""
    from app.models import AccessLog

    fields = set(AccessLog.__table__.columns.keys())
    for forbidden in ("body", "payload", "raw_text", "evidence", "content"):
        assert forbidden not in fields

    from app import access

    source = inspect.getsource(access)
    assert "await request.body()" not in source
    assert "request.json()" not in source
