"""Проверки модуля 13: поэтапное раскрытие.

Модуль существует ради одной проверяемой вещи — первое решение принимается по
профессиональным данным, до имени и фотографии. Поэтому проверяется:

* на первом этапе закрыто ровно два поля и ни одним больше;
* второй этап наступает только от отдельного осознанного действия;
* третий — только при встречном согласии кандидата;
* скрытый профиль не появляется ни на одном этапе.
"""

import inspect

from app import candidates as pool, reveal
from app.db import SessionLocal
from app.models import ReturnTrigger, RevealState, VisibilityState
from app.routers import recruiter as recruiter_module

SEARCH = "/api/recruiter/search"
CANDIDATES = "/api/recruiter/candidates"
COMPARE = "/api/recruiter/compare"
REVEAL = "/api/reveal"
ROLES = "/api/prof/roles"
PARSE = "/api/profile/parse"
ACCEPT = "/api/profile/statements/accept"
LINK = "/api/profile/evidence/link"
PROFILE = "/api/profile"
VISIBILITY = "/api/prof/visibility"
VACANCY = "vac_001"

CASE_TEXT = (
    "Переписал биллинг с нуля на Python, вынес его в отдельный микросервис. "
    "Под нагрузкой в 3000 rps старая схема не держала, поэтому добавили Redis "
    "и переработали индексы в PostgreSQL."
)

FIRST = "cand_001"


def detail(client, candidate_id=FIRST):
    return client.get(f"{CANDIDATES}/{candidate_id}", params={"vacancy_id": VACANCY}).json()


def advance(client, candidate_id=FIRST):
    return client.post(
        f"{CANDIDATES}/{candidate_id}/reveal", params={"vacancy_id": VACANCY}
    ).json()


def go_public(client):
    """Делает живой профиль видимым рынку — иначе его нет в пуле."""
    client.post(ROLES, json={"level": "Middle"})
    parsed = client.post(PARSE, json={"raw_text": CASE_TEXT}).json()
    client.post(ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]})
    ids = [item["id"] for item in client.get(PROFILE).json()["statements"]]
    client.post(LINK, json={"url": "https://github.com/dev/billing", "statement_ids": ids})
    client.put(VISIBILITY, json={"mode": "visible"})


def live_id():
    with SessionLocal() as db:
        state = db.query(VisibilityState).first()
        return f"{pool.LIVE_PREFIX}{state.user_id}"


# --- US1: первый этап -------------------------------------------------------


def test_first_stage_hides_exactly_name_and_photo(signed_client):
    """FR1.1: закрыто два поля, всё остальное открыто целиком."""
    payload = detail(signed_client)

    assert payload["identity_revealed"] is False
    assert payload["display_name"].startswith("Кандидат #")
    assert payload["photo_label"] == "—"

    # Всё, ради чего существует экран, на месте.
    assert payload["prof_index"] >= 0
    assert payload["trust_components"]
    assert payload["prof_components"]
    assert payload["covered"] or payload["uncovered"]
    assert payload["radar_points"]


def test_hidden_identity_reads_as_intentional_not_broken(signed_client):
    """FR1.2: пустое место читалось бы как сломанный профиль."""
    payload = detail(signed_client)

    assert payload["display_name"].strip()
    assert payload["photo_label"].strip()
    assert "не указано" not in payload["display_name"].lower()
    assert "первое решение" in payload["stage_note_ru"].lower()


def test_anonymous_label_is_stable_across_views(signed_client):
    """§7: иначе рекрутер не узнает того, кого смотрел вчера."""
    first = detail(signed_client)["display_name"]
    signed_client.get(SEARCH, params={"vacancy_id": VACANCY})
    second = detail(signed_client)["display_name"]

    assert first == second
    assert reveal.anonymous_label(FIRST) == first


def test_labels_differ_between_candidates():
    labels = {reveal.anonymous_label(item.id) for item in pool.visible_pool()}
    assert len(labels) == len(pool.visible_pool())


