"""Проверки модуля 2: разбор текста, Evidence, статусы и NDA.

Отдельно проверяется таблица статусов §3.4 FRD - без базы и HTTP, чтобы
правило можно было читать как таблицу, и отдельно - поведение API.
"""

from app.enrichment import (
    DECLINED,
    LIMITED,
    MEDIUM,
    NOT_STARTED,
    PENDING,
    STRONG,
    TYPE_BLIND_WITNESS,
    TYPE_FILE,
    TYPE_FREE_TEXT,
    TYPE_LINK,
    EvidenceFacts,
    compute_status,
    parse_free_text,
    source_category_from_url,
)
from app.db import SessionLocal
from app.models import Evidence, RawInput, Statement

PROFILE = "/api/profile"
PARSE = "/api/profile/parse"
ACCEPT = "/api/profile/statements/accept"
LINK = "/api/profile/evidence/link"
FILE = "/api/profile/evidence/file"
BLIND_WITNESS = "/api/profile/evidence/blind-witness"

CASE = (
    "Переписал биллинг с нуля на Python, вынес его в отдельный микросервис. "
    "Под нагрузкой в 3000 rps старая схема не держала, поэтому добавили Redis "
    "и переработали индексы в PostgreSQL. Ускорил отчёты с 40 секунд до 2. "
    "Провёл код-ревью всей команды и написал статью на Хабр про миграцию данных."
)


def link_fact(category="github", status=PENDING):
    return EvidenceFacts(type=TYPE_LINK, source_category=category, status=status)


def free_text_fact(status=PENDING):
    return EvidenceFacts(type=TYPE_FREE_TEXT, source_category=None, status=status)


def file_fact(status=PENDING):
    return EvidenceFacts(type=TYPE_FILE, source_category=None, status=status)


def blind_witness_fact(status=PENDING):
    return EvidenceFacts(type=TYPE_BLIND_WITNESS, source_category=None, status=status)


# --- §3.4: таблица статусов ----------------------------------------------


def test_no_evidence_is_not_started():
    assert compute_status([]).status == NOT_STARTED


def test_single_free_text_is_limited():
    assert compute_status([free_text_fact()]).status == LIMITED


def test_link_to_unknown_site_is_still_self_reported():
    # «Unverified link» из §3.4: произвольный URL проверить нечем.
    assert compute_status([link_fact(category="other")]).status == LIMITED


def test_single_link_to_known_platform_is_medium():
    assert compute_status([link_fact()]).status == MEDIUM


def test_single_file_is_medium():
    assert compute_status([file_fact()]).status == MEDIUM


def test_blind_witness_answer_counts_as_independent_source():
    # FR4.5: ответ Слепого свидетеля - того же уровня, что проверяемая ссылка.
    assert compute_status([blind_witness_fact()]).status == MEDIUM


def test_two_self_reported_items_are_medium():
    assert compute_status([free_text_fact(), free_text_fact()]).status == MEDIUM


def test_two_distinct_sources_with_independent_one_are_strong():
    assert compute_status([link_fact(), file_fact()]).status == STRONG


def test_two_items_of_the_same_source_category_are_not_strong():
    assert compute_status([link_fact(), link_fact()]).status == MEDIUM


def test_declined_evidence_does_not_count_and_does_not_punish():
    with_declined = compute_status([free_text_fact(), link_fact(status=DECLINED)])
    without_it = compute_status([free_text_fact()])

    assert with_declined.status == without_it.status == LIMITED


def test_every_status_comes_with_an_explanation():
    # FR3.4: голый статус без объяснения показывать нельзя.
    for facts in ([], [free_text_fact()], [link_fact()], [link_fact(), file_fact()]):
        view = compute_status(facts)
        assert view.reason.strip()
        assert view.next_action.strip() or view.status == STRONG


def test_source_category_is_inferred_from_domain():
    assert source_category_from_url("https://github.com/nataly/billing") == "github"
    assert source_category_from_url("https://www.linkedin.com/in/nataly") == "linkedin"
    assert source_category_from_url("https://example.org/my-cv") == "other"


# --- FR2.2: разбор свободного текста -------------------------------------


def test_parser_finds_competencies_with_quotes_from_the_text():
    items = parse_free_text(CASE)
    found = {item.skill_name for item in items}

    assert {"Python", "PostgreSQL", "Caching", "High load systems"} <= found
    for item in items:
        assert item.excerpt in CASE
        assert item.confidence in ("high", "medium", "low")


def test_parser_returns_nothing_for_text_without_competencies():
    assert parse_free_text("Вчера был дождь, а сегодня солнце.") == []


# --- API ------------------------------------------------------------------


def test_profile_requires_login(client):
    assert client.get(PROFILE).status_code == 401


def test_parse_saves_the_text_but_changes_nothing_in_the_profile(signed_client):
    response = signed_client.post(PARSE, json={"raw_text": CASE})

    assert response.status_code == 200
    assert response.json()["items"], "разбор должен что-то найти"

    # FR2.3: до решения кандидата в профиле пусто.
    profile = signed_client.get(PROFILE).json()
    assert profile["statements"] == []
    assert profile["evidence"] == []

    # FR2.5: исходный текст сохранён дословно.
    with SessionLocal() as db:
        stored = db.query(RawInput).one()
        assert stored.text == CASE


