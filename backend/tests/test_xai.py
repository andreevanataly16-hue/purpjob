"""Проверки модуля 7: объяснимость и модерация.

Главное правило модуля - «ИИ предлагает вывод, но не может быть неоспоримым
судьёй» - проверяется здесь не чтением текстов, а свойствами:

* у каждого вывода есть объяснение фактом и точка входа «почему»;
* каждая ссылка на доказательство открывается до настоящей записи;
* спор доступен везде, не требует обоснования и ничего не меняет в выводе;
* изменить балл в обход журнала невозможно;
* записи журнала нельзя ни отредактировать, ни удалить.
"""

import inspect

import pytest
from sqlalchemy.exc import StatementError

from app import overrides
from app.db import SessionLocal
from app.models import AnomalyFlag, AppendOnlyViolation, DisputeCase, DisputeHistoryEntry
from app.routers import moderation as moderation_router
from app.xai import (
    PROBE_QUESTION_REASON,
    PROF_COMPETENCY_STATUS,
    TRUST_COMPONENT,
    Explanation,
    is_bare_verdict,
    states_absence,
    validate,
)

EXPLANATIONS = "/api/explanations"
DISPUTES = "/api/disputes"
QUEUE = "/api/moderation/queue"
TRUST = "/api/trust"
PROF = "/api/prof"
PROBE = "/api/probe"
ROLES = "/api/prof/roles"
PARSE = "/api/profile/parse"
ACCEPT = "/api/profile/statements/accept"

CASE_TEXT = (
    "Переписал биллинг с нуля на Python, вынес его в отдельный микросервис. "
    "Под нагрузкой в 3000 rps старая схема не держала, поэтому добавили Redis "
    "и переработали индексы в PostgreSQL."
)


def setup_candidate(client, level="Middle"):
    client.post(ROLES, json={"level": level})
    parsed = client.post(PARSE, json={"raw_text": CASE_TEXT}).json()
    client.post(ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]})


def explanations(client):
    return client.get(EXPLANATIONS).json()["explanations"]


def by_type(client, subject_type):
    return [item for item in explanations(client) if item["subject_type"] == subject_type]


def open_dispute(client, explanation_id, statement=None):
    body = {"explanation_id": explanation_id}
    if statement is not None:
        body["candidate_statement"] = statement
    return client.post(DISPUTES, json=body)


# --- US1: один способ спросить «почему» ----------------------------------


def test_every_prof_status_and_trust_component_is_a_canonical_explanation(signed_client):
    """FR1.1: и модуль 3, и модуль 6 отдают выводы в одной и той же форме."""
    setup_candidate(signed_client)

    prof_items = by_type(signed_client, PROF_COMPETENCY_STATUS)
    trust_items = by_type(signed_client, TRUST_COMPONENT)

    prof_components = signed_client.get(PROF).json()["snapshots"][0]["components"]
    trust_components = signed_client.get(TRUST).json()["components"]

    assert len(prof_items) == len(prof_components)
    assert len(trust_items) == len(trust_components)
    assert all(item["conclusion_ru"] for item in prof_items + trust_items)


def test_entry_point_label_is_the_same_everywhere(signed_client):
    """FR1.3: одна формулировка на весь продукт, а не своя на каждый модуль."""
    setup_candidate(signed_client)
    payload = signed_client.get(EXPLANATIONS).json()

    assert payload["why_label_ru"] == "Почему такой вывод?"


def test_every_score_surface_carries_its_explanation_id(signed_client):
    """FR1.3: от балла на экране есть путь к объяснению - без него точка входа
    была бы кнопкой в никуда."""
    setup_candidate(signed_client)

    for component in signed_client.get(PROF).json()["snapshots"][0]["components"]:
        assert component["explanation_id"]
    for component in signed_client.get(TRUST).json()["components"]:
        assert component["explanation_id"]


def test_explanation_ids_survive_recomputation(signed_client):
    """PROF и Trust пересчитываются на каждый запрос: если бы идентификатор был
    счётчиком, спор указывал бы в пустоту уже на следующем запросе."""
    setup_candidate(signed_client)

    first = {item["id"] for item in explanations(signed_client)}
    signed_client.get(PROF)
    signed_client.get(TRUST)
    second = {item["id"] for item in explanations(signed_client)}

    assert first == second


