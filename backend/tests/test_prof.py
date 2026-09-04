"""Проверки модуля 3: PROF.индекс, белые пятна и режим Self-Audit."""

import pytest

from app.enrichment import LIMITED, MEDIUM, NOT_STARTED, STRONG
from app.prof import (
    COMPLEXITY_MIN_DESCRIPTION,
    DEPTH_REFERENCE,
    STATUS_SCORE,
    StatementView,
    compute_results,
    compute_snapshot,
)
from app.reference import LEVELS, PROFILES, SEGMENT, get_profile

PROF = "/api/prof"
ROLES = "/api/prof/roles"
VISIBILITY = "/api/prof/visibility"
PARSE = "/api/profile/parse"
ACCEPT = "/api/profile/statements/accept"
LINK = "/api/profile/evidence/link"

CASE = (
    "Переписал биллинг с нуля на Python, вынес его в отдельный микросервис. "
    "Под нагрузкой в 3000 rps старая схема не держала, поэтому добавили Redis "
    "и переработали индексы в PostgreSQL. Ускорил отчёты с 40 секунд до 2."
)


def view(skill, status, *, ru=None, reason="Причина.", artifacts=0, text=0):
    return StatementView(
        id="stmt_001",
        skill_name=skill,
        skill_name_ru=ru or skill,
        status=status,
        reason=reason,
        artifact_count=artifacts,
        longest_text=text,
    )


def component(snapshot, competency_id):
    return next(c for c in snapshot["components"] if c["competency_id"] == competency_id)


# --- эталонные профили ----------------------------------------------------


@pytest.mark.parametrize("level", LEVELS)
def test_reference_profile_weights_sum_to_one(level):
    profile = get_profile(level)
    assert round(sum(c.weight for c in profile.competencies), 9) == 1.0


def test_exactly_two_reference_profiles_ship_with_mvp():
    assert set(PROFILES) == set(LEVELS)
    assert all(profile.segment == SEGMENT for profile in PROFILES.values())


def test_senior_asks_more_of_task_complexity_than_middle():
    def complexity_weight(level):
        return sum(
            c.weight for c in get_profile(level).competencies if c.category == "task_complexity"
        )

    assert complexity_weight("Senior") > complexity_weight("Middle")


def test_profiles_cover_only_hard_skills_and_task_complexity():
    # §7 FRD: soft skills в индексе не появляются ни под каким видом.
    for profile in PROFILES.values():
        assert {c.category for c in profile.competencies} == {"hard_skill", "task_complexity"}


# --- расчёт индекса -------------------------------------------------------


def test_empty_profile_scores_zero_and_is_all_white_spots():
    profile = get_profile("Middle")
    snapshot = compute_snapshot(profile, [])

    assert snapshot["overall_score"] == 0
    assert len(snapshot["white_spots"]) == len(profile.competencies)
    assert all(c["status"] == NOT_STARTED for c in snapshot["components"])


def test_score_is_status_times_weight():
    profile = get_profile("Middle")
    snapshot = compute_snapshot(profile, [view("Python", MEDIUM)])

    core = component(snapshot, "core_language")
    assert core["status"] == MEDIUM
    assert core["score_contribution"] == pytest.approx(STATUS_SCORE[MEDIUM] * core["weight"])
    assert snapshot["overall_score"] == round(STATUS_SCORE[MEDIUM] * core["weight"] * 100)


def test_fully_strong_profile_scores_one_hundred():
    profile = get_profile("Senior")
    statements = [
        view(key, STRONG)
        for competency in profile.competencies
        for key in competency.taxonomy_keys
    ]

    assert compute_snapshot(profile, statements)["overall_score"] == 100


def test_competency_with_several_keys_takes_the_strongest():
    # «Python или Go»: закрывать оба необязательно.
    profile = get_profile("Middle")
    snapshot = compute_snapshot(profile, [view("Python", LIMITED), view("Go", STRONG)])

    assert component(snapshot, "core_language")["status"] == STRONG


def test_same_evidence_scores_differently_for_middle_and_senior():
    statements = [view("Python", STRONG)]
    middle = compute_snapshot(get_profile("Middle"), statements)["overall_score"]
    senior = compute_snapshot(get_profile("Senior"), statements)["overall_score"]

    assert middle > senior, "у Senior тот же навык весит меньше"


def test_status_is_never_shown_without_a_reason():
    # FR2.2: голых статусов в ответе быть не может.
    snapshot = compute_snapshot(get_profile("Middle"), [view("Python", MEDIUM)])
    assert all(c["reason"].strip() for c in snapshot["components"])


def test_unmapped_competency_explains_itself_too():
    snapshot = compute_snapshot(get_profile("Middle"), [])
    assert "нет ни одной компетенции" in component(snapshot, "testing")["reason"]


def test_reason_names_the_skill_when_competency_merges_several():
    snapshot = compute_snapshot(
        get_profile("Middle"), [view("Go", MEDIUM, ru="Go", reason="Есть подтверждение.")]
    )
    assert component(snapshot, "core_language")["reason"].startswith("Go:")


