"""Проверки модуля 4: Contextual Probe.

Отдельно - генерация вопроса и разбор ответа (без базы), отдельно - поведение
API: по чему спрашиваем, что видно кандидату рядом с вопросом, что происходит с
ответом, отказом по NDA и пропуском.
"""

from dataclasses import fields

from app.db import SessionLocal
from app.declines import TARGET_QUESTION
from app.enrichment import MEDIUM, TYPE_PROBE_ANSWER
from app.models import DeclineRecord, ProbeAnswer, ProbeFeedback, ProbeQuestion
from app.probe import (
    FREE_TEXT,
    MODE_NDA,
    TARGET_CONTRADICTION,
    Artifact,
    build_reason,
    follow_up_reason,
    generate_question,
    is_too_generic,
    missing_expected_terms,
    pick_detail,
)
from app.probe_templates import TEMPLATES, Template
from app.routers.probe import FEEDBACK_REASONS, NO_ROLE

PROBE = "/api/probe"
NEXT = "/api/probe/next"
HISTORY = "/api/probe/history"
ROLES = "/api/prof/roles"
PARSE = "/api/profile/parse"
ACCEPT = "/api/profile/statements/accept"
LINK = "/api/profile/evidence/link"
PROF = "/api/prof"

CASE = (
    "Переписал биллинг с нуля на Python, вынес его в отдельный микросервис. "
    "Под нагрузкой в 3000 rps старая схема не держала, поэтому добавили Redis "
    "и переработали индексы в PostgreSQL. Ускорил отчёты с 40 секунд до 2."
)

DETAILED_ANSWER = (
    "Упирались в диск: PostgreSQL читал по 200 тысяч строк на каждый отчёт, "
    "потому что индекс не покрывал сортировку. Смотрели план запроса, добавили "
    "составной индекс и переписали выборку — p99 упал с 40 секунд до 2."
)

VAGUE_ANSWER = "Мы просто стали работать лучше и всё стало быстрее, команда молодец."


def setup_profile(client, *, level="Middle"):
    """Кандидат с описанием проекта и заявленным уровнем."""
    client.post(ROLES, json={"level": level})
    parsed = client.post(PARSE, json={"raw_text": CASE}).json()
    client.post(ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]})
    return client.get(PROBE).json()


def ask(client, competency_id=None):
    return client.post(NEXT, json={"competency_id": competency_id}).json()["question"]


# --- US2: генерация вопроса ----------------------------------------------


def test_detail_is_taken_from_a_sentence_about_the_competency():
    artifacts = [
        Artifact(
            "ev_001",
            "text",
            "Вчера был дождь. Переработали индексы в PostgreSQL и ускорили отчёты.",
        )
    ]
    detail = pick_detail(artifacts, ("PostgreSQL", "Database design"))

    assert detail is not None
    assert "PostgreSQL" in detail.content


def test_question_is_built_around_the_candidates_own_words():
    """FR2.3: вопрос ссылается на то, что найдётся только у этого кандидата."""
    question = generate_question(
        "database_design", [Artifact("ev_003", "text", CASE)], ("PostgreSQL", "Database design")
    )

    assert question.grounded is True
    assert question.artifact_evidence_id == "ev_003"
    assert "PostgreSQL" in question.text_ru
    assert "{detail}" not in question.text_ru


def test_question_falls_back_to_template_only_and_is_tagged():
    question = generate_question("database_design", [], ("Database design",))

    assert question.grounded is False
    assert question.artifact_evidence_id is None
    assert question.template_id.endswith("_generic")


def test_no_template_means_no_question_at_all():
    # FR1.5: выдумывать вопрос «на всякий случай» модуль не имеет права.
    assert generate_question("competency_without_templates", [], ()) is None


def test_link_artifact_is_usable_when_there_is_no_quote():
    question = generate_question(
        "caching", [Artifact("ev_007", "source", "https://github.com/nataly/cache")], ("Caching",)
    )

    assert question.grounded is True
    assert "github.com/nataly/cache" in question.text_ru


# --- US3: только свободная форма -----------------------------------------


def test_templates_never_offer_answer_options():
    """FR3.1: вариантов ответа в модуле нет ни в одном шаблоне."""
    forbidden = ("выберите вариант", "a)", "б)", "1)", "2)", "верно/неверно", "да или нет")
    for template in TEMPLATES:
        lowered = template.text.lower()
        assert not any(marker in lowered for marker in forbidden), template.id