def test_conclusion_is_a_fact_not_a_verdict():
    """FR1.2: оценка вместо проверяемого факта - дефект объяснения."""
    assert is_bare_verdict("Низкая достоверность профиля.")
    assert not is_bare_verdict("В профиле 0 подтверждений из независимых источников.")


def test_every_generated_explanation_passes_its_own_rules(signed_client):
    """Правило FR1.2/FR2.2 применяется к живым выводам, а не только к примерам."""
    setup_candidate(signed_client)
    items = explanations(signed_client)
    assert items, "проверять нечего — объяснения не собрались"

    for item in items:
        detail = signed_client.get(f"{EXPLANATIONS}/{item['id']}").json()
        assert detail["problems"] == [], (item["id"], detail["problems"])


def test_unknown_explanation_is_not_found(signed_client):
    setup_candidate(signed_client)
    assert signed_client.get(f"{EXPLANATIONS}/expl_trust_nonexistent").status_code == 404


# --- US2: доказательства открываются -------------------------------------


def test_every_evidence_ref_resolves_to_a_real_record(signed_client):
    """FR2.1: ссылка, которая никуда не ведёт, - дефект, а не упрощение."""
    setup_candidate(signed_client)
    items = explanations(signed_client)
    checked = 0

    for item in items:
        detail = signed_client.get(f"{EXPLANATIONS}/{item['id']}").json()
        assert len(detail["resolved_evidence"]) == len(detail["evidence_refs"])
        assert all(ref["resolved"] for ref in detail["resolved_evidence"])
        assert all(ref["title_ru"] for ref in detail["resolved_evidence"])
        checked += len(detail["resolved_evidence"])

    assert checked > 0, "ни одной ссылки на доказательство не проверено"


def test_zero_conclusion_says_there_is_no_evidence(signed_client):
    """FR2.2: отсутствие доказательств проговаривается, а не показывается
    пустым списком без комментария."""
    setup_candidate(signed_client)

    empty = [
        item
        for item in explanations(signed_client)
        if not item["evidence_refs"] and item["subject_type"] == PROF_COMPETENCY_STATUS
    ]
    assert empty, "должна быть хотя бы одна незакрытая компетенция эталона"
    assert all(states_absence(item["conclusion_ru"]) for item in empty)


def test_multi_evidence_conclusion_shows_all_of_them(signed_client):
    """FR2.3: частичное раскрытие запрещено так же, как отсутствие раскрытия.

    Раньше примером служил компонент непротиворечивости. После
    стабилизационного спринта он доказательства не считает - количество
    источников непротиворечивость не доказывает, - поэтому требование
    проверяется на любом выводе, за которым доказательства действительно
    стоят. Само требование не менялось: показать надо все, а не удобные.
    """
    setup_candidate(signed_client)

    multi = [item for item in explanations(signed_client) if len(item["evidence_refs"]) > 1]
    assert multi, "нужен вывод, опирающийся больше чем на одно доказательство"

    for item in multi:
        detail = signed_client.get(f"{EXPLANATIONS}/{item['id']}").json()
        assert len(detail["resolved_evidence"]) == len(item["evidence_refs"])


def test_broken_ref_is_shown_as_broken_not_hidden(signed_client):
    """Молча выкинуть неразрешимую ссылку - то же частичное раскрытие."""
    setup_candidate(signed_client)
    from app.routers.xai import resolve_refs
    from app.models import User

    with SessionLocal() as db:
        user = db.query(User).first()
        resolved = resolve_refs(db, user, ["ev_999"])

    assert len(resolved) == 1
    assert resolved[0]["resolved"] is False


# --- US3: спор ------------------------------------------------------------


def test_dispute_needs_only_the_explanation(signed_client):
    """FR3.2: обоснование необязательно - «мне кажется, это неверно» хватает."""
    setup_candidate(signed_client)
    target = by_type(signed_client, TRUST_COMPONENT)[0]

    response = open_dispute(signed_client, target["id"])

    assert response.status_code == 201
    case = response.json()["cases"][0]
    assert case["candidate_statement"] is None
    assert case["status"] == "queued"


