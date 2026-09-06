"""Проверки модуля 12: рекрутерская сторона.

Здесь впервые в продукте есть настоящая граница приватности, и категория
ошибок тут дороже всего, что было раньше. Поэтому основное внимание — трём
разным правилам, которые легко перепутать между собой:

* скрытый профиль недоступен структурно;
* согласие управляет только глубиной доказательств;
* отклонённые находки не существуют нигде и ни при каких настройках.
"""

import inspect

from app import candidates as pool
from app.routers import recruiter as module

SEARCH = "/api/recruiter/search"
CANDIDATES = "/api/recruiter/candidates"
COMPARE = "/api/recruiter/compare"
VACANCY = "vac_001"


def search(client, **params):
    return client.get(SEARCH, params={"vacancy_id": VACANCY, **params}).json()


# --- граница видимости ------------------------------------------------------


def test_hidden_candidate_is_absent_from_the_pool_itself():
    """FR-Priv.1: не отфильтрован на экране, а не попадает в набор вообще."""
    hidden = [item for item in pool.ALL if item.visibility_mode == "hidden"]
    assert hidden, "в наборе должен быть скрытый профиль, иначе проверять нечего"

    visible_ids = {item.id for item in pool.visible_pool()}
    assert all(item.id not in visible_ids for item in hidden)


def test_hidden_candidate_never_appears_in_search(recruiter_client):
    payload = search(recruiter_client)
    hidden_ids = {item.id for item in pool.ALL if item.visibility_mode == "hidden"}

    assert payload["candidates"]
    assert not {item["candidate_id"] for item in payload["candidates"]} & hidden_ids


def test_hidden_candidate_is_unreachable_by_direct_link(recruiter_client):
    """FR2.3: та же защита ещё раз на карточке, а не «поиск уже отфильтровал»."""
    hidden = next(item for item in pool.ALL if item.visibility_mode == "hidden")

    response = recruiter_client.get(
        f"{CANDIDATES}/{hidden.id}", params={"vacancy_id": VACANCY}
    )
    assert response.status_code == 404


def test_hidden_candidate_is_unreachable_through_comparison(recruiter_client):
    """FR5.3: сравнение не должно стать вторым входом мимо гейта."""
    hidden = next(item for item in pool.ALL if item.visibility_mode == "hidden")
    visible = pool.visible_pool()[0]

    response = recruiter_client.get(
        COMPARE, params={"vacancy_id": VACANCY, "ids": f"{visible.id},{hidden.id}"}
    )
    assert response.status_code == 404


def test_there_is_no_override_to_show_hidden_candidates():
    """FR1.4: «показать скрытых для исследования» не должно существовать."""
    for source in (inspect.getsource(module), inspect.getsource(pool)):
        assert "include_hidden" not in source
        assert "show_hidden" not in source


# --- согласие управляет только глубиной ------------------------------------


def test_consent_controls_evidence_depth_not_visibility(recruiter_client):
    """FR-Priv.2: два разных гейта, и один не подменяет другой."""
    without = next(
        item for item in pool.visible_pool() if not item.consent_for_recruiter_view
    )

    # Профиль виден, потому что виден режим — согласие тут ни при чём.
    assert any(
        item["candidate_id"] == without.id for item in search(recruiter_client)["candidates"]
    )

    detail = recruiter_client.get(
        f"{CANDIDATES}/{without.id}", params={"vacancy_id": VACANCY}
    ).json()

    assert detail["trust_components"]
    assert all(item["explanation_ru"] for item in detail["trust_components"])
    assert all(item["evidence_refs"] == [] for item in detail["trust_components"])
    assert "не открывал сами доказательства" in detail["consent_note_ru"]


def test_consent_opens_the_evidence_drill_down(recruiter_client):
    with_consent = next(
        item for item in pool.visible_pool() if item.consent_for_recruiter_view
    )
    detail = recruiter_client.get(
        f"{CANDIDATES}/{with_consent.id}", params={"vacancy_id": VACANCY}
    ).json()

    # Согласие управляет глубиной показа, и проверяется именно оно. Пустой
    # список ссылок у отдельного компонента - не признак закрытости: после
    # стабилизационного спринта непротиворечивость доказательства не считает
    # вовсе, и перечислять их у неё было бы неправдой.
    assert all(item["evidence_visible"] for item in detail["trust_components"])

    without_consent = next(
        item for item in pool.visible_pool() if not item.consent_for_recruiter_view
    )
    closed = recruiter_client.get(
        f"{CANDIDATES}/{without_consent.id}", params={"vacancy_id": VACANCY}
    ).json()
    assert not any(item["evidence_visible"] for item in closed["trust_components"])
    assert not any(item["evidence_refs"] for item in closed["trust_components"])


# --- отклонённые находки ----------------------------------------------------


