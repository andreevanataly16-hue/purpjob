"""Проверки модуля 10: лента вакансий и Match Score.

Главное здесь — два ограничения, которые легко нарушить незаметно:

* Match Score ничего не пишет обратно в профиль;
* это не инструмент массовой рассылки — отклика в модуле нет вообще.
"""

import inspect

from app import vacancies as library
from app.prof import STATUS_SCORE
from app.vacancies import (
    ADD_EVIDENCE,
    ANSWER_EXISTING_PROBE,
    CRITICALITY_WEIGHT,
    MANDATORY,
    NICE_TO_HAVE,
    CompetencyState,
    compute,
    feed_for,
)

FEED = "/api/vacancies"
PROF = "/api/prof"
TRUST = "/api/trust"
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
    ids = [item["id"] for item in client.get(PROFILE).json()["statements"]]
    client.post(LINK, json={"url": "https://github.com/dev/billing", "statement_ids": ids})


def state(**statuses):
    return CompetencyState(by_competency=dict(statuses), by_skill={})


# --- US1: лента ------------------------------------------------------------


def test_feed_is_filtered_to_the_declared_level(signed_client):
    """FR1.2: чужой уровень в ленту не попадает."""
    setup_candidate(signed_client, "Middle")
    payload = signed_client.get(FEED).json()

    assert payload["vacancies"]
    assert all(item["stated_level"] == "Middle" for item in payload["vacancies"])


def test_two_roles_widen_the_feed_without_duplicates(signed_client):
    setup_candidate(signed_client, "Middle")
    middle = {item["id"] for item in signed_client.get(FEED).json()["vacancies"]}

    signed_client.post(ROLES, json={"level": "Senior"})
    both = [item["id"] for item in signed_client.get(FEED).json()["vacancies"]]

    assert len(both) == len(set(both))
    assert middle < set(both)


def test_feed_without_a_role_explains_itself(signed_client):
    payload = signed_client.get(FEED).json()
    assert payload["vacancies"] == []
    assert "целевую роль" in payload["note_ru"]


def test_one_posting_from_several_channels_is_one_card(signed_client):
    """FR1.4: дубликаты из разных каналов сливаются, источники сохраняются."""
    setup_candidate(signed_client, "Middle")
    cards = signed_client.get(FEED).json()["vacancies"]

    multi = [item for item in cards if len(item["source_channels"]) > 1]
    assert multi, "в наборе должна быть вакансия из нескольких каналов"
    assert len({item["id"] for item in cards}) == len(cards)


def test_feed_stays_small_and_curated():
    """§6 FR-Constraint.4: набор маленький намеренно."""
    assert len(library.ALL) <= 20


def test_module_has_no_apply_flow_and_no_counters():
    """§6 FR-Constraint.1/2: отклика нет, счётчиков объёма нет."""
    from app.routers import vacancies as router

    for module in (library, router):
        source = inspect.getsource(module).lower()
        for forbidden in ("apply", "откликн", "заявк", "просмотрено", "streak"):
            assert forbidden not in source, forbidden


# --- US2: Match Score как проекция ----------------------------------------


def test_match_is_a_projection_of_prof_not_a_second_score():
    """FR2.1: перевод статуса в вклад берётся у модуля 3, а не заводится свой."""
    source = inspect.getsource(library)
    assert "from app.prof import STATUS_SCORE" in source
    # Своей таблицы статус→балл в модуле нет.
    assert source.count("STATUS_SCORE") >= 1
    assert '"strong": 1.0' not in source


def test_match_never_writes_to_the_profile():
    """FR2.3: односторонняя связь, проверяемая кодом, а не обещанием."""
    from app.routers import vacancies as router

    for module in (library, router):
        source = inspect.getsource(module)
        assert "db.add(" not in source
        assert "db.commit(" not in source
        assert "db.delete(" not in source


def test_browsing_vacancies_changes_nothing_in_the_profile(signed_client):
    setup_candidate(signed_client, "Middle")
    prof_before = signed_client.get(PROF).json()
    trust_before = signed_client.get(TRUST).json()

    for card in signed_client.get(FEED).json()["vacancies"]:
        signed_client.get(f"{FEED}/{card['id']}")

    assert signed_client.get(PROF).json()["snapshots"] == prof_before["snapshots"]
    assert signed_client.get(TRUST).json()["components"] == trust_before["components"]