def test_dispute_changes_no_score_and_no_status(signed_client):
    """FR3.3: спор - это запрос на проверку, а не признание и не понижение."""
    setup_candidate(signed_client)

    before_trust = signed_client.get(TRUST).json()["overall_score"]
    before_prof = signed_client.get(PROF).json()["snapshots"][0]["overall_score"]

    for item in explanations(signed_client)[:5]:
        open_dispute(signed_client, item["id"], "не согласен")

    assert signed_client.get(TRUST).json()["overall_score"] == before_trust
    assert signed_client.get(PROF).json()["snapshots"][0]["overall_score"] == before_prof


def test_every_explanation_offers_a_dispute(signed_client):
    """FR-Gov.1: окончательного, неоспоримого вывода в продукте нет."""
    setup_candidate(signed_client)

    items = explanations(signed_client)
    assert items
    assert all(item["disputable"] for item in items)
    assert all(item["dispute_label_ru"] == "Оспорить и передать на модерацию" for item in items)


def test_dispute_is_visible_next_to_the_explanation_afterwards(signed_client):
    setup_candidate(signed_client)
    target = by_type(signed_client, TRUST_COMPONENT)[0]
    open_dispute(signed_client, target["id"])

    again = next(item for item in explanations(signed_client) if item["id"] == target["id"])
    assert again["open_dispute_id"] is not None


def test_same_explanation_cannot_be_disputed_twice_at_once(signed_client):
    setup_candidate(signed_client)
    target = by_type(signed_client, TRUST_COMPONENT)[0]

    assert open_dispute(signed_client, target["id"]).status_code == 201
    assert open_dispute(signed_client, target["id"]).status_code == 409


def test_candidate_sees_status_and_history_not_a_black_box(signed_client):
    """FR3.4: не «принято, ждите», а статус и вся лента событий."""
    setup_candidate(signed_client)
    target = by_type(signed_client, TRUST_COMPONENT)[0]
    open_dispute(signed_client, target["id"], "балл занижен")

    case = signed_client.get(DISPUTES).json()["cases"][0]
    assert case["status_ru"]
    assert [entry["event_type"] for entry in case["history"]] == ["opened"]
    assert case["history"][0]["note_ru"] == "балл занижен"


def test_dispute_always_has_history_from_the_first_moment(signed_client):
    """§4.3: спора без журнала не бывает."""
    setup_candidate(signed_client)
    for item in explanations(signed_client)[:3]:
        open_dispute(signed_client, item["id"])

    assert all(case["history"] for case in signed_client.get(DISPUTES).json()["cases"])


def test_disputing_an_unknown_conclusion_is_rejected(signed_client):
    setup_candidate(signed_client)
    assert open_dispute(signed_client, "expl_trust_made_up").status_code == 404


# --- US4: модерация -------------------------------------------------------


def queue(client, include_resolved=False):
    return client.get(QUEUE, params={"include_resolved": include_resolved}).json()


def test_queue_shows_all_origins_in_one_place(signed_client, moderator_client):
    """FR4.1: модератор не должен ходить по трём спискам за одним и тем же."""
    setup_candidate(signed_client)
    target = by_type(signed_client, TRUST_COMPONENT)[0]
    open_dispute(signed_client, target["id"])

    with SessionLocal() as db:
        case = db.query(DisputeCase).first()
        case.origin = "sampled_audit"
        db.commit()

    payload = queue(moderator_client)
    assert payload["open_count"] == 1
    assert payload["cases"][0]["origin"] == "sampled_audit"


def test_moderator_sees_exactly_what_the_candidate_saw(signed_client, moderator_client):
    """FR4.2: не отдельный «внутренний» вид, а тот же вывод и те же ссылки."""
    setup_candidate(signed_client)
    target = by_type(signed_client, TRUST_COMPONENT)[0]
    detail = signed_client.get(f"{EXPLANATIONS}/{target['id']}").json()
    open_dispute(signed_client, target["id"])

    case = queue(moderator_client)["cases"][0]
    assert case["conclusion_ru"] == detail["conclusion_ru"]
    assert case["evidence_refs"] == detail["evidence_refs"]
    assert len(case["resolved_evidence"]) == len(detail["resolved_evidence"])


def test_moderator_view_is_frozen_at_dispute_time(signed_client, moderator_client):
    """Индекс пересчитывается: без копии модератор разбирал бы уже другой вывод."""
    setup_candidate(signed_client)
    target = by_type(signed_client, TRUST_COMPONENT)[0]
    original = signed_client.get(f"{EXPLANATIONS}/{target['id']}").json()["conclusion_ru"]
    open_dispute(signed_client, target["id"])

    parsed = signed_client.post(PARSE, json={"raw_text": "Пишу тесты на pytest каждый день."}).json()
    signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]}
    )

    assert queue(moderator_client)["cases"][0]["conclusion_ru"] == original


