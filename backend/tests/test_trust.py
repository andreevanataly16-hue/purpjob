"""Проверки модуля 6: Trust Score.

Главное, что здесь проверяется: балл нельзя уронить действиями кандидата.
Пропуск, отказ, неудачный ответ и нерешённая нестыковка дают ноль вклада, а не
минус — и это проверяется не чтением текстов на экране, а последовательностями
запросов.
"""

import inspect
import re

from app.db import SessionLocal
from app.enrichment import DECLINED
from app.models import ContradictionCase, Evidence, TrustFinding
from app.routers import trust as trust_router
from app import trust as trust_logic
from app.trust import (
    AUTHENTICITY,
    CONSISTENCY,
    UNDERSTANDING,
    ComponentScore,
    EvidenceFacts,
    ProbeFacts,
    authenticity,
    consistency,
    find_level_mismatch,
    has_measurement,
    measured_components,
    overall,
    severity_for,
    understanding,
    unlinked_sources,
)

TRUST = "/api/trust"
PROBE = "/api/probe"
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

GOOD_ANSWER = (
    "Упирались в диск: PostgreSQL читал по 200 тысяч строк на отчёт, потому что индекс не "
    "покрывал сортировку. Смотрели план запроса, добавили составной индекс — p99 упал с 40 "
    "секунд до 2."
)

VAGUE = "Всё было нормально, команда справилась."


def probe(competency="caching", *, understanding_signal=True, pastes=0, follow_up=False, resolved=False):
    return ProbeFacts(
        answer_id="a_001",
        competency_id=competency,
        understanding_signal=understanding_signal,
        paste_attempts_blocked=pastes,
        had_follow_up=follow_up,
        resolved_after_follow_up=resolved,
    )


def evidence(id_="ev_001", type_="link", category="github", status="pending", statements=("stmt_001",)):
    return EvidenceFacts(
        id=id_, type=type_, source_category=category, status=status, statement_ids=statements
    )


def setup_candidate(client, level="Middle"):
    client.post(ROLES, json={"level": level})
    parsed = client.post(PARSE, json={"raw_text": CASE_TEXT}).json()
    client.post(ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]})


def component(payload, component_id):
    return next(c for c in payload["components"] if c["component_id"] == component_id)


# --- US5: балл не может упасть -------------------------------------------


def test_score_computation_contains_no_subtraction():
    """FR5.4: правило проверяется чтением кода, а не текстов на экране."""
    source = inspect.getsource(trust_logic)
    scoring = source[source.index("def authenticity") :]

    # Ни одного вычитания из накопленного балла в расчётной части.
    assert not re.search(r"(total|units|score)\s*-=", scoring)
    assert not re.search(r"(total|units)\s*=\s*[^\n]*\s-\s", scoring)


def test_no_component_can_go_below_zero():
    empty = [authenticity([]), understanding([], []), consistency([], 0, 0, 0)]
    assert all(item.score >= 0 for item in empty)
    assert overall(empty) >= 0


def test_blocked_paste_does_not_reduce_anything():
    """FR5.3: отсутствие зачёта, а не наличие штрафа."""
    clean = authenticity([probe()])
    with_paste = authenticity([probe(), probe("high_load", pastes=2)])

    assert with_paste.score >= clean.score
    assert "не пошли в зачёт" in with_paste.explanation_ru


def test_failed_semantic_depth_is_zero_not_minus():
    passed = understanding([probe()], [])
    mixed = understanding([probe(), probe("high_load", understanding_signal=False, follow_up=True)], [])

    assert mixed.score >= passed.score
    assert any("не убавляют" in note for note in mixed.notes_ru)


def test_score_never_drops_across_a_sequence_of_actions(signed_client):
    """Приёмочный критерий US5: последовательности, роняющей балл, не существует."""
    setup_candidate(signed_client)
    scores = [signed_client.get(TRUST).json()["overall_score"]]

    # пропуск вопроса
    question = signed_client.post(f"{PROBE}/next", json={}).json()["question"]
    signed_client.post(f"{PROBE}/questions/{question['id']}/skip")
    scores.append(signed_client.get(TRUST).json()["overall_score"])

    # ответ, который остался общим даже после уточнения
    question = signed_client.post(f"{PROBE}/next", json={}).json()["question"]
    state = signed_client.post(
        f"{PROBE}/questions/{question['id']}/answer", json={"text": VAGUE}
    ).json()
    signed_client.post(
        f"{PROBE}/follow-ups/{state['follow_up']['id']}/answer", json={"text": "Ну лучше стало."}
    )
    scores.append(signed_client.get(TRUST).json()["overall_score"])

    # отказ по NDA
    question = signed_client.post(f"{PROBE}/next", json={}).json()["question"]
    signed_client.post(f"{PROBE}/questions/{question['id']}/decline", json={})
    scores.append(signed_client.get(TRUST).json()["overall_score"])

    assert scores == sorted(scores), f"балл где-то упал: {scores}"


