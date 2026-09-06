"""Проверки модуля 14: обратная связь рекрутера и калибровка.

Главные два свойства, которые легко потерять при доработке:

* отзыв рекрутера не меняет балл кандидата ни одним путём;
* формулы сами не подстраиваются — величину меняет человек, под запись.
"""

import inspect

import pytest
from sqlalchemy.exc import StatementError

from app import calibration
from app.db import SessionLocal
from app.models import (
    AppendOnlyViolation,
    CalibrationConstantChangeLog,
    ComponentFeedback,
    DisputeCase,
    RecruiterFeedback,
)
from app.routers import calibration as router

CAL = "/api/calibration"
FEEDBACK = "/api/calibration/feedback"
SEARCH = "/api/recruiter/search"
QUEUE = "/api/moderation/queue"

CANDIDATE = "cand_001"
VACANCY = "vac_001"


def detail(client, candidate_id=CANDIDATE, vacancy_id=VACANCY):
    return client.get(
        f"/api/recruiter/candidates/{candidate_id}", params={"vacancy_id": vacancy_id}
    ).json()


def send(client, outcome, candidate_id=CANDIDATE, components=None):
    body = {
        "candidate_id": candidate_id,
        "vacancy_id": VACANCY,
        "relevance_outcome": outcome,
    }
    if components:
        body["component_feedback"] = components
    return client.post(FEEDBACK, json=body)


def verdict(explanation_id, value, subject_type="trust_component", subject_id="understanding"):
    return {
        "explanation_id": explanation_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "verdict": value,
    }


# --- US1: один ответ, и он ничего не меняет -------------------------------


def test_single_action_is_a_complete_submission(signed_client, recruiter_client):
    """FR1.2: подробности необязательны, иначе базовым действием не пользуются."""
    response = send(recruiter_client, calibration.CONFIRMED_RELEVANT)

    assert response.status_code == 201
    submitted = response.json()["submitted"]
    assert submitted["relevance_outcome_ru"] == "Да"
    assert submitted["component_count"] == 0


def test_three_named_outcomes_and_nothing_else(signed_client, recruiter_client):
    assert calibration.OUTCOMES == ("confirmed_relevant", "not_relevant", "partially_relevant")
    assert [calibration.OUTCOME_RU[value] for value in calibration.OUTCOMES] == [
        "Да",
        "Нет",
        "Частично",
    ]
    assert send(recruiter_client, "maybe").status_code == 400


def test_prompt_matches_the_agreed_wording(signed_client, recruiter_client):
    state = recruiter_client.get(f"{FEEDBACK}/{CANDIDATE}").json()
    assert state["prompt_ru"] == "Кандидат оказался релевантен после собеседования?"
    assert state["component_prompt_ru"] == (
        "Эта информация оказалась полезной или вводящей в заблуждение?"
    )


def test_feedback_never_changes_the_candidates_scores(signed_client, recruiter_client):
    """FR1.3: мнение одного рекрутера не должно уметь уронить чей-то профиль."""
    before = detail(recruiter_client)

    for _ in range(3):
        send(recruiter_client, calibration.NOT_RELEVANT)

    after = detail(recruiter_client)
    assert after["trust_score"] == before["trust_score"]
    assert after["prof_index"] == before["prof_index"]
    assert after["match_score"] == before["match_score"]
    assert after["trust_components"] == before["trust_components"]


def test_module_has_no_write_path_into_candidate_data():
    """То же правило кодом: соблазн «чуть-чуть учесть отзыв» слишком велик."""
    source = inspect.getsource(router)

    for forbidden in ("Statement(", "Evidence(", "TrustFinding(", "ProfRole("):
        assert forbidden not in source
    assert "ModeratorOverride(" not in source


def test_scores_are_frozen_at_the_moment_of_feedback(signed_client, recruiter_client):
    """Сверять вывод с исходом нужно по тому, что система утверждала тогда."""
    send(recruiter_client, calibration.CONFIRMED_RELEVANT)

    with SessionLocal() as db:
        row = db.query(RecruiterFeedback).first()
        assert row.trust_score_at_feedback > 0
        assert row.prof_score_at_feedback > 0