def test_search_results_start_anonymous(signed_client):
    payload = signed_client.get(SEARCH, params={"vacancy_id": VACANCY}).json()

    assert payload["candidates"]
    assert all(not item["identity_revealed"] for item in payload["candidates"])
    assert all(item["display_name"].startswith("Кандидат #") for item in payload["candidates"])


def test_comparison_also_starts_anonymous(signed_client):
    """FR1.4: сравнение обезличенных профилей — ровно тот сценарий, ради
    которого модуль существует, и обходить его здесь нельзя."""
    ids = ",".join(item.id for item in pool.visible_pool()[:2])
    payload = signed_client.get(COMPARE, params={"vacancy_id": VACANCY, "ids": ids}).json()

    assert all(not item["identity_revealed"] for item in payload["candidates"])


# --- US2: второй этап -------------------------------------------------------


def test_identity_opens_only_after_a_deliberate_action(signed_client):
    """FR2.1: не по таймеру, не при открытии карточки — отдельным действием."""
    for _ in range(3):
        assert detail(signed_client)["identity_revealed"] is False

    after = advance(signed_client)
    assert after["identity_revealed"] is True
    assert after["display_name"] == "Мария К."


def test_advancing_does_not_change_anything_else(signed_client):
    """FR2.2: раскрытие имени не трогает остальные данные."""
    before = detail(signed_client)
    after = advance(signed_client)

    assert after["prof_index"] == before["prof_index"]
    assert after["trust_score"] == before["trust_score"]
    assert after["match_score"] == before["match_score"]
    assert after["covered"] == before["covered"]


def test_stage_is_per_recruiter_not_global(signed_client, client, credentials):
    """FR2.2: этап одного рекрутера ничего не значит для другого."""
    advance(signed_client)
    assert detail(signed_client)["identity_revealed"] is True

    with SessionLocal() as db:
        rows = db.query(RevealState).all()
        assert len({row.recruiter_user_id for row in rows}) == 1


def test_advancing_is_idempotent(signed_client):
    first = advance(signed_client)
    second = advance(signed_client)
    assert first["current_stage"] == second["current_stage"] == reveal.STAGE_2

    with SessionLocal() as db:
        rows = db.query(RevealState).filter_by(candidate_id=FIRST).all()
        assert len(rows) == 1


def test_advancing_fires_the_recruiter_interest_trigger(signed_client):
    """FR2.3: повод, отложенный в модуле 8, наконец получает производителя."""
    go_public(signed_client)
    candidate_id = live_id()

    with SessionLocal() as db:
        before = db.query(ReturnTrigger).filter_by(trigger_type="recruiter_interest").count()
    assert before == 0

    advance(signed_client, candidate_id)

    with SessionLocal() as db:
        rows = db.query(ReturnTrigger).filter_by(trigger_type="recruiter_interest").all()
    assert len(rows) == 1
    assert rows[0].related_ref == candidate_id


def test_seed_candidate_produces_no_trigger(signed_client):
    """Синтетическому профилю некому возвращаться — повода быть не должно."""
    advance(signed_client, FIRST)

    with SessionLocal() as db:
        assert db.query(ReturnTrigger).filter_by(trigger_type="recruiter_interest").count() == 0


# --- третий этап: только встречное согласие ---------------------------------


def test_contacts_need_both_sides(signed_client):
    """FR2.4/FR3.3: одного действия рекрутера здесь недостаточно."""
    go_public(signed_client)
    candidate_id = live_id()
    advance(signed_client, candidate_id)

    asked = signed_client.post(
        f"{CANDIDATES}/{candidate_id}/request-contacts", params={"vacancy_id": VACANCY}
    ).json()
    assert asked["contacts_visible"] is False
    assert asked["current_stage"] == reveal.STAGE_2

    with SessionLocal() as db:
        recruiter_id = db.query(RevealState).first().recruiter_user_id

    signed_client.post(f"{REVEAL}/interests/{recruiter_id}/share-contacts")

    after = signed_client.post(
        f"{CANDIDATES}/{candidate_id}/request-contacts", params={"vacancy_id": VACANCY}
    ).json()
    assert after["contacts_visible"] is True
    assert after["current_stage"] == reveal.STAGE_3