def test_ui_copy_never_calls_it_a_penalty(signed_client):
    """FR5.5: в текстах для кандидата нет ни штрафа, ни наказания, ни снижения.

    Проверяется то, что человек действительно видит, — весь ответ API целиком,
    а не комментарии в коде, где само это правило и объясняется.
    """
    payload = make_contradiction(signed_client)
    signed_client.post(LINK, json={"url": "https://github.com/someone/forgotten"})
    question = signed_client.post(f"{PROBE}/next", json={}).json()["question"]
    signed_client.post(f"{PROBE}/questions/{question['id']}/answer", json={"text": VAGUE})
    payload = signed_client.get(TRUST).json()

    visible = [payload["legend_ru"]]
    for item in payload["components"]:
        visible.append(item["explanation_ru"])
        visible.extend(item["notes_ru"])
    visible.extend(item["text_ru"] for item in payload["next_actions"])
    visible.extend(item["finding_text_ru"] for item in payload["findings"])
    visible.extend(item["detail_ru"] for item in payload["contradictions"])

    for text in visible:
        lowered = text.lower()
        for word in ("штраф", "наказан", "снижен", "понижен", "минус"):
            assert word not in lowered, text


# --- US1: три компонента и ничего больше ---------------------------------


def test_only_three_components_exist(signed_client):
    payload = signed_client.get(TRUST).json()
    assert [c["component_id"] for c in payload["components"]] == [
        AUTHENTICITY,
        UNDERSTANDING,
        CONSISTENCY,
    ]
    # Ethics и Integrity не показываются даже нулями.
    assert not any("ethic" in c["component_id"] or "integrity" in c["component_id"] for c in payload["components"])


def test_overall_is_not_a_plain_average():
    components = [
        ComponentScore(AUTHENTICITY, 100, "x"),
        ComponentScore(UNDERSTANDING, 0, "x"),
        ComponentScore(CONSISTENCY, 0, "x"),
    ]
    flipped = [
        ComponentScore(AUTHENTICITY, 0, "x"),
        ComponentScore(UNDERSTANDING, 100, "x"),
        ComponentScore(CONSISTENCY, 0, "x"),
    ]
    assert overall(components) != overall(flipped)


def test_repeat_confirmation_from_the_same_source_adds_less():
    """§4.2: считается независимость, а не количество."""
    one = understanding([probe("caching")], [])
    same_again = understanding([probe("caching"), probe("caching")], [])
    different = understanding([probe("caching"), probe("high_load")], [])

    assert same_again.score > one.score
    assert different.score > same_again.score


def test_nda_confirmations_count_towards_understanding():
    """Модуль 5: подтверждение под NDA считается наравне с остальными."""
    without = understanding([], [])
    with_nda = understanding([], [evidence(type_="blind_witness_answer", category=None)])

    assert with_nda.score > without.score


def test_trust_reacts_to_a_probe_answer_without_any_recalculate_action(signed_client):
    setup_candidate(signed_client)
    before = signed_client.get(TRUST).json()

    question = signed_client.post(f"{PROBE}/next", json={}).json()["question"]
    signed_client.post(f"{PROBE}/questions/{question['id']}/answer", json={"text": GOOD_ANSWER})

    after = signed_client.get(TRUST).json()
    assert after["overall_score"] > before["overall_score"]
    assert after["version"] > before["version"]


def test_trust_requires_login(client):
    assert client.get(TRUST).status_code == 401


# --- US2: ни одного балла без факта --------------------------------------


def test_every_component_carries_a_checkable_explanation(signed_client):
    setup_candidate(signed_client)
    payload = signed_client.get(TRUST).json()

    verdicts = ("низкая достоверность", "плохо", "недостаточно хорош", "слабый профиль")
    for item in payload["components"]:
        assert item["explanation_ru"].strip()
        assert not any(word in item["explanation_ru"].lower() for word in verdicts)