# --- FR1.5: эвристика сложности задач -------------------------------------


def test_complexity_heuristic_lifts_limited_to_medium_with_artifact_and_details():
    long_text = "и" * COMPLEXITY_MIN_DESCRIPTION
    snapshot = compute_snapshot(
        get_profile("Middle"),
        [view("High load systems", LIMITED, artifacts=1, text=len(long_text))],
    )

    high_load = component(snapshot, "high_load")
    assert high_load["status"] == MEDIUM
    assert high_load["heuristic_applied"] is True
    assert "эвристика" in high_load["reason"]


def test_complexity_heuristic_needs_both_artifact_and_description():
    profile = get_profile("Middle")
    only_artifact = compute_snapshot(
        profile, [view("High load systems", LIMITED, artifacts=1, text=10)]
    )
    only_text = compute_snapshot(
        profile, [view("High load systems", LIMITED, text=COMPLEXITY_MIN_DESCRIPTION)]
    )

    assert component(only_artifact, "high_load")["status"] == LIMITED
    assert component(only_text, "high_load")["status"] == LIMITED


def test_heuristic_never_touches_hard_skills():
    snapshot = compute_snapshot(
        get_profile("Middle"),
        [view("Python", LIMITED, artifacts=3, text=COMPLEXITY_MIN_DESCRIPTION * 3)],
    )

    assert component(snapshot, "core_language")["status"] == LIMITED


def test_heuristic_cannot_invent_strong():
    # FR2.4: strong остаётся правилом модуля 2 - два разных источника.
    snapshot = compute_snapshot(
        get_profile("Middle"),
        [view("Distributed systems", MEDIUM, artifacts=5, text=1000)],
    )

    assert component(snapshot, "distributed_systems")["status"] == MEDIUM


# --- радар ----------------------------------------------------------------


def test_radar_has_a_point_per_competency_with_both_values():
    profile = get_profile("Senior")
    snapshot = compute_snapshot(profile, [view("Python", MEDIUM)])

    assert len(snapshot["radar_points"]) == len(profile.competencies)

    core = next(p for p in snapshot["radar_points"] if p["competency_id"] == "core_language")
    assert core["candidate_value"] == STATUS_SCORE[MEDIUM]
    assert core["reference_value"] == DEPTH_REFERENCE["deep"]


# --- US3: белые пятна -----------------------------------------------------


def test_white_spots_are_only_not_started_and_limited():
    snapshot = compute_snapshot(
        get_profile("Middle"), [view("Python", STRONG), view("Testing", LIMITED)]
    )

    assert "core_language" not in snapshot["white_spots"]
    assert "testing" in snapshot["white_spots"]


def test_white_spots_are_ordered_by_weight():
    profile = get_profile("Middle")
    snapshot = compute_snapshot(profile, [])
    weights = [
        next(c.weight for c in profile.competencies if c.competency_id == spot)
        for spot in snapshot["white_spots"]
    ]

    assert weights == sorted(weights, reverse=True)


def test_closing_a_gap_removes_it_from_white_spots():
    profile = get_profile("Middle")
    before = compute_snapshot(profile, [])
    after = compute_snapshot(profile, [view("Testing", STRONG)])

    assert "testing" in before["white_spots"]
    assert "testing" not in after["white_spots"]


# --- API ------------------------------------------------------------------


def test_prof_requires_login(client):
    assert client.get(PROF).status_code == 401


def test_profile_starts_hidden_with_no_roles(signed_client):
    payload = signed_client.get(PROF).json()

    assert payload["snapshots"] == []
    assert payload["visibility"]["mode"] == "hidden"
    assert payload["available_levels"] == list(LEVELS)


def test_candidate_declares_a_level_and_gets_an_index(signed_client):
    response = signed_client.post(ROLES, json={"level": "Middle"})

    assert response.status_code == 201
    snapshot = response.json()["snapshots"][0]
    assert snapshot["level"] == "Middle"
    assert snapshot["segment"] == SEGMENT
    assert snapshot["overall_score"] == 0
    assert snapshot["components"], "эталон подгрузился"


def test_unknown_level_is_rejected_with_an_explanation(signed_client):
    response = signed_client.post(ROLES, json={"level": "Junior"})

    assert response.status_code == 400
    assert "эталон" in response.json()["detail"].lower()
    assert signed_client.get(PROF).json()["snapshots"] == []


def test_declaring_the_same_level_twice_changes_nothing(signed_client):
    signed_client.post(ROLES, json={"level": "Senior"})
    payload = signed_client.post(ROLES, json={"level": "Senior"}).json()

    assert len(payload["snapshots"]) == 1


def test_both_levels_can_be_tracked_at_once(signed_client):
    signed_client.post(ROLES, json={"level": "Middle"})
    payload = signed_client.post(ROLES, json={"level": "Senior"}).json()

    assert [s["level"] for s in payload["snapshots"]] == ["Middle", "Senior"]
    assert len(payload["snapshots"]) <= payload["max_roles"]