def test_uphold_requires_a_reason(signed_client, moderator_client):
    """FR4.3a: «проверили, всё верно» без причины - отписка, а не решение."""
    setup_candidate(signed_client)
    target = by_type(signed_client, TRUST_COMPONENT)[0]
    case_id = open_dispute(signed_client, target["id"]).json()["cases"][0]["id"]

    empty = moderator_client.post(f"/api/moderation/cases/{case_id}/uphold", json={"rationale_ru": ""})
    assert empty.status_code == 422

    ok = moderator_client.post(
        f"/api/moderation/cases/{case_id}/uphold",
        json={"rationale_ru": "Проверил три источника — все из одной категории, расчёт верен."},
    )
    assert ok.status_code == 200

    case = signed_client.get(DISPUTES).json()["cases"][0]
    assert case["status"] == "resolved_upheld"
    assert any(entry["event_type"] == "moderator_note_added" for entry in case["history"])


def test_request_info_asks_a_named_question(signed_client, moderator_client):
    """FR4.3b: конкретный вопрос, а не «уточните, пожалуйста»."""
    setup_candidate(signed_client)
    target = by_type(signed_client, TRUST_COMPONENT)[0]
    case_id = open_dispute(signed_client, target["id"]).json()["cases"][0]["id"]

    moderator_client.post(
        f"/api/moderation/cases/{case_id}/request-info",
        json={"question_ru": "Из какого репозитория взята ссылка ev_002?"},
    )

    case = signed_client.get(DISPUTES).json()["cases"][0]
    assert case["status"] == "needs_more_info"
    assert case["info_request_ru"].startswith("Из какого репозитория")


def test_candidate_can_answer_and_the_case_returns_to_the_queue(signed_client, moderator_client):
    setup_candidate(signed_client)
    target = by_type(signed_client, TRUST_COMPONENT)[0]
    case_id = open_dispute(signed_client, target["id"]).json()["cases"][0]["id"]
    moderator_client.post(
        f"/api/moderation/cases/{case_id}/request-info", json={"question_ru": "Откуда ссылка?"}
    )

    signed_client.post(f"{DISPUTES}/{case_id}/reply", json={"text": "Из рабочего GitLab."})

    case = signed_client.get(DISPUTES).json()["cases"][0]
    assert case["status"] == "queued"
    assert any(entry["event_type"] == "candidate_responded" for entry in case["history"])


def test_override_requires_a_reason_and_changes_the_value(signed_client, moderator_client):
    """FR4.3c: правка только с причиной - и она действительно меняет вывод."""
    setup_candidate(signed_client)
    trust_before = signed_client.get(TRUST).json()
    component = next(c for c in trust_before["components"] if c["component_id"] == "understanding")
    case_id = open_dispute(signed_client, component["explanation_id"]).json()["cases"][0]["id"]

    without_reason = moderator_client.post(
        f"/api/moderation/cases/{case_id}/override",
        json={
            "target_type": overrides.TARGET_TRUST_COMPONENT,
            "target_id": "understanding",
            "new_value": "80",
            "rationale_ru": "",
        },
    )
    assert without_reason.status_code == 422

    applied = moderator_client.post(
        f"/api/moderation/cases/{case_id}/override",
        json={
            "target_type": overrides.TARGET_TRUST_COMPONENT,
            "target_id": "understanding",
            "new_value": "80",
            "rationale_ru": "Кандидат показал независимость источника в переписке.",
        },
    )
    assert applied.status_code == 200

    after = signed_client.get(TRUST).json()
    assert next(c for c in after["components"] if c["component_id"] == "understanding")["score"] == 80
    assert after["overall_score"] != trust_before["overall_score"]