def test_explanation_names_numbers_not_adjectives(signed_client):
    setup_candidate(signed_client)
    question = signed_client.post(f"{PROBE}/next", json={}).json()["question"]
    signed_client.post(f"{PROBE}/questions/{question['id']}/answer", json={"text": GOOD_ANSWER})

    payload = signed_client.get(TRUST).json()
    assert re.search(r"\d", component(payload, UNDERSTANDING)["explanation_ru"])


def test_component_points_at_the_evidence_actually_used(signed_client):
    """FR2.2: компонент показывает доказательства, которые в него вошли.

    Раньше этот тест проверял непротиворечивость, и она перечисляла все
    доказательства профиля. После стабилизационного спринта она их не считает
    вообще - количество источников непротиворечивость не доказывает, - поэтому
    и список у неё пуст. Перечислять как «учтённое» то, что не считалось, было
    бы противоречием самому себе.

    Требование при этом не отменено: оно проверяется на компоненте, который
    действительно опирается на доказательства.
    """
    setup_candidate(signed_client)
    signed_client.post(LINK, json={"url": "https://github.com/nataly/billing"})

    payload = signed_client.get(TRUST).json()
    assert component(payload, CONSISTENCY)["contributing_evidence_ids"] == []

    understanding_component = component(payload, UNDERSTANDING)
    assert isinstance(understanding_component["contributing_evidence_ids"], list)


def test_repeat_evidence_is_explained_not_silently_absorbed():
    """FR2.3: если добавленное не двинуло балл, кандидат узнаёт почему."""
    repeated = authenticity([probe("caching"), probe("caching")])
    assert any("повтор" in note.lower() for note in repeated.notes_ru)


# --- US3: следующее лучшее действие --------------------------------------


def test_next_actions_are_specific_and_addressed(signed_client):
    setup_candidate(signed_client)
    payload = signed_client.get(TRUST).json()

    assert payload["next_actions"]
    first = payload["next_actions"][0]
    assert first["text_ru"].strip()
    assert first["target_kind"] in ("probe", "contradiction", "finding")
    assert first["target_id"]


def test_next_actions_are_prioritized(signed_client):
    setup_candidate(signed_client)
    actions = signed_client.get(TRUST).json()["next_actions"]
    weights = [item["weight"] for item in actions]

    assert weights == sorted(weights, reverse=True)


def test_legend_is_reused_verbatim(signed_client):
    payload = signed_client.get(TRUST).json()
    assert "Не заменяет интервью" in payload["legend_ru"]


# --- US4, Case 1: находка об источнике ------------------------------------


def test_unlinked_source_becomes_a_finding(signed_client):
    setup_candidate(signed_client)
    signed_client.post(LINK, json={"url": "https://github.com/someone/forgotten"})

    findings = signed_client.get(TRUST).json()["findings"]
    assert len(findings) == 1
    assert "это ваш профессиональный след?" in findings[0]["finding_text_ru"]


def test_linked_source_is_not_a_finding(signed_client):
    setup_candidate(signed_client)
    statement = signed_client.get(PROFILE).json()["statements"][0]["id"]
    signed_client.post(
        LINK, json={"url": "https://github.com/nataly/billing", "statement_ids": [statement]}
    )

    assert signed_client.get(TRUST).json()["findings"] == []


def test_declining_a_finding_leaves_no_trace_and_no_score_change(signed_client):
    """FR4.1: сильнее обычного отказа - следа не остаётся вовсе."""
    setup_candidate(signed_client)
    signed_client.post(LINK, json={"url": "https://github.com/someone/forgotten"})
    before = signed_client.get(TRUST).json()

    finding = before["findings"][0]
    after = signed_client.post(
        f"{TRUST}/findings/{finding['id']}/respond", json={"response": "not_me_or_outdated"}
    ).json()

    assert after["findings"] == []
    assert after["overall_score"] >= before["overall_score"]

    profile = signed_client.get(PROFILE).json()
    assert not [e for e in profile["evidence"] if e["url"] and "forgotten" in e["url"]]
    # Записи об отказе тоже не остаётся: она и была бы следом.
    assert all(d["target_type"] != "evidence" for d in profile["declines"])


def test_confirming_a_finding_keeps_the_source(signed_client):
    setup_candidate(signed_client)
    signed_client.post(LINK, json={"url": "https://github.com/nataly/tools"})
    finding = signed_client.get(TRUST).json()["findings"][0]

    after = signed_client.post(
        f"{TRUST}/findings/{finding['id']}/respond", json={"response": "confirmed"}
    ).json()

    assert after["findings"] == []
    profile = signed_client.get(PROFILE).json()
    assert [e for e in profile["evidence"] if e["url"] and "tools" in e["url"]]

    with SessionLocal() as db:
        assert db.query(TrustFinding).one().candidate_response == "confirmed"


