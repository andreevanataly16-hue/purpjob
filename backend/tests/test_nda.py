"""Проверки модуля 5: NDA и альтернативная верификация.

Главное, что здесь проверяется: закрытый опыт можно подтвердить, ни разу не
показав ни файла, ни названия клиента, ни цифр, — и ни один отказ по дороге
ничего не отнимает.
"""

import pytest

from app.db import SessionLocal
from app.declines import TARGET_NDACASE
from app.enrichment import MEDIUM, TYPE_BLIND_WITNESS, TYPE_MIRROR_TASK
from app.mirror_tasks import SCENARIOS, scenario_for
from app.models import DeclineRecord, NDACase, NDAMethodSwitch
from app.probe import MODE_BLIND_WITNESS, MODE_MIRROR_TASK, generate_question
from app.probe_templates import TEMPLATES
from app.routers.nda import DISCLAIMER, MIRROR_FRAMING

NDA = "/api/nda"
CASES = "/api/nda/cases"
PROBE = "/api/probe"
ROLES = "/api/prof/roles"
PARSE = "/api/profile/parse"
ACCEPT = "/api/profile/statements/accept"
PROF = "/api/prof"
PROFILE = "/api/profile"

CASE_TEXT = (
    "Переписал биллинг с нуля на Python, вынес его в отдельный микросервис. "
    "Под нагрузкой в 3000 rps старая схема не держала, поэтому добавили Redis "
    "и переработали индексы в PostgreSQL."
)

STRUCTURAL_ANSWER = (
    "Узлов было три: приём запроса, слой кеша и источник данных. Критическим оказался "
    "переход между кешем и источником — там при массовом промахе шло 200 одновременных "
    "запросов, поэтому поставили блокировку на прогрев и разнесли время жизни записей."
)

LOGIC_ANSWER = (
    "Сначала считаем читающую нагрузку и цену промаха, потом решаем, что инвалидировать по "
    "событию, а что по времени. Если данные меняются реже, чем читаются в сто раз, берём "
    "событийную инвалидацию и прогрев после перезапуска."
)

VAGUE = "Всё было нормально, справились."


def setup_candidate(client, level="Middle"):
    client.post(ROLES, json={"level": level})
    parsed = client.post(PARSE, json={"raw_text": CASE_TEXT}).json()
    client.post(ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]})


def open_case(client, competency_id="caching"):
    state = client.post(CASES, json={"competency_id": competency_id}).json()
    return state["cases"][-1]


def acknowledged_case(client, competency_id="caching"):
    case = open_case(client, competency_id)
    state = client.post(f"{CASES}/{case['id']}/acknowledge").json()
    return next(c for c in state["cases"] if c["id"] == case["id"])


def case_by_id(state, case_id):
    return next(c for c in state["cases"] if c["id"] == case_id)


# --- содержание: чего этот модуль не просит никогда -----------------------


def test_disclaimer_names_both_sides():
    """FR1.2: односторонней фразы «не переживайте» недостаточно."""
    assert DISCLAIMER["allowed_ru"] and DISCLAIMER["never_asked_ru"]
    assert "код" in DISCLAIMER["never_asked_ru"]
    assert "имена клиентов" in DISCLAIMER["never_asked_ru"]
    assert DISCLAIMER["legal_review_note_ru"], "пометка о юрпроверке не должна теряться"


def test_no_nda_prompt_ever_asks_for_a_file_or_a_client_name():
    """FR1.3: ограничение содержания, а не пожелание к тону."""
    forbidden = ("название клиент", "имя клиент", "приложите файл", "загрузите", "выручк")

    for template in TEMPLATES:
        if template.slot not in ("nda", "structure"):
            continue
        lowered = template.text.lower()
        assert not any(word in lowered for word in forbidden), template.id

    for scenario in SCENARIOS:
        lowered = (scenario.instructions_ru + scenario.title_ru).lower()
        assert not any(word in lowered for word in forbidden), scenario.id


def test_mirror_task_framing_line_is_not_optional():
    """FR2.4: оговорка про позиционирование - требование, а не украшение."""
    assert "не замена реальному опыту" in MIRROR_FRAMING
    assert "не очередное тестовое" in MIRROR_FRAMING


# --- движок: те же режимы, а не отдельная реализация ---------------------


def test_blind_witness_prompt_comes_from_the_shared_engine():
    question = generate_question(
        "caching", [], ("Caching",), mode=MODE_BLIND_WITNESS, competency_name_ru="Кеширование"
    )

    assert question is not None
    assert "структур" in question.text_ru.lower()
    assert "Слепого свидетеля" in question.reason_ru


def test_mirror_task_mode_returns_a_scenario_not_a_question():
    assert generate_question("caching", [], mode=MODE_MIRROR_TASK) is None
    assert scenario_for("caching") is not None