def test_role_can_be_dropped(signed_client):
    signed_client.post(ROLES, json={"level": "Middle"})
    assert signed_client.delete(f"{ROLES}/Middle").json()["snapshots"] == []


def test_index_reflects_module_two_evidence_without_any_recalculate_action(signed_client):
    """Приёмочный критерий US1: индекс пересчитывается сам после изменений в
    модуле 2 - отдельной кнопки «пересчитать» нет."""
    signed_client.post(ROLES, json={"level": "Middle"})
    assert signed_client.get(PROF).json()["snapshots"][0]["overall_score"] == 0

    parsed = signed_client.post(PARSE, json={"raw_text": CASE}).json()
    signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]}
    )

    after = signed_client.get(PROF).json()["snapshots"][0]
    assert after["overall_score"] > 0

    core = component(after, "core_language")
    assert core["status"] == LIMITED
    assert core["statement_ids"], "компетенция связана с утверждением модуля 2"


def test_new_evidence_raises_the_index_and_shrinks_white_spots(signed_client):
    signed_client.post(ROLES, json={"level": "Middle"})
    parsed = signed_client.post(PARSE, json={"raw_text": CASE}).json()
    profile = signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]}
    ).json()

    before = signed_client.get(PROF).json()["snapshots"][0]
    python_statement = next(s["id"] for s in profile["statements"] if s["skill_name"] == "Python")

    signed_client.post(
        LINK,
        json={
            "url": "https://github.com/nataly/billing",
            "statement_ids": [python_statement],
        },
    )

    after = signed_client.get(PROF).json()["snapshots"][0]
    assert after["overall_score"] > before["overall_score"]
    assert "core_language" in before["white_spots"]
    assert "core_language" not in after["white_spots"]


def test_probe_result_enters_the_index_without_model_changes(signed_client):
    """FR1.6: точка входа для будущего Contextual Probe.

    Компетенция, которой кандидат не заявлял, приходит как обычное утверждение
    модуля 2 - и сразу попадает в индекс. Ничего дорабатывать не придётся.
    """
    signed_client.post(ROLES, json={"level": "Middle"})
    assert "testing" in signed_client.get(PROF).json()["snapshots"][0]["white_spots"]

    # Так же результат ответа на вопрос создаст утверждение в модуле 2.
    signed_client.post("/api/profile/statements", json={"skill_name_ru": "Тестирование"})
    signed_client.post(
        "/api/profile/evidence/blind-witness",
        json={
            "answer": "Покрывали контрактными тестами границы сервиса, а не проценты строк.",
            "statement_ids": [
                next(
                    s["id"]
                    for s in signed_client.get("/api/profile").json()["statements"]
                    if s["skill_name"] == "Testing"
                )
            ],
        },
    )

    snapshot = signed_client.get(PROF).json()["snapshots"][0]
    assert component(snapshot, "testing")["status"] == MEDIUM
    assert "testing" not in snapshot["white_spots"]


# --- US4: Self-Audit ------------------------------------------------------


def test_visibility_switches_only_by_candidate_action(signed_client):
    signed_client.post(ROLES, json={"level": "Middle"})

    payload = signed_client.put(VISIBILITY, json={"mode": "visible"}).json()
    assert payload["visibility"]["mode"] == "visible"

    payload = signed_client.put(VISIBILITY, json={"mode": "hidden"}).json()
    assert payload["visibility"]["mode"] == "hidden"


def test_third_visibility_mode_does_not_exist(signed_client):
    response = signed_client.put(VISIBILITY, json={"mode": "whitelist"})

    assert response.status_code == 400
    assert signed_client.get(PROF).json()["visibility"]["mode"] == "hidden"


def test_hidden_mode_is_the_full_module_not_a_preview(signed_client):
    """FR4.2: в режиме Self-Audit доступно ровно то же, что и в открытом."""
    signed_client.post(ROLES, json={"level": "Middle"})
    parsed = signed_client.post(PARSE, json={"raw_text": CASE}).json()
    signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]}
    )

    hidden = signed_client.get(PROF).json()
    assert hidden["visibility"]["mode"] == "hidden"

    signed_client.put(VISIBILITY, json={"mode": "visible"})
    visible = signed_client.get(PROF).json()

    assert hidden["snapshots"] == visible["snapshots"]


def test_roles_and_visibility_are_private_to_the_candidate(signed_client, client):
    signed_client.post(ROLES, json={"level": "Middle"})
    signed_client.put(VISIBILITY, json={"mode": "visible"})
    signed_client.post("/api/auth/logout")

    client.post(
        "/api/auth/register", json={"email": "another@example.com", "password": "verysecret123"}
    )
    payload = client.get(PROF).json()

    assert payload["snapshots"] == []
    assert payload["visibility"]["mode"] == "hidden"