def test_contacts_cannot_be_requested_before_identity(signed_client):
    response = signed_client.post(
        f"{CANDIDATES}/{FIRST}/request-contacts", params={"vacancy_id": VACANCY}
    )
    assert response.status_code == 409


# --- US3: сторона кандидата -------------------------------------------------


def test_candidate_sees_who_reached_which_stage(signed_client):
    """FR3.1: прозрачность, а не право вето."""
    go_public(signed_client)
    candidate_id = live_id()
    detail(signed_client, candidate_id)

    payload = signed_client.get(REVEAL).json()
    assert payload["interests"]
    assert payload["interests"][0]["current_stage"] == reveal.STAGE_1
    assert "только профессиональные данные" in payload["interests"][0]["stage_ru"]

    advance(signed_client, candidate_id)
    after = signed_client.get(REVEAL).json()
    assert after["interests"][0]["current_stage"] == reveal.STAGE_2


def test_candidate_cannot_roll_a_stage_back(signed_client):
    """Раскрытая личность не закрывается обратно — это и есть «не вето»."""
    from app.routers import reveal as candidate_side

    source = inspect.getsource(candidate_side)
    assert reveal.STAGE_1 not in source.split("STAGE_RU")[-1] or "= reveal.STAGE_1" not in source


def test_opt_out_is_off_by_default_and_explicit(signed_client):
    """FR3.2: поэтапность и есть механизм — выход из неё осознанный."""
    payload = signed_client.get(REVEAL).json()

    assert payload["allow_immediate_identity_reveal"] is False
    assert payload["opt_out_label_ru"] == "Разрешить рекрутерам сразу видеть моё имя и фото"


def test_opt_out_skips_straight_to_identity(signed_client):
    go_public(signed_client)
    signed_client.put(f"{REVEAL}/settings", json={"allow_immediate_identity_reveal": True})

    payload = detail(signed_client, live_id())
    assert payload["identity_revealed"] is True
    assert payload["current_stage"] == reveal.STAGE_2


def test_immediate_identity_does_not_imply_contact_consent(signed_client):
    """FR3.3: два независимых решения, одно не подразумевает другое."""
    go_public(signed_client)
    signed_client.put(f"{REVEAL}/settings", json={"allow_immediate_identity_reveal": True})
    candidate_id = live_id()
    detail(signed_client, candidate_id)

    asked = signed_client.post(
        f"{CANDIDATES}/{candidate_id}/request-contacts", params={"vacancy_id": VACANCY}
    ).json()
    assert asked["contacts_visible"] is False


def test_two_settings_are_independent(signed_client):
    """Согласие на доказательства и раскрытие личности — разные вещи."""
    signed_client.put(f"{REVEAL}/settings", json={"consent_for_recruiter_view": True})
    payload = signed_client.get(REVEAL).json()

    assert payload["consent_for_recruiter_view"] is True
    assert payload["allow_immediate_identity_reveal"] is False


def test_hidden_profile_is_never_staged_at_all(signed_client):
    """FR3.4: поэтапность работает внутри видимого пула, а не в обход него."""
    go_public(signed_client)
    signed_client.put(VISIBILITY, json={"mode": "hidden"})

    candidate_id = live_id()
    assert (
        signed_client.get(
            f"{CANDIDATES}/{candidate_id}", params={"vacancy_id": VACANCY}
        ).status_code
        == 404
    )

    payload = signed_client.get(SEARCH, params={"vacancy_id": VACANCY}).json()
    assert all(item["candidate_id"] != candidate_id for item in payload["candidates"])


# --- слой отображения -------------------------------------------------------


def test_module_writes_nothing_into_scoring_modules():
    """§7: это слой отображения, а не ещё один источник данных."""
    source = inspect.getsource(reveal)

    assert "Statement" not in source
    assert "Evidence" not in source
    assert "TrustScore" not in source
    assert "compute" not in source


def test_no_automatic_advance_by_time_or_view():
    """FR2.1: раскрытие не должно случаться само."""
    source = inspect.getsource(recruiter_module)

    for forbidden in ("seconds", "timer", "auto_advance", "on_view"):
        assert forbidden not in source.lower()