def test_override_on_prof_status_moves_the_index_and_the_radar(signed_client, moderator_client):
    setup_candidate(signed_client)
    snapshot = signed_client.get(PROF).json()["snapshots"][0]
    component = next(c for c in snapshot["components"] if c["status"] == "not_started")
    case_id = open_dispute(signed_client, component["explanation_id"]).json()["cases"][0]["id"]

    moderator_client.post(
        f"/api/moderation/cases/{case_id}/override",
        json={
            "target_type": overrides.TARGET_PROF_STATUS,
            "target_id": component["competency_id"],
            "new_value": "strong",
            "rationale_ru": "Подтверждено рекомендацией бывшего руководителя вне платформы.",
        },
    )

    after = signed_client.get(PROF).json()["snapshots"][0]
    changed = next(
        c for c in after["components"] if c["competency_id"] == component["competency_id"]
    )
    point = next(
        p for p in after["radar_points"] if p["competency_id"] == component["competency_id"]
    )

    assert changed["status"] == "strong"
    assert changed["competency_id"] not in after["white_spots"]
    assert point["candidate_value"] == 1.0
    assert after["overall_score"] > snapshot["overall_score"]


def test_override_is_visible_to_the_candidate_with_its_reason(signed_client, moderator_client):
    """Правка человека без объяснения на экране - тот же чёрный ящик."""
    setup_candidate(signed_client)
    component = next(c for c in signed_client.get(TRUST).json()["components"])
    case_id = open_dispute(signed_client, component["explanation_id"]).json()["cases"][0]["id"]

    moderator_client.post(
        f"/api/moderation/cases/{case_id}/override",
        json={
            "target_type": overrides.TARGET_TRUST_COMPONENT,
            "target_id": component["component_id"],
            "new_value": "77",
            "rationale_ru": "Учтён внешний отзыв заказчика.",
        },
    )

    after = next(
        c
        for c in signed_client.get(TRUST).json()["components"]
        if c["component_id"] == component["component_id"]
    )
    assert "Учтён внешний отзыв заказчика." in after["moderator_note_ru"]


def test_override_only_accepts_known_targets_and_values(signed_client, moderator_client):
    """FR4.4: правка адресная, и адрес проверяется."""
    setup_candidate(signed_client)
    target = by_type(signed_client, TRUST_COMPONENT)[0]
    case_id = open_dispute(signed_client, target["id"]).json()["cases"][0]["id"]

    bad_type = moderator_client.post(
        f"/api/moderation/cases/{case_id}/override",
        json={
            "target_type": "whole_profile",
            "target_id": "everything",
            "new_value": "good",
            "rationale_ru": "потому что",
        },
    )
    assert bad_type.status_code == 400

    bad_value = moderator_client.post(
        f"/api/moderation/cases/{case_id}/override",
        json={
            "target_type": overrides.TARGET_TRUST_COMPONENT,
            "target_id": "understanding",
            "new_value": "отлично",
            "rationale_ru": "потому что",
        },
    )
    assert bad_value.status_code == 400


def test_there_is_no_blanket_profile_action(signed_client):
    """FR4.4: одного «поправить профиль целиком» в модуле нет и не должно быть."""
    source = inspect.getsource(moderation_router)
    assert "whole_profile" not in source
    assert source.count("ModeratorOverride(") == 1


def test_every_moderator_action_leaves_a_record(signed_client, moderator_client):
    """FR4.5: действия модератора без следа в модуле не существует."""
    setup_candidate(signed_client)
    target = by_type(signed_client, TRUST_COMPONENT)[0]
    case_id = open_dispute(signed_client, target["id"]).json()["cases"][0]["id"]

    moderator_client.post(f"/api/moderation/cases/{case_id}/take")
    moderator_client.post(
        f"/api/moderation/cases/{case_id}/uphold", json={"rationale_ru": "Расчёт верен."}
    )

    history = signed_client.get(DISPUTES).json()["cases"][0]["history"]
    events = [entry["event_type"] for entry in history]
    assert events.count("status_changed") == 2
    assert "moderator_note_added" in events


def test_closed_case_cannot_be_acted_on_again(signed_client, moderator_client):
    setup_candidate(signed_client)
    target = by_type(signed_client, TRUST_COMPONENT)[0]
    case_id = open_dispute(signed_client, target["id"]).json()["cases"][0]["id"]
    moderator_client.post(f"/api/moderation/cases/{case_id}/uphold", json={"rationale_ru": "Верно."})

    again = moderator_client.post(
        f"/api/moderation/cases/{case_id}/uphold", json={"rationale_ru": "Ещё раз."}
    )
    assert again.status_code == 409