def test_declined_findings_do_not_exist_in_this_module():
    """FR-Priv.3: самое строгое правило — их нет ни при каких настройках."""
    for source in (inspect.getsource(module), inspect.getsource(pool)):
        assert "AttributionFinding" not in source
        assert "TrustFinding" not in source
        assert "declined" not in source.lower() or "DECLINED" in source

    # И в самом наборе их тоже не может быть: отклонённая находка по правилу
    # модуля 6 не оставляет следа нигде.
    import json
    from pathlib import Path

    for path in Path(pool.SEED_DIR).glob("*.json"):
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert "finding" not in json.dumps(raw, ensure_ascii=False).lower()


# --- US1: поиск -------------------------------------------------------------


def test_search_ranks_by_match_and_filters(recruiter_client):
    payload = search(recruiter_client)
    scores = [item["match_score"] for item in payload["candidates"]]
    assert scores == sorted(scores, reverse=True)

    strict = search(recruiter_client, min_trust_score=75)
    assert all(item["trust_score"] >= 75 for item in strict["candidates"])
    assert len(strict["candidates"]) <= len(payload["candidates"])


def test_search_can_be_sorted_by_each_axis(recruiter_client):
    for key in ("match_score", "trust_score", "prof_index"):
        payload = search(recruiter_client, sort_by=key)
        values = [item[key] for item in payload["candidates"]]
        assert values == sorted(values, reverse=True)

    bad = recruiter_client.get(SEARCH, params={"vacancy_id": VACANCY, "sort_by": "nonsense"})
    assert bad.status_code == 400


def test_search_is_scoped_to_an_existing_vacancy(recruiter_client):
    assert recruiter_client.get(SEARCH, params={"vacancy_id": "vac_999"}).status_code == 404


def test_level_filter_narrows_the_pool(recruiter_client):
    payload = search(recruiter_client, level="Senior")
    assert all("Senior" in item["levels"] for item in payload["candidates"])


def test_module_never_reaches_out_to_candidates():
    """§2.2: рассылки и обращения к кандидату здесь нет вообще."""
    source = inspect.getsource(module).lower()
    for forbidden in ("invite", "notify", "message", "outreach", "пригласить"):
        assert forbidden not in source


# --- US2/US4: карточка ------------------------------------------------------


def test_detail_shows_the_same_data_the_candidate_sees(recruiter_client):
    """FR2.1: не упрощённая версия для рекрутера, а та же структура."""
    candidate = pool.visible_pool()[0]
    detail = recruiter_client.get(
        f"{CANDIDATES}/{candidate.id}", params={"vacancy_id": VACANCY}
    ).json()

    snapshot = max(pool.prof_snapshots(candidate), key=lambda item: item["overall_score"])
    assert detail["prof_index"] == snapshot["overall_score"]
    assert len(detail["prof_components"]) == len(snapshot["components"])
    assert detail["radar_points"]


def test_scores_are_computed_by_the_same_engines_not_stored():
    """Записанные руками цифры разошлись бы с настоящим расчётом."""
    source = inspect.getsource(pool)
    assert "compute_snapshot" in source
    assert "compute_status" in source
    assert "authenticity" in source and "understanding" in source and "consistency" in source

    import json
    from pathlib import Path

    for path in Path(pool.SEED_DIR).glob("*.json"):
        raw = json.dumps(json.loads(path.read_text(encoding="utf-8")), ensure_ascii=False)
        for forbidden in ("prof_index", "trust_score", "overall_score", '"status": "strong"'):
            assert forbidden not in raw, forbidden


def test_breakdown_is_never_collapsed_into_one_number(recruiter_client):
    """FR4.1: и компетенции, и требования вакансии — по отдельности."""
    candidate = pool.visible_pool()[0]
    detail = recruiter_client.get(
        f"{CANDIDATES}/{candidate.id}", params={"vacancy_id": VACANCY}
    ).json()

    assert detail["prof_components"]
    assert detail["covered"] or detail["uncovered"]
    assert all(item["explanation_ru"] for item in detail["covered"] + detail["uncovered"])


def test_wording_stays_factual_and_never_judges_the_person(recruiter_client):
    """FR4.2: «требует дополнительной проверки», а не «слабое место»."""
    for candidate in pool.visible_pool():
        detail = recruiter_client.get(
            f"{CANDIDATES}/{candidate.id}", params={"vacancy_id": VACANCY}
        ).json()
        texts = [item["explanation_ru"] for item in detail["covered"] + detail["uncovered"]]
        texts += [item["reason"] for item in detail["prof_components"]]
        texts += [item["explanation_ru"] for item in detail["trust_components"]]

        for text in texts:
            lowered = text.lower()
            for forbidden in ("слаб", "плохо", "недостаточно хорош", "неподходящ"):
                assert forbidden not in lowered, text