def test_accepted_items_become_statements_with_evidence(signed_client):
    parsed = signed_client.post(PARSE, json={"raw_text": CASE}).json()
    items = parsed["items"][:2]

    response = signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": items}
    )

    assert response.status_code == 200
    profile = response.json()
    assert len(profile["statements"]) == 2
    assert len(profile["evidence"]) == 2

    for statement in profile["statements"]:
        assert statement["status"] == LIMITED
        assert statement["status_reason"]
        assert statement["evidence_ids"], "каждое утверждение ссылается на своё Evidence"


def test_same_competency_is_reinforced_not_duplicated(signed_client):
    parsed = signed_client.post(PARSE, json={"raw_text": CASE}).json()
    item = parsed["items"][:1]

    signed_client.post(ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": item})
    second = signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": item}
    ).json()

    assert len(second["statements"]) == 1
    assert len(second["evidence"]) == 2
    # Два подтверждения с собственных слов - это уже Medium (§3.4).
    assert second["statements"][0]["status"] == MEDIUM


def test_link_is_stored_with_inferred_source(signed_client):
    response = signed_client.post(LINK, json={"url": "https://github.com/nataly/billing"})

    assert response.status_code == 201
    evidence = response.json()["evidence"][0]
    assert evidence["type"] == TYPE_LINK
    assert evidence["source_category"] == "github"
    assert evidence["status"] == PENDING


def test_link_lifts_statement_status(signed_client):
    parsed = signed_client.post(PARSE, json={"raw_text": CASE}).json()
    profile = signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"][:1]}
    ).json()
    statement_id = profile["statements"][0]["id"]

    updated = signed_client.post(
        LINK,
        json={"url": "https://github.com/nataly/billing", "statement_ids": [statement_id]},
    ).json()

    assert updated["statements"][0]["status"] == STRONG


def test_one_evidence_can_back_several_statements(signed_client):
    parsed = signed_client.post(PARSE, json={"raw_text": CASE}).json()
    profile = signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"][:2]}
    ).json()
    first, second = (s["id"] for s in profile["statements"])

    evidence_id = signed_client.post(
        LINK, json={"url": "https://github.com/nataly/billing", "statement_ids": [first]}
    ).json()["evidence"][-1]["id"]

    linked = signed_client.post(f"{PROFILE}/statements/{second}/evidence/{evidence_id}").json()
    backing = next(e for e in linked["evidence"] if e["id"] == evidence_id)

    assert set(backing["linked_statement_ids"]) == {first, second}


def test_file_upload_creates_pending_evidence(signed_client):
    response = signed_client.post(
        FILE, files={"file": ("diploma.png", b"\x89PNG\r\n\x1a\n" + b"0" * 100, "image/png")}
    )

    assert response.status_code == 201
    evidence = response.json()["evidence"][0]
    assert evidence["type"] == TYPE_FILE
    assert evidence["file_name"] == "diploma.png"
    assert evidence["status"] == PENDING


def test_file_of_wrong_format_is_rejected(signed_client):
    response = signed_client.post(
        FILE, files={"file": ("script.exe", b"MZ binary", "application/octet-stream")}
    )

    assert response.status_code == 400
    assert signed_client.get(PROFILE).json()["evidence"] == []


def test_file_over_ten_megabytes_is_rejected(signed_client):
    too_big = b"0" * (10 * 1024 * 1024 + 1)
    response = signed_client.post(FILE, files={"file": ("big.pdf", too_big, "application/pdf")})

    assert response.status_code == 413
    assert signed_client.get(PROFILE).json()["evidence"] == []


# --- US4: NDA и отказы ----------------------------------------------------


def test_blind_witness_confirms_competency_without_disclosing_anything(signed_client):
    """Приёмочный сценарий US4: проект под NDA доходит до Medium, при этом ни
    файла, ни описания проекта в системе не появляется."""
    answer = (
        "Ключевых развилок было три: держать ли консистентность на уровне БД "
        "или в приложении, переносить ли данные разом или в две волны, и как "
        "откатываться. Выбрали PostgreSQL с транзакционным переносом."
    )

    response = signed_client.post(BLIND_WITNESS, json={"answer": answer})

    assert response.status_code == 201
    profile = response.json()

    evidence = profile["evidence"][0]
    assert evidence["type"] == TYPE_BLIND_WITNESS
    assert evidence["nda"] is True
    assert evidence["url"] is None and evidence["file_ref"] is None
    assert evidence["raw_text"] == answer

    assert profile["statements"], "ответ разобран в компетенции"
    assert all(s["status"] == MEDIUM for s in profile["statements"])
    # Факт «материалы не раскрывались» зафиксирован (FR4.2).
    assert profile["declines"] and all(d["target_type"] == "statement" for d in profile["declines"])