def test_vacancy_weight_wins_over_reference_weight():
    """FR2.2, механизм 2: считаем по критичности вакансии, а не по весу эталона."""
    vacancy = library.BY_ID["vac_001"]

    mandatory_only = compute(
        vacancy, state(core_language="strong", rest_api_design="strong", database_design="strong"), {}
    )
    nice_only = compute(vacancy, state(testing="strong"), {})

    # Три обязательных требования дают заметно больше, чем одно желательное.
    assert mandatory_only.overall_match_score > nice_only.overall_match_score
    assert CRITICALITY_WEIGHT[MANDATORY] > CRITICALITY_WEIGHT[NICE_TO_HAVE]


def test_requirement_outside_the_reference_profile_still_counts():
    """FR2.2, механизм 1: требования вроде ClickHouse не выкидываются из расчёта."""
    vacancy = library.BY_ID["vac_001"]
    full = compute(
        vacancy,
        state(
            core_language="strong",
            rest_api_design="strong",
            database_design="strong",
            testing="strong",
        ),
        {},
    )

    # Всё, что есть в эталоне, подтверждено — но 100 не получается, потому что
    # ClickHouse не закрыт.
    assert full.overall_match_score < 100
    assert any(item.requirement_id == "req_005" for item in full.uncovered)


def test_vacancy_only_requirement_can_be_covered_by_a_manual_competency():
    """Обратная сторона: если кандидат сам добавил ClickHouse, он засчитывается."""
    vacancy = library.BY_ID["vac_001"]
    with_skill = CompetencyState(by_competency={}, by_skill={"clickhouse": "strong"})

    result = compute(vacancy, with_skill, {})
    assert any(item.requirement_id == "req_005" for item in result.covered)


def test_high_role_breadth_is_scored_per_cluster():
    """FR2.4: каждый кластер против своего эталона, а не один усреднённый."""
    vacancy = library.BY_ID["vac_003"]
    result = compute(vacancy, state(core_language="strong"), {"ref_backend_fullstack_python_go_middle": 40})

    assert vacancy.role_breadth == "high"
    assert result.cluster_scores == [("Backend-разработка", 40)]
    assert result.unevaluated_clusters == ["DevOps и инфраструктура"]


def test_unevaluated_cluster_is_never_folded_in_as_zero(signed_client):
    setup_candidate(signed_client, "Middle")
    detail = signed_client.get(f"{FEED}/vac_003").json()

    assert detail["unevaluated_clusters"]
    assert "не оценена платформой" in detail["unevaluated_note_ru"]
    assert "не значит, что у вас её нет" in detail["unevaluated_note_ru"]


def test_role_breadth_copy_is_structural_not_evaluative(signed_client):
    """§3: «объединяет два кластера», а не «слишком размытая вакансия»."""
    setup_candidate(signed_client, "Middle")
    note = signed_client.get(f"{FEED}/vac_003").json()["note_ru"]

    assert "объединяет" in note
    for forbidden in ("размыт", "слишком", "плохо"):
        assert forbidden not in note.lower()


def test_overstated_level_is_a_property_of_the_vacancy(signed_client):
    """FR2.2, механизм 5: вакансия, завышающая уровень, не портит профиль."""
    setup_candidate(signed_client, "Middle")
    prof_before = signed_client.get(PROF).json()["snapshots"][0]["overall_score"]

    signed_client.post(ROLES, json={"level": "Senior"})
    for card in signed_client.get(FEED).json()["vacancies"]:
        signed_client.get(f"{FEED}/{card['id']}")

    after = next(
        item
        for item in signed_client.get(PROF).json()["snapshots"]
        if item["level"] == "Middle"
    )
    assert after["overall_score"] == prof_before


# --- US3: три категории требований ----------------------------------------


def test_requirements_split_into_exactly_three_categories(signed_client):
    setup_candidate(signed_client, "Middle")
    detail = signed_client.get(f"{FEED}/vac_001").json()

    vacancy = library.BY_ID["vac_001"]
    assert len(detail["covered"]) + len(detail["uncovered"]) == len(vacancy.requirements)
    assert isinstance(detail["unevaluated_clusters"], list)


def test_every_requirement_carries_a_factual_reason(signed_client):
    """FR3.2: голых меток нет ни в одной категории."""
    setup_candidate(signed_client, "Middle")

    for card in signed_client.get(FEED).json()["vacancies"]:
        detail = signed_client.get(f"{FEED}/{card['id']}").json()
        for item in detail["covered"] + detail["uncovered"]:
            assert len(item["explanation_ru"]) > 20
            for forbidden in ("слаб", "недостаточно хорош", "плохо"):
                assert forbidden not in item["explanation_ru"].lower()