def test_queue_states_the_real_access_boundary(signed_client, moderator_client):
    """§7: граница доступа должна быть видна в самом ответе, а не только в README.

    Раньше здесь проверялось, что очередь помечена как «без доступа и без
    ролей». Роли появились в стабилизационном спринте, и прежнее ожидание
    стало неправдой про код: тест бы охранял устаревшее обещание. Смысл
    проверки тот же - экран честно говорит, где его граница.
    """
    payload = queue(moderator_client)
    note = payload["access_note_ru"]
    assert "проверяются на сервере" in note
    # И не обещает больше, чем есть.
    assert "разграничения по компаниям" in note
    assert "без доступа и без ролей" not in note


def test_queue_measures_load_and_dispute_concentration(signed_client, moderator_client):
    """H1: время разбора и перекос по видам выводов должны быть видны."""
    setup_candidate(signed_client)
    target = by_type(signed_client, TRUST_COMPONENT)[0]
    case_id = open_dispute(signed_client, target["id"]).json()["cases"][0]["id"]
    moderator_client.post(f"/api/moderation/cases/{case_id}/uphold", json={"rationale_ru": "Верно."})

    stats = queue(moderator_client)["stats"]
    assert stats["resolved_count"] == 1
    assert stats["median_minutes_to_resolve"] is not None
    assert stats["disputes_by_subject_type"][TRUST_COMPONENT] == 1


# --- US5: журнал ----------------------------------------------------------


def test_history_entry_cannot_be_edited(signed_client):
    """FR5.1: запрет держится кодом, а не договорённостью в документации."""
    setup_candidate(signed_client)
    target = by_type(signed_client, TRUST_COMPONENT)[0]
    open_dispute(signed_client, target["id"])

    with SessionLocal() as db:
        entry = db.query(DisputeHistoryEntry).first()
        entry.note_ru = "подчистил"
        with pytest.raises((AppendOnlyViolation, StatementError)):
            db.commit()


def test_history_entry_cannot_be_deleted(signed_client):
    setup_candidate(signed_client)
    target = by_type(signed_client, TRUST_COMPONENT)[0]
    open_dispute(signed_client, target["id"])

    with SessionLocal() as db:
        entry = db.query(DisputeHistoryEntry).first()
        db.delete(entry)
        with pytest.raises((AppendOnlyViolation, StatementError)):
            db.commit()


def test_no_update_or_delete_path_exists_in_the_code():
    """Проверка не только на уровне БД: таких операций нет и в коде модуля.

    И записи журнала создаются ровно одним способом - `append_history`. Две
    точки записи однажды разойдутся, и журнал перестанет быть журналом.
    """
    from app.routers import xai as xai_router

    for module in (xai_router, moderation_router):
        source = inspect.getsource(module)
        assert "db.delete(" not in source
        assert ".note_ru =" not in source
        assert ".timestamp =" not in source

    xai_source = inspect.getsource(xai_router)
    assert xai_source.count("DisputeHistoryEntry(") == 1
    assert "DisputeHistoryEntry(" not in inspect.getsource(moderation_router)


def test_override_and_history_never_diverge(signed_client, moderator_client):
    """§4.4: запись журнала рождается вместе с правкой и держит её значения."""
    setup_candidate(signed_client)
    component = signed_client.get(TRUST).json()["components"][0]
    previous = str(component["score"])
    case_id = open_dispute(signed_client, component["explanation_id"]).json()["cases"][0]["id"]

    moderator_client.post(
        f"/api/moderation/cases/{case_id}/override",
        json={
            "target_type": overrides.TARGET_TRUST_COMPONENT,
            "target_id": component["component_id"],
            "new_value": "91",
            "rationale_ru": "Подтверждено вне платформы.",
        },
    )

    case = signed_client.get(DISPUTES).json()["cases"][0]
    entry = next(e for e in case["history"] if e["event_type"] == "override_applied")

    assert case["override"]["previous_value"] == previous == entry["before_value"]
    assert case["override"]["new_value"] == "91" == entry["after_value"]
    assert case["override"]["rationale_ru"] == entry["note_ru"]