def test_blind_witness_answer_can_be_attached_to_a_chosen_competency(signed_client):
    parsed = signed_client.post(PARSE, json={"raw_text": CASE}).json()
    profile = signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"][:1]}
    ).json()
    statement_id = profile["statements"][0]["id"]

    updated = signed_client.post(
        BLIND_WITNESS,
        json={
            "answer": "Решали, что делать с двойными списаниями.",
            "statement_ids": [statement_id],
        },
    ).json()

    # Ответ пришёл к выбранной компетенции, новых не завелось, а к описанию
    # кандидата добавился независимый источник другого типа - это Strong.
    assert len(updated["statements"]) == 1
    assert updated["statements"][0]["status"] == STRONG


def test_decline_needs_no_reason_and_takes_nothing_away(signed_client):
    parsed = signed_client.post(PARSE, json={"raw_text": CASE}).json()
    profile = signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"][:1]}
    ).json()
    statement_id = profile["statements"][0]["id"]
    before = profile["statements"][0]["status"]

    declined = signed_client.post(
        f"{PROFILE}/statements/{statement_id}/decline", json={}
    ).json()

    assert declined["statements"][0]["status"] == before
    assert declined["statements"][0]["declined"] is True
    assert declined["declines"][0]["reason"] is None


def test_declining_an_evidence_lowers_nothing_below_the_rest(signed_client):
    parsed = signed_client.post(PARSE, json={"raw_text": CASE}).json()
    profile = signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"][:1]}
    ).json()
    statement_id = profile["statements"][0]["id"]

    with_link = signed_client.post(
        LINK, json={"url": "https://github.com/nataly/billing", "statement_ids": [statement_id]}
    ).json()
    link_id = with_link["evidence"][-1]["id"]
    assert with_link["statements"][0]["status"] == STRONG

    after = signed_client.post(f"{PROFILE}/evidence/{link_id}/decline", json={}).json()

    # Ссылка больше не учитывается, но осталось описание кандидата - Limited,
    # ровно как если бы ссылки и не было. Наказания за отказ нет.
    assert after["statements"][0]["status"] == LIMITED
    assert next(e for e in after["evidence"] if e["id"] == link_id)["status"] == DECLINED


def test_decline_is_reversible(signed_client):
    added = signed_client.post(LINK, json={"url": "https://github.com/nataly/billing"}).json()
    evidence_id = added["evidence"][0]["id"]

    signed_client.post(f"{PROFILE}/evidence/{evidence_id}/decline", json={"reason": "NDA"})
    restored = signed_client.delete(f"{PROFILE}/evidence/{evidence_id}/decline").json()

    assert restored["evidence"][0]["status"] == PENDING
    assert restored["declines"] == []


def test_unlinked_evidence_is_deleted_but_linked_one_turns_into_decline(signed_client):
    alone = signed_client.post(LINK, json={"url": "https://gitlab.com/nataly/tools"}).json()
    alone_id = alone["evidence"][0]["id"]

    assert signed_client.delete(f"{PROFILE}/evidence/{alone_id}").json()["evidence"] == []

    parsed = signed_client.post(PARSE, json={"raw_text": CASE}).json()
    profile = signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"][:1]}
    ).json()
    linked_id = profile["evidence"][0]["id"]

    after = signed_client.delete(f"{PROFILE}/evidence/{linked_id}").json()

    # FR1.6: связанное доказательство не стирается из истории.
    assert len(after["evidence"]) == 1
    assert after["evidence"][0]["status"] == DECLINED


def test_manual_statement_starts_empty(signed_client):
    response = signed_client.post(
        f"{PROFILE}/statements", json={"skill_name_ru": "Проектирование REST API"}
    )

    assert response.status_code == 201
    statement = response.json()["statements"][0]
    assert statement["source_of_claim"] == "manual"
    assert statement["status"] == NOT_STARTED
    assert statement["next_action"]


def test_another_candidate_cannot_touch_someone_elses_evidence(signed_client, client):
    added = signed_client.post(LINK, json={"url": "https://github.com/nataly/billing"}).json()
    evidence_id = added["evidence"][0]["id"]

    signed_client.post("/api/auth/logout")
    client.post(
        "/api/auth/register", json={"email": "someone@example.com", "password": "verysecret123"}
    )

    assert client.post(f"{PROFILE}/evidence/{evidence_id}/decline", json={}).status_code == 404
    assert client.get(PROFILE).json()["evidence"] == []


def test_broken_identifier_is_not_found(signed_client):
    assert signed_client.post(f"{PROFILE}/evidence/ev_нет/decline", json={}).status_code == 404


def test_statements_and_evidence_survive_reload(signed_client):
    """§7 FRD: перезагрузка не сбрасывает профиль."""
    parsed = signed_client.post(PARSE, json={"raw_text": CASE}).json()
    signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"][:2]}
    )

    with SessionLocal() as db:
        assert db.query(Statement).count() == 2
        assert db.query(Evidence).count() == 2

    assert len(signed_client.get(PROFILE).json()["statements"]) == 2