def test_competency_without_a_scenario_does_not_get_a_fake_one():
    """FR2.1: выдумывать абстрактную головоломку нельзя."""
    assert scenario_for("testing") is None


def test_every_scenario_belongs_to_a_real_competency():
    from app.reference import PROFILES

    known = {c.competency_id for p in PROFILES.values() for c in p.competencies}
    assert all(scenario.competency_id in known for scenario in SCENARIOS)


# --- US1: дисклеймер как жёсткие ворота ----------------------------------


def test_nda_requires_login(client):
    assert client.get(NDA).status_code == 401


def test_case_starts_at_method_selection_without_acknowledgement(signed_client):
    setup_candidate(signed_client)
    case = open_case(signed_client)

    assert case["status"] == "method_selection"
    assert case["disclaimer_acknowledged"] is False


def test_method_cannot_be_chosen_before_the_disclaimer(signed_client):
    setup_candidate(signed_client)
    case = open_case(signed_client)

    response = signed_client.post(
        f"{CASES}/{case['id']}/method", json={"method": "blind_witness"}
    )

    assert response.status_code == 409
    assert "не спрашиваем" in response.json()["detail"]


def test_acknowledgement_opens_the_flow(signed_client):
    setup_candidate(signed_client)
    case = acknowledged_case(signed_client)

    assert case["disclaimer_acknowledged"] is True
    state = signed_client.post(
        f"{CASES}/{case['id']}/method", json={"method": "blind_witness"}
    ).json()
    assert case_by_id(state, case["id"])["status"] == "in_progress"


# --- US4: способ выбирает кандидат ---------------------------------------


def test_both_methods_are_shown_as_equal_choices(signed_client):
    setup_candidate(signed_client)
    case = acknowledged_case(signed_client)

    methods = {m["value"]: m for m in case["methods"]}
    assert set(methods) == {"blind_witness", "mirror_task"}
    assert all(m["label_ru"] and m["description_ru"] for m in methods.values())
    assert methods["mirror_task"]["available"] is True


def test_mirror_task_is_marked_unavailable_when_there_is_no_scenario(signed_client):
    setup_candidate(signed_client)
    case = acknowledged_case(signed_client, "testing")

    mirror = next(m for m in case["methods"] if m["value"] == "mirror_task")
    assert mirror["available"] is False
    assert mirror["unavailable_reason_ru"]

    response = signed_client.post(
        f"{CASES}/{case['id']}/method", json={"method": "mirror_task"}
    )
    assert response.status_code == 409


def test_switching_method_mid_flow_is_free_and_logged(signed_client):
    """FR4.2, FR4.3: без объяснений, без потери самого случая."""
    setup_candidate(signed_client)
    case = acknowledged_case(signed_client)

    signed_client.post(f"{CASES}/{case['id']}/method", json={"method": "blind_witness"})
    state = signed_client.post(
        f"{CASES}/{case['id']}/method", json={"method": "mirror_task"}
    ).json()

    switched = case_by_id(state, case["id"])
    assert switched["chosen_method"] == "mirror_task"
    assert switched["status"] == "in_progress"
    assert switched["switch_count"] == 2
    # Начатая сессия Слепого свидетеля никуда не делась - случай тот же.
    assert switched["blind_witness"]
    assert switched["mirror_task"] is not None

    with SessionLocal() as db:
        assert db.query(NDAMethodSwitch).count() == 2


def test_declining_all_methods_costs_nothing(signed_client):
    """FR4.4: компетенция просто остаётся неподтверждённой."""
    setup_candidate(signed_client)
    before = signed_client.get(PROF).json()["snapshots"][0]
    case = acknowledged_case(signed_client)

    state = signed_client.post(f"{CASES}/{case['id']}/decline", json={}).json()

    assert case_by_id(state, case["id"])["status"] == "declined_all"
    after = signed_client.get(PROF).json()["snapshots"][0]
    assert after["overall_score"] == before["overall_score"]
    assert after["white_spots"] == before["white_spots"]


def test_decline_uses_the_shared_mechanism(signed_client):
    """FR4.5: третьей реализации права на отказ в продукте нет."""
    setup_candidate(signed_client)
    case = acknowledged_case(signed_client)
    signed_client.post(f"{CASES}/{case['id']}/decline", json={})

    with SessionLocal() as db:
        record = db.query(DeclineRecord).filter_by(target_type=TARGET_NDACASE).one()
        assert record.reason is None
        assert db.get(NDACase, record.target_id).status == "declined_all"