def test_templates_elicit_reasoning_not_a_single_fact():
    """FR3.2: вопрос про «почему/как», а не про запоминание строки."""
    markers = ("почему", "как ", "как вы", "что бы", "за счёт", "по каким", "что произойдёт")
    for template in TEMPLATES:
        lowered = template.text.lower()
        assert any(marker in lowered for marker in markers), template.id


def test_no_correct_answer_is_stored_anywhere():
    """FR3.3: сверять ответ не с чем - правильной строки в модели нет."""
    names = {f.name for f in fields(Template)}
    assert not names & {"answer", "correct", "correct_answer", "expected_answer", "key"}


def test_answer_format_is_fixed(signed_client):
    setup_profile(signed_client)
    state = signed_client.post(NEXT, json={}).json()
    assert state["answer_format"] == FREE_TEXT
    assert state["question"]["answer_format"] == FREE_TEXT

    signed_client.post(
        f"{PROBE}/questions/{state['question']['id']}/answer", json={"text": DETAILED_ANSWER}
    )
    with SessionLocal() as db:
        assert db.query(ProbeAnswer).one().format == FREE_TEXT


# --- US4: прозрачность ----------------------------------------------------


def test_every_question_carries_the_reason_it_was_asked():
    question = generate_question(
        "database_design", [], ("Database design",), competency_name_ru="Проектирование баз данных"
    )
    assert "Проектирование баз данных" in question.reason_ru
    assert "недостаточно независимых подтверждений" in question.reason_ru


def test_contradiction_target_is_explained_differently():
    """FR4.2: одной общей фразой на оба типа цели обойтись нельзя."""
    white_spot = build_reason("Кеширование", "white_spot", "artifact_grounded")
    contradiction = build_reason("Кеширование", TARGET_CONTRADICTION, "artifact_grounded")

    assert white_spot != contradiction
    assert "расхождение" in contradiction


def test_nda_rephrase_explains_that_materials_stay_closed():
    question = generate_question(
        "caching", [], ("Caching",), mode=MODE_NDA, competency_name_ru="Кеширование"
    )
    assert question.nda_abstract is True
    assert "раскрывать материалы не нужно" in question.reason_ru


def test_api_never_returns_a_question_without_a_reason(signed_client):
    setup_profile(signed_client)
    question = ask(signed_client)

    assert question["reason_ru"].strip()
    assert question["competency_name_ru"] in question["reason_ru"]


def test_follow_up_says_it_is_the_same_check(signed_client):
    """FR4.3: уточнение не появляется из ниоткуда."""
    setup_profile(signed_client)
    question = ask(signed_client)

    state = signed_client.post(
        f"{PROBE}/questions/{question['id']}/answer", json={"text": VAGUE_ANSWER}
    ).json()

    follow_up = state["follow_up"]
    assert follow_up["reason_ru"].startswith("Уточнение по той же компетенции")
    assert question["competency_name_ru"] in follow_up["reason_ru"]


def test_history_keeps_questions_and_their_reasons(signed_client):
    """FR4.4: кандидат может вернуться и посмотреть, что спрашивали и почему."""
    setup_profile(signed_client)
    answered = ask(signed_client)
    signed_client.post(
        f"{PROBE}/questions/{answered['id']}/answer", json={"text": DETAILED_ANSWER}
    )
    skipped = ask(signed_client)
    signed_client.post(f"{PROBE}/questions/{skipped['id']}/skip")

    history = signed_client.get(HISTORY).json()
    by_id = {item["id"]: item for item in history}

    assert by_id[answered["id"]]["reason_ru"] == answered["reason_ru"]
    assert by_id[answered["id"]]["answer_text"] == DETAILED_ANSWER
    assert by_id[answered["id"]]["status_ru"] == "Отвечен"
    assert by_id[skipped["id"]]["status_ru"] == "Пропущен"
    assert all(item["reason_ru"].strip() for item in history)


# --- US5: отказ по NDA ----------------------------------------------------


def test_nda_decline_offers_an_abstract_version_of_the_same_check(signed_client):
    setup_profile(signed_client)
    question = ask(signed_client)

    state = signed_client.post(
        f"{PROBE}/questions/{question['id']}/decline", json={}
    ).json()

    replacement = state["question"]
    assert replacement is not None
    assert replacement["nda_abstract"] is True
    assert replacement["competency_id"] == question["competency_id"]
    assert replacement["id"] != question["id"]
    assert state["declined_count"] == 1