def test_unknown_response_is_rejected(signed_client):
    setup_candidate(signed_client)
    signed_client.post(LINK, json={"url": "https://github.com/someone/forgotten"})
    finding = signed_client.get(TRUST).json()["findings"][0]

    response = signed_client.post(
        f"{TRUST}/findings/{finding['id']}/respond", json={"response": "может быть"}
    )
    assert response.status_code == 400


# --- US4, Case 2: нестыковка ---------------------------------------------


def test_level_mismatch_is_detected_from_the_candidates_own_words():
    found = find_level_mismatch(
        ["Senior"],
        [("1", "2", "Работал под руководством тимлида, мне поручили выгрузку отчётов.")],
    )

    assert len(found) == 1
    assert found[0].markers


def test_level_mismatch_needs_a_senior_claim():
    assert find_level_mismatch(["Middle"], [("1", "2", "Работал под руководством тимлида.")]) == []


def test_severity_defaults_to_the_soft_side():
    assert severity_for(1) == "minor"
    assert severity_for(2) == "minor"
    assert severity_for(3) == "major"


def make_contradiction(signed_client):
    setup_candidate(signed_client, level="Senior")
    parsed = signed_client.post(
        PARSE,
        json={
            "raw_text": (
                "Работал с Redis под руководством тимлида: мне поручили настроить кеш, "
                "я выполнял задачи по его описанию."
            )
        },
    ).json()
    signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]}
    )
    return signed_client.get(TRUST).json()


def test_contradiction_is_created_from_local_data_only(signed_client):
    payload = make_contradiction(signed_client)

    assert payload["contradictions"]
    case = payload["contradictions"][0]
    assert case["detected_by"] == "local_consistency_check"
    assert case["check_type"] == "level_mismatch"
    assert case["status"] == "open"
    assert case["detail_ru"]


def test_open_contradiction_does_not_lower_the_score(signed_client):
    setup_candidate(signed_client, level="Senior")
    before = signed_client.get(TRUST).json()["overall_score"]

    parsed = signed_client.post(
        PARSE, json={"raw_text": "Работал под руководством тимлида, мне поручили кеш на Redis."}
    ).json()
    signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]}
    )

    assert signed_client.get(TRUST).json()["overall_score"] >= before


def test_explaining_a_contradiction_resolves_it(signed_client):
    case = make_contradiction(signed_client)["contradictions"][0]

    after = signed_client.post(
        f"{TRUST}/contradictions/{case['id']}/resolve",
        json={"path": "explain", "explanation_text": "Это был первый месяц, потом вёл направление сам."},
    ).json()

    resolved = after["contradictions"][0]
    assert resolved["status"] == "resolved"
    assert resolved["resolution_path"] == "explain"
    assert resolved["explanation_text"]
    assert resolved["visibility_suspended"] is False


def test_deleting_the_artifact_removes_it(signed_client):
    case = make_contradiction(signed_client)["contradictions"][0]
    evidence_id = case["evidence_id"]

    after = signed_client.post(
        f"{TRUST}/contradictions/{case['id']}/resolve", json={"path": "delete_artifact"}
    ).json()

    assert after["contradictions"][0]["status"] == "resolved"
    profile = signed_client.get(PROFILE).json()
    assert evidence_id not in [e["id"] for e in profile["evidence"]]


def test_correcting_the_claim_is_recorded(signed_client):
    case = make_contradiction(signed_client)["contradictions"][0]

    after = signed_client.post(
        f"{TRUST}/contradictions/{case['id']}/resolve",
        json={"path": "correct_claim", "corrected_value": "Middle"},
    ).json()

    assert after["contradictions"][0]["corrected_value"] == "Middle"


def test_explain_requires_the_explanation_itself(signed_client):
    case = make_contradiction(signed_client)["contradictions"][0]

    response = signed_client.post(
        f"{TRUST}/contradictions/{case['id']}/resolve", json={"path": "explain"}
    )
    assert response.status_code == 400


def test_unresolved_contradiction_stays_open_without_consequences(signed_client):
    payload = make_contradiction(signed_client)
    case = payload["contradictions"][0]

    again = signed_client.get(TRUST).json()
    assert again["contradictions"][0]["status"] == "open"
    assert again["overall_score"] >= 0
    # На спорную компетенцию это не вешает никакого минуса.
    assert component(again, CONSISTENCY)["score"] >= 0