def test_feedback_for_an_unknown_candidate_is_refused(signed_client, recruiter_client):
    assert send(recruiter_client, calibration.CONFIRMED_RELEVANT, "cand_999").status_code == 404


# --- US2: отметки на конкретных выводах -----------------------------------


def test_component_feedback_is_addressed_by_explanation_id(signed_client, recruiter_client):
    """FR2.1: тем же идентификатором, каким адресуется всё остальное."""
    component = detail(recruiter_client)["trust_components"][0]
    assert component["explanation_id"]

    send(
        recruiter_client,
        calibration.PARTIALLY_RELEVANT,
        components=[verdict(component["explanation_id"], calibration.MISLEADING)],
    )

    state = recruiter_client.get(f"{FEEDBACK}/{CANDIDATE}").json()
    assert state["component_verdicts"][component["explanation_id"]] == calibration.MISLEADING


def test_prof_competencies_are_addressable_too(signed_client, recruiter_client):
    """FR2.2: отметка ставится там же, где рекрутер видел этот вывод."""
    component = detail(recruiter_client)["prof_components"][0]
    assert component["explanation_id"]


def test_several_marks_fit_one_submission(signed_client, recruiter_client):
    """FR2.3: рекрутер не ограничен одной отметкой на кандидата."""
    components = detail(recruiter_client)["trust_components"]
    marks = [
        verdict(item["explanation_id"], calibration.USEFUL, subject_id=item["component_id"])
        for item in components
    ]

    send(recruiter_client, calibration.CONFIRMED_RELEVANT, components=marks)

    with SessionLocal() as db:
        assert db.query(ComponentFeedback).count() == len(components)


def test_unknown_verdict_is_refused(signed_client, recruiter_client):
    component = detail(recruiter_client)["trust_components"][0]
    response = send(
        recruiter_client,
        calibration.CONFIRMED_RELEVANT,
        components=[verdict(component["explanation_id"], "so-so")],
    )
    assert response.status_code == 400


# --- US3: сводка и осознанное изменение -----------------------------------


def test_one_comment_never_raises_a_systematic_flag(signed_client, moderator_client, recruiter_client):
    """FR3.1: флаг требует и выборки, и доли — иначе это шум, а не закономерность."""
    component = detail(recruiter_client)["trust_components"][0]
    send(
        recruiter_client,
        calibration.NOT_RELEVANT,
        components=[verdict(component["explanation_id"], calibration.MISLEADING)],
    )

    insight = moderator_client.get(CAL).json()["insights"][0]
    assert insight["misleading_rate"] == 1.0
    assert insight["sample_size"] == 1
    assert insight["flagged_for_review"] is False


def test_flag_appears_only_with_enough_evidence():
    verdicts = [calibration.MISLEADING] * calibration.MIN_SAMPLE_SIZE
    enough = calibration.insight_for("trust_component", "understanding", verdicts)
    assert enough.flagged_for_review is True

    mostly_fine = calibration.insight_for(
        "trust_component",
        "understanding",
        [calibration.USEFUL] * calibration.MIN_SAMPLE_SIZE,
    )
    assert mostly_fine.flagged_for_review is False


def test_thresholds_are_named_constants():
    """Та же договорённость, что во всём проекте: величины не вшиты в строку."""
    source = inspect.getsource(calibration)
    assert "MIN_SAMPLE_SIZE = " in source
    assert "MISLEADING_RATE_THRESHOLD = " in source
    assert "HIGH_SCORE_THRESHOLD = " in source


def test_agreement_rule_is_a_swappable_function():
    """§4.3: как считать «частично» — само по себе калибровочное решение."""
    assert calibration.outcomes_agree(calibration.CONFIRMED_RELEVANT, 90) is True
    assert calibration.outcomes_agree(calibration.CONFIRMED_RELEVANT, 10) is False
    assert calibration.outcomes_agree(calibration.NOT_RELEVANT, 10) is True
    # Частичный исход не натягивается ни на один лагерь.
    assert calibration.outcomes_agree(calibration.PARTIALLY_RELEVANT, 90) is None