def test_nda_decline_uses_the_same_decline_record_as_module_two(signed_client):
    """FR5.5: второй реализации права на отказ в продукте нет."""
    setup_profile(signed_client)
    question = ask(signed_client)

    signed_client.post(f"{PROBE}/questions/{question['id']}/decline", json={})

    with SessionLocal() as db:
        record = db.query(DeclineRecord).filter_by(target_type=TARGET_QUESTION).one()
        assert record.target_id == int(question["id"].split("_")[1])
        assert record.reason is None

        stored = db.get(ProbeQuestion, record.target_id)
        assert stored.status == "declined_nda"


def test_declining_the_rephrase_too_is_just_a_skip(signed_client):
    """FR5.3: через переформулировку никого не протаскивают силой."""
    setup_profile(signed_client)
    question = ask(signed_client)
    rephrase = signed_client.post(
        f"{PROBE}/questions/{question['id']}/decline", json={}
    ).json()["question"]

    state = signed_client.post(
        f"{PROBE}/questions/{rephrase['id']}/decline", json={}
    ).json()

    # Третьего вопроса по той же компетенции не появляется.
    assert state["question"] is None or state["question"]["competency_id"] != question[
        "competency_id"
    ]


def test_nda_decline_changes_no_score(signed_client):
    """FR5.4: отказ ничего и нигде не отнимает."""
    setup_profile(signed_client)
    before = signed_client.get(PROF).json()["snapshots"][0]
    question = ask(signed_client)

    signed_client.post(f"{PROBE}/questions/{question['id']}/decline", json={"reason": "NDA"})

    after = signed_client.get(PROF).json()["snapshots"][0]
    assert after["overall_score"] == before["overall_score"]
    assert after["white_spots"] == before["white_spots"]


def test_nda_decline_is_reversible(signed_client):
    setup_profile(signed_client)
    question = ask(signed_client)
    signed_client.post(f"{PROBE}/questions/{question['id']}/decline", json={})

    signed_client.delete(f"{PROBE}/questions/{question['id']}/decline")

    with SessionLocal() as db:
        assert db.query(DeclineRecord).filter_by(target_type=TARGET_QUESTION).count() == 0

    assert signed_client.get(HISTORY).json()[-1]["declined"] is False


def test_question_declines_do_not_pollute_the_evidence_map(signed_client):
    setup_profile(signed_client)
    question = ask(signed_client)
    signed_client.post(f"{PROBE}/questions/{question['id']}/decline", json={})

    profile = signed_client.get("/api/profile").json()
    assert all(d["target_type"] != "question" for d in profile["declines"])


# --- §5.6: два независимых сигнала ---------------------------------------


def test_confirming_answer_gives_understanding_but_no_new_competency(signed_client):
    """Строка 1 таблицы §5.6."""
    setup_profile(signed_client)
    question = ask(signed_client, "database_design")

    signed_client.post(
        f"{PROBE}/questions/{question['id']}/answer", json={"text": DETAILED_ANSWER}
    )

    with SessionLocal() as db:
        answer = db.query(ProbeAnswer).one()
        assert answer.understanding_signal is True
        assert answer.new_competency_signal is False

    snapshot = signed_client.get(PROF).json()["snapshots"][0]
    database = next(c for c in snapshot["components"] if c["competency_id"] == "database_design")
    assert database["status"] == MEDIUM
    assert "Contextual Probe" in database["reason"]


def test_revealed_competency_gives_both_signals(signed_client):
    """Строка 2 таблицы §5.6: всплывшее под живым вопросом - тоже подтверждение."""
    setup_profile(signed_client)
    question = ask(signed_client)

    signed_client.post(
        f"{PROBE}/questions/{question['id']}/answer",
        json={
            "text": (
                "Сначала прогнали нагрузочные тесты, потом закрыли дыру в авторизации: "
                "добавили проверку подписи jwt и вынесли секреты из репозитория. "
                "Kubernetes переехал в отдельный неймспейс, чтобы лимиты не пересекались."
            )
        },
    )

    with SessionLocal() as db:
        answer = db.query(ProbeAnswer).one()
        assert answer.new_competency_signal is True
        assert answer.understanding_signal is True

    profile = signed_client.get("/api/profile").json()
    discovered = [s for s in profile["statements"] if s["source_of_claim"] == "probe"]
    assert any(s["skill_name"] in ("Security", "Kubernetes") for s in discovered)