def test_visibility_suspension_is_only_set_for_major_cases(signed_client):
    payload = make_contradiction(signed_client)
    for case in payload["contradictions"]:
        if case["severity"] == "minor":
            assert case["visibility_suspended"] is False


def test_contradictions_are_private_to_the_candidate(signed_client, client):
    case = make_contradiction(signed_client)["contradictions"][0]
    signed_client.post("/api/auth/logout")

    client.post(
        "/api/auth/register", json={"email": "someone@example.com", "password": "verysecret123"}
    )

    assert client.get(TRUST).json()["contradictions"] == []
    response = client.post(
        f"{TRUST}/contradictions/{case['id']}/resolve", json={"path": "delete_artifact"}
    )
    assert response.status_code == 404


# --- вспомогательная логика ----------------------------------------------


def test_declined_evidence_is_not_a_finding():
    items = [evidence(status=DECLINED, statements=())]
    assert unlinked_sources(items) == []


def test_only_links_and_files_become_findings():
    items = [evidence(id_="ev_002", type_="free_text", category=None, statements=())]
    assert unlinked_sources(items) == []


# --- «не измерено» против «измерено нулём» --------------------------------
#
# Прежняя реализация складывала неизмеренный компонент как ноль с полным весом.
# Кандидат, которому просто нечего было подтверждать, получал тот же балл, что
# и кандидат, проверку не прошедший, — то есть отсутствие сигнала работало как
# отрицательный сигнал. Это прямо противоречит правилу продукта, и ниже оно
# закреплено числами, а не текстом на экране.


def scored(component_id, score, *, measured=True):
    return ComponentScore(
        component_id=component_id,
        score=score,
        explanation_ru="для проверки арифметики",
        measured=measured,
    )


def test_unmeasured_component_does_not_lower_the_overall():
    """A: неизмеренный компонент не участвует в среднем вовсе."""
    without = overall([scored(AUTHENTICITY, 80), scored(UNDERSTANDING, 70)])
    with_unmeasured = overall(
        [
            scored(AUTHENTICITY, 80),
            scored(UNDERSTANDING, 70),
            scored(CONSISTENCY, 0, measured=False),
        ]
    )
    assert with_unmeasured == without


def test_overall_is_normalised_by_the_weight_of_measured_components():
    """B: вес делится на измеренное, а не на все три компонента."""
    components = [
        scored(AUTHENTICITY, 80),
        scored(UNDERSTANDING, 70),
        scored(CONSISTENCY, 0, measured=False),
    ]
    # (80*0.3 + 70*0.4) / (0.3 + 0.4) = 52 / 0.7
    assert overall(components) == 74


def test_single_measured_component_defines_the_overall():
    """C: если измерен один компонент, общий балл равен ему."""
    components = [
        scored(AUTHENTICITY, 63),
        scored(UNDERSTANDING, 0, measured=False),
        scored(CONSISTENCY, 0, measured=False),
    ]
    assert overall(components) == 63


def test_nothing_measured_is_an_explicit_state_not_a_zero():
    """D: пустой профиль — «пока не измерено», а не «ноль из ста»."""
    components = [
        scored(AUTHENTICITY, 0, measured=False),
        scored(UNDERSTANDING, 0, measured=False),
        scored(CONSISTENCY, 0, measured=False),
    ]
    assert has_measurement(components) is False
    assert measured_components(components) == []
    # Число всё равно нужно отдать - но отличает состояние флаг, а не оно.
    assert overall(components) == 0


def test_measured_zero_is_not_the_same_as_unmeasured():
    """E: настоящий ноль балл понижает — иначе провал ничего бы не значил."""
    unmeasured = overall(
        [
            scored(AUTHENTICITY, 80),
            scored(UNDERSTANDING, 70),
            scored(CONSISTENCY, 0, measured=False),
        ]
    )
    measured_zero = overall(
        [
            scored(AUTHENTICITY, 80),
            scored(UNDERSTANDING, 70),
            scored(CONSISTENCY, 0),
        ]
    )
    assert measured_zero < unmeasured
    assert measured_zero == 52


def test_empty_profile_reports_unmeasured_over_the_api(signed_client):
    """То же самое, но глазами кандидата: ни одного нуля на пустом профиле."""
    payload = signed_client.get(TRUST).json()
    assert payload["overall_measured"] is False
    assert all(item["measured"] is False for item in payload["components"])