def test_trust_accuracy_ignores_partial_outcomes(signed_client, moderator_client, recruiter_client):
    send(recruiter_client, calibration.PARTIALLY_RELEVANT)

    accuracy = moderator_client.get(CAL).json()["accuracy"]
    assert accuracy["total_feedback_count"] == 1
    assert accuracy["comparable_count"] == 0
    assert accuracy["trust_accuracy_pct"] is None


def test_trust_accuracy_is_computed_from_real_feedback(signed_client, moderator_client, recruiter_client):
    send(recruiter_client, calibration.CONFIRMED_RELEVANT)

    accuracy = moderator_client.get(CAL).json()["accuracy"]
    assert accuracy["comparable_count"] == 1
    assert accuracy["trust_accuracy_pct"] in (0, 100)


def test_changing_a_constant_requires_a_reason(signed_client, moderator_client):
    """FR3.3: обязательность стоит в схеме, а не «в форме на экране»."""
    without = moderator_client.post(
        f"{CAL}/changes",
        json={"constant_ref": "module8.decay_countdown_days", "new_value": "14", "rationale_ru": ""},
    )
    assert without.status_code == 422

    with_reason = moderator_client.post(
        f"{CAL}/changes",
        json={
            "constant_ref": "module8.decay_countdown_days",
            "new_value": "14",
            "rationale_ru": "Три дня для рынка труда слишком мало: за неделю профиль не устаревает.",
        },
    )
    assert with_reason.status_code == 201

    change = with_reason.json()["changes"][0]
    assert change["previous_value"] == "3"
    assert change["new_value"] == "14"
    assert change["based_on_feedback_count"] >= 0


def test_only_listed_constants_can_be_changed(signed_client, moderator_client):
    """Список закрытый: «поменять что угодно по имени» — способ обойти запись."""
    refused = moderator_client.post(
        f"{CAL}/changes",
        json={
            "constant_ref": "module6.overall_score",
            "new_value": "100",
            "rationale_ru": "хочется",
        },
    )
    assert refused.status_code == 400


def test_no_automatic_recalibration_anywhere():
    """FR3.3: подстройки формул по обратной связи не существует."""
    source = inspect.getsource(router)

    # Значения констант читаются, но не присваиваются.
    assert "STATUS_SCORE =" not in source
    assert "MIN_MATCH_SCORE_TO_NOTIFY =" not in source
    assert "DECAY_COUNTDOWN_DAYS =" not in source


def test_change_log_cannot_be_edited(signed_client, moderator_client):
    moderator_client.post(
        f"{CAL}/changes",
        json={
            "constant_ref": "module14.min_sample_size",
            "new_value": "10",
            "rationale_ru": "Пять отзывов — слишком мало для вывода о закономерности.",
        },
    )

    with SessionLocal() as db:
        row = db.query(CalibrationConstantChangeLog).first()
        row.rationale_ru = "переписал"
        with pytest.raises((AppendOnlyViolation, StatementError)):
            db.commit()


def test_change_log_cannot_be_deleted(signed_client, moderator_client):
    moderator_client.post(
        f"{CAL}/changes",
        json={
            "constant_ref": "module14.min_sample_size",
            "new_value": "10",
            "rationale_ru": "Пять отзывов — слишком мало.",
        },
    )

    with SessionLocal() as db:
        row = db.query(CalibrationConstantChangeLog).first()
        db.delete(row)
        with pytest.raises((AppendOnlyViolation, StatementError)):
            db.commit()


def test_recorded_change_does_not_alter_past_snapshots(signed_client, moderator_client, recruiter_client):
    """FR3.4: изменение действует вперёд, прошлые снимки — исторический факт."""
    send(recruiter_client, calibration.CONFIRMED_RELEVANT)
    with SessionLocal() as db:
        before = db.query(RecruiterFeedback).first().trust_score_at_feedback

    moderator_client.post(
        f"{CAL}/changes",
        json={
            "constant_ref": "module6.independence_weighting",
            "new_value": "0.5",
            "rationale_ru": "Повторный источник недооценён.",
        },
    )

    with SessionLocal() as db:
        assert db.query(RecruiterFeedback).first().trust_score_at_feedback == before