def test_answer_that_stays_generic_gives_no_signals_and_no_penalty(signed_client):
    """Строка 3 таблицы §5.6: ноль, а не минус."""
    setup_profile(signed_client)
    before = signed_client.get(PROF).json()["snapshots"][0]
    question = ask(signed_client)

    state = signed_client.post(
        f"{PROBE}/questions/{question['id']}/answer", json={"text": VAGUE_ANSWER}
    ).json()
    signed_client.post(
        f"{PROBE}/follow-ups/{state['follow_up']['id']}/answer", json={"text": "Ну просто лучше."}
    )

    with SessionLocal() as db:
        answer = db.query(ProbeAnswer).one()
        assert answer.understanding_signal is False
        assert answer.new_competency_signal is False
        assert answer.evidence_id is None

    after = signed_client.get(PROF).json()["snapshots"][0]
    assert after["overall_score"] == before["overall_score"]

    profile = signed_client.get("/api/profile").json()
    assert not [e for e in profile["evidence"] if e["type"] == TYPE_PROBE_ANSWER]


def test_clarified_answer_becomes_evidence(signed_client):
    setup_profile(signed_client)
    question = ask(signed_client, "database_design")
    state = signed_client.post(
        f"{PROBE}/questions/{question['id']}/answer", json={"text": VAGUE_ANSWER}
    ).json()

    signed_client.post(
        f"{PROBE}/follow-ups/{state['follow_up']['id']}/answer", json={"text": DETAILED_ANSWER}
    )

    with SessionLocal() as db:
        answer = db.query(ProbeAnswer).one()
        assert answer.understanding_signal is True
        assert answer.evidence_id is not None

    profile = signed_client.get("/api/profile").json()
    evidence = next(e for e in profile["evidence"] if e["type"] == TYPE_PROBE_ANSWER)
    assert VAGUE_ANSWER in evidence["raw_text"]
    assert DETAILED_ANSWER in evidence["raw_text"]


def test_answer_raises_the_prof_index_without_any_extra_step(signed_client):
    setup_profile(signed_client)
    before = signed_client.get(PROF).json()["snapshots"][0]["overall_score"]
    question = ask(signed_client)

    signed_client.post(
        f"{PROBE}/questions/{question['id']}/answer", json={"text": DETAILED_ANSWER}
    )

    assert signed_client.get(PROF).json()["snapshots"][0]["overall_score"] > before


# --- US1: по чему спрашиваем ---------------------------------------------


def test_probe_requires_login(client):
    assert client.get(PROBE).status_code == 401


def test_without_a_declared_level_there_is_nothing_to_ask(signed_client):
    state = signed_client.get(PROBE).json()

    assert state["available"] is False
    assert state["unavailable_reason"] == NO_ROLE
    assert state["question"] is None


def test_target_follows_module_three_priority(signed_client):
    state = setup_profile(signed_client)
    prof = signed_client.get(PROF).json()["snapshots"][0]

    assert state["next_target"]["competency_id"] == prof["white_spots"][0]


def test_question_is_generated_for_a_white_spot(signed_client):
    setup_profile(signed_client)
    question = ask(signed_client)
    prof = signed_client.get(PROF).json()["snapshots"][0]

    assert question["competency_id"] in prof["white_spots"]
    assert question["status"] == "pending"


def test_confirmed_competency_is_never_probed(signed_client):
    setup_profile(signed_client)
    profile = signed_client.get("/api/profile").json()
    python_statement = next(s["id"] for s in profile["statements"] if s["skill_name"] == "Python")
    signed_client.post(
        LINK,
        json={"url": "https://github.com/nataly/billing", "statement_ids": [python_statement]},
    )

    response = signed_client.post(NEXT, json={"competency_id": "core_language"})

    assert response.status_code == 400
    assert "уже подтверждена" in response.json()["detail"]


def test_pending_question_is_retired_when_the_gap_closes_elsewhere(signed_client):
    setup_profile(signed_client)
    question = ask(signed_client, "database_design")

    profile = signed_client.get("/api/profile").json()
    statement = next(
        s["id"]
        for s in profile["statements"]
        if s["skill_name"] in ("PostgreSQL", "Database design")
    )
    signed_client.post(
        LINK, json={"url": "https://github.com/nataly/db", "statement_ids": [statement]}
    )

    signed_client.get(PROBE)
    with SessionLocal() as db:
        assert db.get(ProbeQuestion, int(question["id"].split("_")[1])).status == "retired"


