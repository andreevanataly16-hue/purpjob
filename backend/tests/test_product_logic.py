"""Проверки продуктовой логики, которые легко потерять при доработках.

Здесь собраны правила, нарушение которых не сломает ни один экран, но сломает
сам продукт: отсутствие публичного следа не должно превращаться в наказание,
отказ - в оценку, а упоминание технологии в тексте - в компетенцию.
"""

from pathlib import Path

from app.config import settings
from app.db import SessionLocal
from app.enrichment import (
    DECLINED,
    LIMITED,
    MEDIUM,
    NEGATIVE,
    PENDING,
    POSITIVE,
    HYPOTHETICAL,
    TYPE_BLIND_WITNESS,
    EvidenceFacts,
    assertion_type,
    compute_status,
    parse_free_text,
)
from app.models import DeclineRecord, Evidence

PROFILE = "/api/profile"
BLIND_WITNESS = "/api/profile/evidence/blind-witness"
LINK = "/api/profile/evidence/link"
FILE = "/api/profile/evidence/file"
PARSE = "/api/profile/parse"
ACCEPT = "/api/profile/statements/accept"
ROLES = "/api/prof/roles"
PROF = "/api/prof"

NDA_ANSWER = (
    "Развилок было три: держать консистентность на уровне базы или в приложении, "
    "переносить данные разом или волнами и как считать расхождения. Выбрали "
    "PostgreSQL с транзакционным переносом и сверку сумм по дням."
)


# --- P0: Слепой свидетель - это подтверждение, а не отказ -----------------


def test_blind_witness_creates_no_decline_record(signed_client):
    """Кандидат подтвердил опыт, просто не раскрыл материалы.

    Это не отказ: DeclineRecord появляется только от явного «не подтверждать».
    """
    response = signed_client.post(BLIND_WITNESS, json={"answer": NDA_ANSWER})

    assert response.status_code == 201
    profile = response.json()

    assert profile["declines"] == []
    with SessionLocal() as db:
        assert db.query(DeclineRecord).count() == 0


def test_blind_witness_does_not_mark_the_statement_declined(signed_client):
    profile = signed_client.post(BLIND_WITNESS, json={"answer": NDA_ANSWER}).json()

    assert profile["statements"], "ответ разобран в компетенции"
    assert all(statement["declined"] is False for statement in profile["statements"])


def test_blind_witness_is_evidence_and_lifts_the_status(signed_client):
    profile = signed_client.post(BLIND_WITNESS, json={"answer": NDA_ANSWER}).json()

    evidence = profile["evidence"][0]
    assert evidence["type"] == TYPE_BLIND_WITNESS
    assert evidence["nda"] is True
    assert evidence["url"] is None and evidence["file_ref"] is None

    assert all(statement["status"] == MEDIUM for statement in profile["statements"])


def test_nda_is_never_a_penalty_for_the_index(signed_client):
    """Отсутствие публичного следа не должно стоить кандидату баллов."""
    signed_client.post(ROLES, json={"level": "Middle"})
    before = signed_client.get(PROF).json()["snapshots"][0]["overall_score"]

    signed_client.post(BLIND_WITNESS, json={"answer": NDA_ANSWER})

    after = signed_client.get(PROF).json()["snapshots"][0]["overall_score"]
    assert after > before


def test_decline_still_works_as_an_explicit_action(signed_client):
    """Право отказаться никуда не делось - оно просто отдельное действие."""
    added = signed_client.post(LINK, json={"url": "https://github.com/nataly/tools"}).json()
    evidence_id = added["evidence"][0]["id"]

    profile = signed_client.post(
        f"{PROFILE}/evidence/{evidence_id}/decline", json={}
    ).json()

    assert len(profile["declines"]) == 1
    assert profile["declines"][0]["target_type"] == "evidence"


# --- P0: что означает pending ---------------------------------------------


def test_pending_evidence_counts_towards_the_status():
    """Каноническое поведение: pending - это «доказательство есть».

    Внешней проверки источников в MVP нет, поэтому pending не может означать
    «пока не считается» - иначе не считалось бы вообще ничего.
    """
    view = compute_status([EvidenceFacts(type="link", source_category="github", status=PENDING)])
    assert view.status == MEDIUM


def test_only_declined_evidence_drops_out_of_the_calculation():
    active = EvidenceFacts(type="free_text", source_category=None, status=PENDING)
    declined = EvidenceFacts(type="link", source_category="github", status=DECLINED)

    assert compute_status([active, declined]).status == compute_status([active]).status == LIMITED


def test_new_evidence_is_created_as_pending(signed_client):
    signed_client.post(LINK, json={"url": "https://github.com/nataly/tools"})
    signed_client.post(BLIND_WITNESS, json={"answer": NDA_ANSWER})

    with SessionLocal() as db:
        assert {item.status for item in db.query(Evidence).all()} == {PENDING}


# --- P1: отрицания не превращаются в компетенции --------------------------


def test_refusal_to_use_a_technology_is_not_experience_with_it():
    found = {item.skill_name for item in parse_free_text("Мы отказались от Redis.")}
    assert "Caching" not in found