def test_previous_value_is_precise_enough_to_restore(signed_client, moderator_client):
    """FR5.3: не «балл вырос», а точное прежнее значение конкретного поля."""
    setup_candidate(signed_client)
    component = next(
        c for c in signed_client.get(TRUST).json()["components"] if c["component_id"] == "consistency"
    )
    case_id = open_dispute(signed_client, component["explanation_id"]).json()["cases"][0]["id"]

    moderator_client.post(
        f"/api/moderation/cases/{case_id}/override",
        json={
            "target_type": overrides.TARGET_TRUST_COMPONENT,
            "target_id": "consistency",
            "new_value": "42",
            "rationale_ru": "Учтено пояснение кандидата.",
        },
    )

    override = signed_client.get(DISPUTES).json()["cases"][0]["override"]
    assert override["target_id"] == "consistency"
    assert override["previous_value"] == str(component["score"])


def test_trust_version_grows_and_points_back_to_the_journal(signed_client, moderator_client):
    """FR5.4: версия снимка и журнал - одно и то же, а не два разных счётчика."""
    setup_candidate(signed_client)
    before = signed_client.get(TRUST).json()
    component = before["components"][0]
    case_id = open_dispute(signed_client, component["explanation_id"]).json()["cases"][0]["id"]

    moderator_client.post(
        f"/api/moderation/cases/{case_id}/override",
        json={
            "target_type": overrides.TARGET_TRUST_COMPONENT,
            "target_id": component["component_id"],
            "new_value": "64",
            "rationale_ru": "Учтён внешний источник.",
        },
    )

    after = signed_client.get(TRUST).json()
    assert after["version"] > before["version"]

    trace = after["moderation_trace"][0]
    assert trace["dispute_case_id"] == case_id
    assert trace["history_entry_id"] is not None

    history_ids = [
        entry["id"] for entry in signed_client.get(DISPUTES).json()["cases"][0]["history"]
    ]
    assert trace["history_entry_id"] in history_ids


def test_full_timeline_is_reconstructable(signed_client, moderator_client):
    """Приёмка US5: что заключила система, с чем спорили, кто смотрел, что
    изменилось, на что и почему."""
    setup_candidate(signed_client)
    component = signed_client.get(TRUST).json()["components"][0]
    case_id = open_dispute(
        signed_client, component["explanation_id"], "источник независимый"
    ).json()["cases"][0]["id"]

    moderator_client.post(f"/api/moderation/cases/{case_id}/take")
    moderator_client.post(
        f"/api/moderation/cases/{case_id}/override",
        json={
            "target_type": overrides.TARGET_TRUST_COMPONENT,
            "target_id": component["component_id"],
            "new_value": "88",
            "rationale_ru": "Источник действительно независимый.",
        },
    )

    case = signed_client.get(DISPUTES).json()["cases"][0]

    assert case["conclusion_ru"]
    assert case["candidate_statement"] == "источник независимый"
    assert case["assigned_moderator"]
    assert case["override"]["new_value"] == "88"
    assert case["override"]["rationale_ru"]
    timestamps = [entry["timestamp"] for entry in case["history"]]
    assert timestamps == sorted(timestamps)


# --- границы объёма (§2.2) ------------------------------------------------


def test_no_anomaly_detector_produces_flags(signed_client):
    """§4.5: форма принята, детектора нет - и подделывать его мы не будем."""
    setup_candidate(signed_client)
    signed_client.get(TRUST)
    signed_client.get(PROBE)
    signed_client.get(EXPLANATIONS)

    with SessionLocal() as db:
        assert db.query(AnomalyFlag).count() == 0


def test_anomaly_flag_shape_is_real_even_without_a_producer(signed_client):
    """Принятая форма должна быть настоящей записью, а не комментарием."""
    from app.models import User

    with SessionLocal() as db:
        user = db.query(User).first()
        flag = AnomalyFlag(
            user_id=user.id, flag_type="stylometric_mismatch", subject_evidence_or_answer_id="a_001"
        )
        db.add(flag)
        db.commit()
        assert flag.id is not None
        db.delete(flag)
        db.commit()


def test_recruiter_consent_field_is_prepared_but_unused(signed_client):
    """§2.2: поле есть, рекрутерской стороны нет - согласие всегда выключено."""
    setup_candidate(signed_client)
    assert all(
        item["candidate_consent_for_recruiter_view"] is False for item in explanations(signed_client)
    )


def test_validate_flags_a_silent_empty_evidence_list():
    bad = Explanation(
        id="expl_test",
        subject_type=PROBE_QUESTION_REASON,
        subject_id="q_001",
        conclusion_ru="Компетенция подтверждена.",
        evidence_refs=(),
        generated_by="module_4",
        created_at=None,
    )
    assert validate(bad)