# --- пропуск, жалоба, приватность ----------------------------------------


def test_skipping_creates_nothing_and_takes_nothing_away(signed_client):
    setup_profile(signed_client)
    before = signed_client.get(PROF).json()["snapshots"][0]
    question = ask(signed_client)

    state = signed_client.post(f"{PROBE}/questions/{question['id']}/skip").json()

    assert state["skipped_count"] == 1
    after = signed_client.get(PROF).json()["snapshots"][0]
    assert after["overall_score"] == before["overall_score"]

    profile = signed_client.get("/api/profile").json()
    assert not [e for e in profile["evidence"] if e["type"] == TYPE_PROBE_ANSWER]


def test_bad_question_is_replaced_after_feedback(signed_client):
    setup_profile(signed_client)
    question = ask(signed_client)

    state = signed_client.post(
        f"{PROBE}/questions/{question['id']}/feedback",
        json={"reason": "not_related_to_project", "comment": "Это не про мой проект"},
    ).json()

    assert state["question"]["id"] != question["id"]
    assert state["question"]["template_id"] != question["template_id"]

    with SessionLocal() as db:
        feedback = db.query(ProbeFeedback).one()
        assert feedback.reason == "not_related_to_project"
        assert feedback.template_id == question["template_id"]
        assert db.get(ProbeQuestion, int(question["id"].split("_")[1])).status == "flagged_bad"


def test_feedback_reason_must_be_from_the_fixed_list(signed_client):
    setup_profile(signed_client)
    question = ask(signed_client)

    response = signed_client.post(
        f"{PROBE}/questions/{question['id']}/feedback", json={"reason": "просто не нравится"}
    )
    assert response.status_code == 400


def test_feedback_reasons_match_the_agreed_wording(signed_client):
    labels = [label for _, label in FEEDBACK_REASONS]

    assert labels == [
        "Не относится к моему проекту",
        "Не понимаю вопрос",
        "Слишком узкий/специфичный фреймворк",
        "Ошибка в контексте",
        "Другое",
    ]
    assert [r["label"] for r in signed_client.get(PROBE).json()["feedback_reasons"]] == labels


def test_keystroke_capture_is_off_and_nothing_is_stored_silently(signed_client):
    setup_profile(signed_client)
    state = signed_client.post(NEXT, json={}).json()
    assert state["keystroke_capture"] is False

    signed_client.post(
        f"{PROBE}/questions/{state['question']['id']}/answer",
        json={
            "text": DETAILED_ANSWER,
            "typed_duration_ms": 45210,
            "paste_attempts_blocked": 2,
            "keystroke_meta": '{"keys": "что-то"}',
        },
    )

    with SessionLocal() as db:
        answer = db.query(ProbeAnswer).one()
        assert answer.keystroke_meta is None
        assert answer.typed_duration_ms == 45210
        assert answer.paste_attempts_blocked == 2


def test_another_candidate_cannot_reach_someone_elses_question(signed_client, client):
    setup_profile(signed_client)
    question = ask(signed_client)
    signed_client.post("/api/auth/logout")

    client.post(
        "/api/auth/register", json={"email": "stranger@example.com", "password": "verysecret123"}
    )

    assert client.post(f"{PROBE}/questions/{question['id']}/skip").status_code == 404
    assert client.get(PROBE).json()["question"] is None
    assert client.get(HISTORY).json() == []


# --- эвристики разбора ----------------------------------------------------


def test_short_answer_is_too_generic():
    assert is_too_generic("Всё хорошо работало.") is True


def test_answer_with_specifics_is_not_generic():
    assert is_too_generic(DETAILED_ANSWER) is False


def test_long_but_empty_answer_is_still_generic():
    assert is_too_generic(VAGUE_ANSWER) is True


def test_jargon_trap_triggers_when_no_insider_term_appears():
    terms = ("инвалид", "ttl", "прогрев")
    assert missing_expected_terms("Мы положили данные в кеш и всё летало быстро", terms) is True
    assert missing_expected_terms("Инвалидируем по событию, ttl на сутки", terms) is False


def test_follow_up_reason_prefers_genericity_over_jargon():
    assert follow_up_reason("Стало лучше.", ("ttl",)) == "too_generic"
    assert follow_up_reason(DETAILED_ANSWER, ("совершенно_другое_слово",)) == "jargon_trap"
    assert follow_up_reason(DETAILED_ANSWER, ()) is None