def test_candidate_can_come_back_after_declining_everything(signed_client):
    setup_candidate(signed_client)
    case = acknowledged_case(signed_client)
    signed_client.post(f"{CASES}/{case['id']}/decline", json={})

    state = signed_client.post(
        f"{CASES}/{case['id']}/method", json={"method": "blind_witness"}
    ).json()

    assert case_by_id(state, case["id"])["status"] == "in_progress"
    with SessionLocal() as db:
        assert db.query(DeclineRecord).filter_by(target_type=TARGET_NDACASE).count() == 0


# --- US3: Метод Слепого свидетеля ----------------------------------------


def test_blind_witness_session_has_questions_with_reasons(signed_client):
    setup_candidate(signed_client)
    case = acknowledged_case(signed_client)
    state = signed_client.post(
        f"{CASES}/{case['id']}/method", json={"method": "blind_witness"}
    ).json()

    questions = case_by_id(state, case["id"])["blind_witness"]
    assert len(questions) == 2
    assert all(q["prompt_ru"] and q["reason_ru"] for q in questions)


def test_blind_witness_produces_evidence_without_any_artifact(signed_client):
    """Приёмочный сценарий US3."""
    setup_candidate(signed_client)
    case = acknowledged_case(signed_client)
    state = signed_client.post(
        f"{CASES}/{case['id']}/method", json={"method": "blind_witness"}
    ).json()

    for question, answer in zip(
        case_by_id(state, case["id"])["blind_witness"], (STRUCTURAL_ANSWER, LOGIC_ANSWER)
    ):
        state = signed_client.post(
            f"{NDA}/questions/{question['id']}/answer", json={"text": answer}
        ).json()

    assert case_by_id(state, case["id"])["status"] == "confirmed"

    profile = signed_client.get(PROFILE).json()
    evidence = [e for e in profile["evidence"] if e["type"] == TYPE_BLIND_WITNESS]
    assert len(evidence) == 1
    assert evidence[0]["nda"] is True
    assert evidence[0]["file_ref"] is None and evidence[0]["url"] is None
    assert evidence[0]["linked_statement_ids"]


def test_generic_blind_witness_answer_gets_one_clarification(signed_client):
    """FR3.3: низкоусердный ответ не проходит просто потому, что путь NDA."""
    setup_candidate(signed_client)
    case = acknowledged_case(signed_client)
    state = signed_client.post(
        f"{CASES}/{case['id']}/method", json={"method": "blind_witness"}
    ).json()
    first = case_by_id(state, case["id"])["blind_witness"][0]

    state = signed_client.post(
        f"{NDA}/questions/{first['id']}/answer", json={"text": VAGUE}
    ).json()

    updated = case_by_id(state, case["id"])["blind_witness"][0]
    assert updated["follow_up_ru"]
    assert updated["follow_up_reason_ru"]
    assert case_by_id(state, case["id"])["status"] == "in_progress"

    profile = signed_client.get(PROFILE).json()
    assert not [e for e in profile["evidence"] if e["type"] == TYPE_BLIND_WITNESS]


def test_blind_witness_lifts_the_competency_and_the_index(signed_client):
    setup_candidate(signed_client)
    before = signed_client.get(PROF).json()["snapshots"][0]["overall_score"]

    case = acknowledged_case(signed_client)
    state = signed_client.post(
        f"{CASES}/{case['id']}/method", json={"method": "blind_witness"}
    ).json()
    for question, answer in zip(
        case_by_id(state, case["id"])["blind_witness"], (STRUCTURAL_ANSWER, LOGIC_ANSWER)
    ):
        signed_client.post(f"{NDA}/questions/{question['id']}/answer", json={"text": answer})

    snapshot = signed_client.get(PROF).json()["snapshots"][0]
    caching = next(c for c in snapshot["components"] if c["competency_id"] == "caching")

    assert snapshot["overall_score"] > before
    assert caching["status"] in (MEDIUM, "strong")
    assert "caching" not in snapshot["white_spots"]


# --- US2: зеркальная задача ----------------------------------------------


def test_mirror_task_scenario_is_offered_with_its_framing(signed_client):
    setup_candidate(signed_client)
    case = acknowledged_case(signed_client)
    state = signed_client.post(
        f"{CASES}/{case['id']}/method", json={"method": "mirror_task"}
    ).json()

    mirror = case_by_id(state, case["id"])["mirror_task"]
    assert mirror["scenario"]["framing_ru"] == MIRROR_FRAMING
    assert len(mirror["scenario"]["nodes"]) >= 3
    assert mirror["status"] == "pending"


def test_mirror_task_needs_both_arrangement_and_explanation(signed_client):
    setup_candidate(signed_client)
    case = acknowledged_case(signed_client)
    signed_client.post(f"{CASES}/{case['id']}/method", json={"method": "mirror_task"})

    only_nodes = signed_client.post(
        f"{CASES}/{case['id']}/mirror-task",
        json={"node_arrangement": [{"node_id": "n1", "order": 1, "role_ru": "вход"}]},
    )
    only_text = signed_client.post(
        f"{CASES}/{case['id']}/mirror-task",
        json={"node_arrangement": [], "logic_explanation": LOGIC_ANSWER},
    )

    assert only_nodes.status_code == 422
    assert only_text.status_code == 422