def test_operator_screen_is_flagged_as_not_production_safe(signed_client, moderator_client):
    payload = moderator_client.get(CAL).json()
    assert "без доступа и без ролей" in payload["not_production_safe_ru"]


# --- US4: выборочный разбор ------------------------------------------------


def test_batch_produces_real_module_7_cases(signed_client, moderator_client, recruiter_client):
    """FR4.2: этот модуль отбирает, а разбирает очередь модуля 7."""
    send(recruiter_client, calibration.NOT_RELEVANT)

    created = moderator_client.post(
        f"{CAL}/batches", json={"selection_criteria": calibration.RANDOM, "size": 1}
    )
    assert created.status_code == 201

    batch = created.json()["batches"][0]
    assert batch["dispute_case_ids"]

    with SessionLocal() as db:
        case = db.query(DisputeCase).first()
        assert case.origin == "sampled_audit"
        assert case.status == "queued"

    queue = moderator_client.get(QUEUE).json()
    assert any(item["origin"] == "sampled_audit" for item in queue["cases"])


def test_divergence_selection_picks_only_contradictions(signed_client, moderator_client, recruiter_client):
    """FR4.1: отбор по расхождению — то, ради чего он и нужен."""
    # Высокий Trust и «не подошёл» — это расхождение.
    send(recruiter_client, calibration.NOT_RELEVANT, "cand_001")
    # Высокий Trust и «подошёл» — согласие, в партию попадать не должно.
    send(recruiter_client, calibration.CONFIRMED_RELEVANT, "cand_002")

    payload = moderator_client.post(
        f"{CAL}/batches", json={"selection_criteria": calibration.HIGH_DIVERGENCE, "size": 5}
    ).json()

    batch = payload["batches"][0]
    with SessionLocal() as db:
        rows = {row.candidate_id: row for row in db.query(RecruiterFeedback).all()}
    for candidate_id in batch["candidate_ids"]:
        row = rows[candidate_id]
        assert (
            calibration.outcomes_agree(row.relevance_outcome, row.trust_score_at_feedback) is False
        )


def test_batch_without_feedback_says_why(signed_client, moderator_client):
    response = moderator_client.post(
        f"{CAL}/batches", json={"selection_criteria": calibration.RANDOM, "size": 3}
    )
    assert response.status_code == 409
    assert "нет ни одного отзыва" in response.json()["detail"]


def test_batch_summary_is_about_the_whole_batch(signed_client, moderator_client, recruiter_client):
    """FR4.3: систематическая ошибка видна поверх партии, а не в одном случае."""
    send(recruiter_client, calibration.NOT_RELEVANT)
    payload = moderator_client.post(
        f"{CAL}/batches", json={"selection_criteria": calibration.RANDOM, "size": 1}
    ).json()

    batch = payload["batches"][0]
    assert batch["pattern_ru"]
    assert isinstance(batch["overridden_by_subject_type"], dict)


def test_module_builds_no_second_review_screen():
    """FR4.2: разбор остаётся в модуле 7 — второго интерфейса тут нет."""
    source = inspect.getsource(router)
    for forbidden in ("uphold", "request-info", "override"):
        assert f'"/{forbidden}' not in source


# --- границы (§0) ----------------------------------------------------------


def test_this_feedback_is_not_merged_with_the_other_three(signed_client):
    """§0: четыре механизма обратной связи и четыре разных хранилища."""
    source = inspect.getsource(router)

    assert "ProbeFeedback" not in source
    assert "ReturnTrigger" not in source
    # Спор создаётся только как результат отбора партии, а не как способ
    # записать мнение рекрутера о кандидате.
    assert source.count("DisputeCase(") == 1