def test_explicit_lack_of_experience_is_not_a_competency():
    found = {item.skill_name for item in parse_free_text("Я не работал с Kubernetes.")}
    assert "Kubernetes" not in found


def test_hypothetical_plans_are_not_competencies():
    found = {item.skill_name for item in parse_free_text("Планирую изучить Go в этом году.")}
    assert "Go" not in found


def test_negation_does_not_spill_over_to_the_next_clause():
    """«Не работал с Kubernetes, но занимался Docker» - Docker остаётся."""
    found = {
        item.skill_name
        for item in parse_free_text("Я не работал с Kubernetes, но плотно занимался Docker.")
    }

    assert "Docker" in found
    assert "Kubernetes" not in found


def test_positive_mentions_still_get_through():
    found = {
        item.skill_name
        for item in parse_free_text("Добавили Redis и переработали индексы в PostgreSQL.")
    }

    assert {"Caching", "PostgreSQL"} <= found


def test_not_only_is_not_a_negation():
    found = {item.skill_name for item in parse_free_text("Использовали не только Redis, но и Kafka.")}
    assert {"Caching", "Message queues"} <= found


def test_assertion_type_is_reported_for_future_replacement():
    sentence = "Мы отказались от Redis, зато внедрили Kafka."
    assert assertion_type(sentence, sentence.index("Redis")) == NEGATIVE
    assert assertion_type(sentence, sentence.index("Kafka")) == POSITIVE
    assert assertion_type("Если бы мы взяли Kafka, было бы проще.", 17) == HYPOTHETICAL

    for item in parse_free_text("Добавили Redis и переработали индексы."):
        assert item.assertion_type == POSITIVE


def test_negative_mention_does_not_reach_the_profile(signed_client):
    parsed = signed_client.post(
        PARSE, json={"raw_text": "С Kubernetes не работал. Зато Docker знаю хорошо."}
    ).json()

    found = {item["skill_name"] for item in parsed["items"]}
    assert "Kubernetes" not in found
    assert "Docker" in found


# --- P2: файл не остаётся на диске, если запрос не прошёл -----------------


def _stored_files(user_folder: Path) -> list[Path]:
    return list(user_folder.glob("*")) if user_folder.exists() else []


def test_upload_with_a_wrong_statement_id_leaves_no_file(signed_client):
    folder = Path(settings.upload_dir)
    before = sum(len(_stored_files(p)) for p in folder.glob("*")) if folder.exists() else 0

    response = signed_client.post(
        FILE,
        files={"file": ("diploma.png", b"\x89PNG\r\n\x1a\n" + b"0" * 50, "image/png")},
        data={"statement_ids": "stmt_999"},
    )

    assert response.status_code == 404
    after = sum(len(_stored_files(p)) for p in folder.glob("*")) if folder.exists() else 0
    assert after == before, "файл-сирота остался в хранилище"
    assert signed_client.get(PROFILE).json()["evidence"] == []


def test_upload_with_a_valid_statement_id_still_works(signed_client):
    profile = signed_client.post(
        f"{PROFILE}/statements", json={"skill_name_ru": "Тестирование"}
    ).json()
    statement_id = profile["statements"][0]["id"]

    response = signed_client.post(
        FILE,
        files={"file": ("diploma.png", b"\x89PNG\r\n\x1a\n" + b"0" * 50, "image/png")},
        data={"statement_ids": statement_id},
    )

    assert response.status_code == 201
    evidence = response.json()["evidence"][0]
    assert evidence["linked_statement_ids"] == [statement_id]


# --- полный путь кандидата ------------------------------------------------


def test_full_flow_from_registration_to_prof_recalculation(signed_client):
    """Профиль -> Evidence -> Statement -> PROF -> белые пятна -> усиление."""
    signed_client.post(ROLES, json={"level": "Middle"})
    assert signed_client.get(PROF).json()["snapshots"][0]["overall_score"] == 0

    parsed = signed_client.post(
        PARSE,
        json={
            "raw_text": (
                "Переписал биллинг на Python, добавили Redis и переработали индексы "
                "в PostgreSQL под нагрузкой в 3000 rps."
            )
        },
    ).json()
    signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]}
    )

    after_evidence = signed_client.get(PROF).json()["snapshots"][0]
    assert after_evidence["overall_score"] > 0
    assert after_evidence["white_spots"], "белые пятна показывают, что усиливать"

    gap = after_evidence["white_spots"][0]
    component = next(c for c in after_evidence["components"] if c["competency_id"] == gap)

    # Усиление через Слепого свидетеля: материалы не раскрываются, наказания нет.
    signed_client.post(
        f"{PROFILE}/statements", json={"skill_name_ru": component["suggested_skill_ru"]}
    )
    statement_id = next(
        s["id"]
        for s in signed_client.get(PROFILE).json()["statements"]
        if s["skill_name"] == component["suggested_skill_key"]
    )
    signed_client.post(
        BLIND_WITNESS, json={"answer": NDA_ANSWER, "statement_ids": [statement_id]}
    )

    final = signed_client.get(PROF).json()["snapshots"][0]
    assert final["overall_score"] > after_evidence["overall_score"]
    assert gap not in final["white_spots"]
    assert all(statement["declined"] is False for statement in signed_client.get(PROFILE).json()["statements"])