def test_uncovered_explanation_distinguishes_nothing_from_not_enough():
    """FR3.2: «нет ни одного» и «есть, но мало» — разные факты."""
    vacancy = library.BY_ID["vac_001"]

    nothing = compute(vacancy, state(), {})
    partial = compute(vacancy, state(core_language="limited"), {})

    empty_reason = next(i for i in nothing.uncovered if i.requirement_id == "req_001").explanation_ru
    partial_reason = next(
        i for i in partial.uncovered if i.requirement_id == "req_001"
    ).explanation_ru

    assert "нет ни одного" in empty_reason
    assert empty_reason != partial_reason
    assert "не хватает" in partial_reason


def test_status_vocabulary_is_module_3s_own():
    """FR3.3: своей параллельной таксономии статусов модуль не заводит."""
    vacancy = library.BY_ID["vac_001"]
    result = compute(vacancy, state(core_language="medium", rest_api_design="limited"), {})

    statuses = {item.status for item in result.covered + result.uncovered}
    assert statuses <= set(STATUS_SCORE)


# --- US4: рекомендация ----------------------------------------------------


def test_recommendation_has_exactly_two_routes():
    """FR4.1: третьего маршрута нет — Vacancy-Specific Probe отложен."""
    vacancy = library.BY_ID["vac_001"]
    result = compute(vacancy, state(), {})

    routes = {item.recommended_action for item in result.uncovered}
    assert routes <= {ADD_EVIDENCE, ANSWER_EXISTING_PROBE}


def test_reference_requirement_routes_to_the_existing_probe():
    vacancy = library.BY_ID["vac_001"]
    result = compute(vacancy, state(), {})

    with_competency = next(i for i in result.uncovered if i.competency_id == "core_language")
    assert with_competency.recommended_action == ANSWER_EXISTING_PROBE


def test_vacancy_only_requirement_routes_to_adding_evidence():
    """Для ClickHouse вопроса нет и быть не может — генерировать его нельзя."""
    vacancy = library.BY_ID["vac_001"]
    result = compute(vacancy, state(), {})

    clickhouse = next(i for i in result.uncovered if i.requirement_id == "req_005")
    assert clickhouse.competency_id is None
    assert clickhouse.recommended_action == ADD_EVIDENCE


def test_recommendations_are_ordered_mandatory_first():
    """FR4.2: тот же приоритет, что у белых пятен модуля 3."""
    vacancy = library.BY_ID["vac_001"]
    result = compute(vacancy, state(), {})

    weights = [CRITICALITY_WEIGHT[item.criticality] for item in result.uncovered]
    assert weights == sorted(weights, reverse=True)


def test_no_new_question_is_ever_generated_here():
    """FR4.4: выдуманных кейсов под вакансию модуль не делает."""
    from app.routers import vacancies as router

    for module in (library, router):
        source = inspect.getsource(module)
        assert "ProbeQuestion" not in source
        assert "generate_question" not in source


def test_match_recomputes_after_the_candidate_acts(signed_client):
    """FR4.3: без кнопки «пересчитать» — совпадение живое."""
    setup_candidate(signed_client, "Middle")
    before = signed_client.get(f"{FEED}/vac_003").json()["overall_match_score"]

    parsed = signed_client.post(
        PARSE, json={"raw_text": "Настроил CI/CD в GitLab и деплой в Kubernetes через Helm."}
    ).json()
    signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]}
    )
    ids = [item["id"] for item in signed_client.get(PROFILE).json()["statements"]]
    signed_client.post(LINK, json={"url": "https://gitlab.com/dev/ci", "statement_ids": ids})

    after = signed_client.get(f"{FEED}/vac_003").json()["overall_match_score"]
    assert after > before


def test_unknown_vacancy_is_not_found(signed_client):
    setup_candidate(signed_client, "Middle")
    assert signed_client.get(f"{FEED}/vac_999").status_code == 404


# --- набор данных ---------------------------------------------------------


def test_seed_is_validated_at_import():
    """Опечатка в competency_id тихо поменяла бы маршрут рекомендации."""
    known = {
        competency.competency_id
        for level in ("Middle", "Senior")
        for competency in library.get_profile(level).competencies
    }
    for vacancy in library.ALL:
        for requirement in vacancy.requirements:
            assert requirement.competency_id is None or requirement.competency_id in known


def test_every_vacancy_names_its_source():
    for vacancy in library.ALL:
        assert vacancy.source_channels


def test_feed_for_returns_newest_first():
    items = feed_for("Middle")
    dates = [item.created_at for item in items]
    assert dates == sorted(dates, reverse=True)