def test_uncovered_requirement_says_it_needs_more_checking(recruiter_client):
    candidate = pool.visible_pool()[0]
    detail = recruiter_client.get(
        f"{CANDIDATES}/{candidate.id}", params={"vacancy_id": VACANCY}
    ).json()

    assert detail["uncovered"]
    assert all(
        "требует дополнительной проверки" in item["explanation_ru"].lower()
        for item in detail["uncovered"]
    )


def test_unevaluated_cluster_is_not_mistaken_for_absence(recruiter_client):
    """FR4.3: та же формулировка, что видит кандидат."""
    candidate = pool.visible_pool()[0]
    detail = recruiter_client.get(
        f"{CANDIDATES}/{candidate.id}", params={"vacancy_id": "vac_003"}
    ).json()

    assert detail["unevaluated_clusters"]
    assert "не значит" in detail["unevaluated_note_ru"]


def test_nda_evidence_is_marked_neutrally(recruiter_client):
    """FR3.4: подтверждение под NDA не выглядит хуже прочих."""
    with_nda = next(item for item in pool.visible_pool() if item.nda_confirmations)
    detail = recruiter_client.get(
        f"{CANDIDATES}/{with_nda.id}", params={"vacancy_id": VACANCY}
    ).json()

    assert detail["nda_note_ru"] == "подтверждено через альтернативный метод (NDA)"
    for forbidden in ("подозрительн", "неполн", "сомнительн"):
        assert forbidden not in detail["nda_note_ru"].lower()


def test_trust_is_never_shown_as_a_bare_number(recruiter_client):
    """FR3.1: у каждого компонента — своё объяснение."""
    for candidate in pool.visible_pool():
        detail = recruiter_client.get(
            f"{CANDIDATES}/{candidate.id}", params={"vacancy_id": VACANCY}
        ).json()
        assert detail["trust_components"]
        assert all(len(item["explanation_ru"]) > 15 for item in detail["trust_components"])


# --- US5: сравнение ---------------------------------------------------------


def test_comparison_uses_one_identical_structure(recruiter_client):
    ids = ",".join(item.id for item in pool.visible_pool()[:3])
    payload = recruiter_client.get(COMPARE, params={"vacancy_id": VACANCY, "ids": ids}).json()

    assert len(payload["candidates"]) == 3
    shapes = {tuple(sorted(item.keys())) for item in payload["candidates"]}
    assert len(shapes) == 1


def test_comparison_keeps_the_breakdown_not_only_numbers(recruiter_client):
    """FR5.2: сравнение голых чисел вернуло бы непрозрачную сортировку."""
    ids = ",".join(item.id for item in pool.visible_pool()[:2])
    payload = recruiter_client.get(COMPARE, params={"vacancy_id": VACANCY, "ids": ids}).json()

    for item in payload["candidates"]:
        assert item["prof_components"]
        assert item["covered"] or item["uncovered"]
        assert item["trust_components"]


def test_comparison_needs_at_least_one_candidate(recruiter_client):
    assert (
        recruiter_client.get(COMPARE, params={"vacancy_id": VACANCY, "ids": " "}).status_code == 400
    )


# --- граница доступа --------------------------------------------------------


def test_recruiter_mode_states_the_real_access_boundary(recruiter_client):
    """Прежнее ожидание - «режим без ролей» - стало неправдой про код.

    Роли появились в стабилизационном спринте. Проверяется то же по смыслу:
    что раздел честно описывает свою границу, не обещая лишнего.
    """
    payload = search(recruiter_client)
    note = payload["access_note_ru"]
    assert "проверяются на сервере" in note
    assert "разграничения по компаниям" in note
    assert "любой вошедший" not in note
    assert "записываются" in note


def test_module_computes_nothing_of_its_own():
    """§1: своего движка оценки здесь нет — только чужие результаты."""
    source = inspect.getsource(module)
    assert "STATUS_SCORE" not in source
    assert "COMPONENT_WEIGHT" not in source
    assert "library.compute" in source


def test_recruiter_copy_never_addresses_the_candidate(recruiter_client):
    """Разбор пришёл из модуля 10, где он писался для самого кандидата.

    На рекрутерском экране «в вашем профиле» читается как обращение не к тому
    человеку — факты те же, адресат другой.
    """
    for candidate in pool.visible_pool():
        detail = recruiter_client.get(
            f"{CANDIDATES}/{candidate.id}", params={"vacancy_id": VACANCY}
        ).json()

        texts = [item["explanation_ru"] for item in detail["covered"] + detail["uncovered"]]
        texts += [item["reason"] for item in detail["prof_components"]]
        texts += [item["explanation_ru"] for item in detail["trust_components"]]

        for text in texts:
            lowered = text.lower()
            for forbidden in ("в вашем", "у вас", "вашей", "ваш "):
                assert forbidden not in lowered, text