def test_mirror_task_produces_evidence(signed_client):
    """Приёмочный сценарий US2."""
    setup_candidate(signed_client)
    case = acknowledged_case(signed_client)
    state = signed_client.post(
        f"{CASES}/{case['id']}/method", json={"method": "mirror_task"}
    ).json()
    nodes = case_by_id(state, case["id"])["mirror_task"]["scenario"]["nodes"]

    state = signed_client.post(
        f"{CASES}/{case['id']}/mirror-task",
        json={
            "node_arrangement": [
                {"node_id": node["id"], "order": index, "role_ru": node["label_ru"]}
                for index, node in enumerate(nodes, start=1)
            ],
            "logic_explanation": LOGIC_ANSWER,
        },
    ).json()

    assert case_by_id(state, case["id"])["status"] == "confirmed"

    profile = signed_client.get(PROFILE).json()
    evidence = [e for e in profile["evidence"] if e["type"] == TYPE_MIRROR_TASK]
    assert len(evidence) == 1
    assert evidence[0]["nda"] is True
    assert evidence[0]["file_ref"] is None

    snapshot = signed_client.get(PROF).json()["snapshots"][0]
    assert "caching" not in snapshot["white_spots"]


def test_unknown_nodes_are_rejected(signed_client):
    setup_candidate(signed_client)
    case = acknowledged_case(signed_client)
    signed_client.post(f"{CASES}/{case['id']}/method", json={"method": "mirror_task"})

    response = signed_client.post(
        f"{CASES}/{case['id']}/mirror-task",
        json={
            "node_arrangement": [{"node_id": "n99", "order": 1, "role_ru": "?"}],
            "logic_explanation": LOGIC_ANSWER,
        },
    )
    assert response.status_code == 400


def test_generic_mirror_explanation_gets_one_clarification(signed_client):
    setup_candidate(signed_client)
    case = acknowledged_case(signed_client)
    state = signed_client.post(
        f"{CASES}/{case['id']}/method", json={"method": "mirror_task"}
    ).json()
    nodes = case_by_id(state, case["id"])["mirror_task"]["scenario"]["nodes"]

    state = signed_client.post(
        f"{CASES}/{case['id']}/mirror-task",
        json={
            "node_arrangement": [{"node_id": nodes[0]["id"], "order": 1, "role_ru": "вход"}],
            "logic_explanation": VAGUE,
        },
    ).json()

    mirror = case_by_id(state, case["id"])["mirror_task"]
    assert mirror["follow_up_ru"]
    assert case_by_id(state, case["id"])["status"] != "confirmed"


# --- связь с модулем 4 ----------------------------------------------------


def test_probe_nda_decline_opens_an_nda_case(signed_client):
    """§4.1: заглушка модуля 4 заменена настоящим потоком модуля 5."""
    setup_candidate(signed_client)
    question = signed_client.post("/api/probe/next", json={}).json()["question"]

    signed_client.post(f"{PROBE}/questions/{question['id']}/decline", json={})

    cases = signed_client.get(NDA).json()["cases"]
    assert len(cases) == 1
    assert cases[0]["competency_id"] == question["competency_id"]
    assert cases[0]["origin"] == "probe"
    assert cases[0]["status"] == "method_selection"


def test_probe_decline_still_takes_nothing_away(signed_client):
    setup_candidate(signed_client)
    before = signed_client.get(PROF).json()["snapshots"][0]
    question = signed_client.post("/api/probe/next", json={}).json()["question"]

    signed_client.post(f"{PROBE}/questions/{question['id']}/decline", json={})

    after = signed_client.get(PROF).json()["snapshots"][0]
    assert after["overall_score"] == before["overall_score"]


def test_cases_are_private_to_the_candidate(signed_client, client):
    setup_candidate(signed_client)
    case = acknowledged_case(signed_client)
    signed_client.post("/api/auth/logout")

    client.post(
        "/api/auth/register", json={"email": "other@example.com", "password": "verysecret123"}
    )

    assert client.get(NDA).json()["cases"] == []
    assert client.post(f"{CASES}/{case['id']}/acknowledge").status_code == 404


@pytest.mark.parametrize("competency_id", ["caching", "high_load", "distributed_systems"])
def test_seeded_competencies_offer_both_methods(signed_client, competency_id):
    setup_candidate(signed_client)
    case = acknowledged_case(signed_client, competency_id)

    assert all(m["available"] for m in case["methods"])
