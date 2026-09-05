"""Проверки модуля 11: цикл возвращения кандидата.

Гипотеза, которую проверяет модуль, самая неуверенная во всём продукте, и
поэтому проверяется здесь именно то, что её легко подделать:

* значимо только `acted_upon` — показ уведомления успехом не считается;
* про одну вакансию не напоминают дважды;
* закрытый пробел виден не только в той вакансии, ради которой вернулись.
"""

import inspect
from datetime import datetime, timedelta, timezone

from app import growth
from app.db import SessionLocal
from app.models import ProfileGrowthEvent, ReturnTrigger, VacancyCheckpoint
from app.routers import retention as module
from app.routers.retention import MIN_MATCH_SCORE_TO_NOTIFY, NEW_MATCHING_VACANCY

RETENTION = "/api/retention"
CHECK = "/api/retention/check"
FEED = "/api/vacancies"
EXPLANATIONS = "/api/explanations"
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

API_TEXT = (
    "Проектировал REST API для внешних партнёров, отдельно занимался gRPC. "
    "Писал автотесты на pytest для всех интеграций."
)

# Широкий текст: закрывает сразу несколько разных требований, поэтому годится
# для проверки, что закрытый пробел засчитывается той вакансии, по которой
# пришёл повод, какой бы она ни была.
BROAD_TEXT = (
    "Оптимизировал тяжёлые SQL-запросы в PostgreSQL и добавил кеширование в Redis. "
    "Отдельно проектировал REST API для партнёров и покрыл интеграции автотестами на pytest."
)


def setup_candidate(client, level="Middle"):
    client.post(ROLES, json={"level": level})
    parsed = client.post(PARSE, json={"raw_text": CASE_TEXT}).json()
    client.post(ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]})
    ids = [item["id"] for item in client.get(PROFILE).json()["statements"]]
    client.post(LINK, json={"url": "https://github.com/dev/billing", "statement_ids": ids})


def strengthen(client, text, url):
    parsed = client.post(PARSE, json={"raw_text": text}).json()
    client.post(ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]})
    ids = [item["id"] for item in client.get(PROFILE).json()["statements"]]
    client.post(LINK, json={"url": url, "statement_ids": ids})


def rewind_checkpoint(days=30):
    """Отматывает отметку «до какого момента видели» — иначе нового не будет."""
    with SessionLocal() as db:
        row = db.query(VacancyCheckpoint).first()
        row.last_checked_at = datetime.now(timezone.utc) - timedelta(days=days)
        db.commit()


# --- US1: повод появляется --------------------------------------------------


def test_first_visit_does_not_dump_the_whole_feed_as_new(signed_client):
    """Иначе в первую же секунду прилетело бы семь «новых» вакансий."""
    setup_candidate(signed_client)
    payload = signed_client.post(CHECK).json()

    assert payload["triggers"] == []


def test_new_relevant_vacancy_produces_exactly_one_trigger(signed_client):
    setup_candidate(signed_client)
    signed_client.post(CHECK)
    rewind_checkpoint()

    payload = signed_client.post(CHECK).json()

    assert payload["triggers"]
    ids = [item["vacancy_id"] for item in payload["triggers"]]
    assert len(ids) == len(set(ids))


def test_nothing_below_the_threshold_is_notified(signed_client):
    """FR1.1: порог — калибруемая константа, а не «на глаз»."""
    setup_candidate(signed_client)
    signed_client.post(CHECK)
    rewind_checkpoint()

    payload = signed_client.post(CHECK).json()
    assert payload["min_match_score_to_notify"] == MIN_MATCH_SCORE_TO_NOTIFY
    assert all(
        item["match_score_at_detection"] >= MIN_MATCH_SCORE_TO_NOTIFY
        for item in payload["triggers"]
    )


def test_the_same_vacancy_is_never_notified_twice(signed_client):
    """FR1.2: одна вакансия — максимум один повод, даже когда профиль вырос.

    Другие вакансии при этом могут впервые перешагнуть порог, и сообщить о них
    как раз правильно: запрет касается повтора, а не новых совпадений.
    """
    setup_candidate(signed_client)
    signed_client.post(CHECK)
    rewind_checkpoint()
    first = {item["vacancy_id"] for item in signed_client.post(CHECK).json()["triggers"]}
    assert first

    strengthen(signed_client, BROAD_TEXT, "https://github.com/dev/api")
    rewind_checkpoint()
    signed_client.post(CHECK)

    with SessionLocal() as db:
        rows = db.query(ReturnTrigger).filter_by(trigger_type=NEW_MATCHING_VACANCY).all()
        by_vacancy = [row.related_ref for row in rows]

    assert len(by_vacancy) == len(set(by_vacancy))
    assert first <= set(by_vacancy)


def test_a_grown_profile_alone_does_not_re_notify(signed_client):
    """Без «прихода» новой вакансии рост профиля поводов не создаёт."""
    setup_candidate(signed_client)
    signed_client.post(CHECK)
    rewind_checkpoint()
    signed_client.post(CHECK)

    with SessionLocal() as db:
        before = db.query(ReturnTrigger).filter_by(trigger_type=NEW_MATCHING_VACANCY).count()

    strengthen(signed_client, BROAD_TEXT, "https://github.com/dev/api")
    signed_client.post(CHECK)

    with SessionLocal() as db:
        after = db.query(ReturnTrigger).filter_by(trigger_type=NEW_MATCHING_VACANCY).count()

    assert after == before


def test_score_at_detection_stays_true_to_the_moment(signed_client):
    """Обещание «62%» не должно задним числом «уточняться»."""
    setup_candidate(signed_client)
    signed_client.post(CHECK)
    rewind_checkpoint()
    before = signed_client.post(CHECK).json()["triggers"][0]

    strengthen(signed_client, API_TEXT, "https://github.com/dev/api")
    after = next(
        item
        for item in signed_client.get(RETENTION).json()["triggers"]
        if item["vacancy_id"] == before["vacancy_id"]
    )

    assert after["match_score_at_detection"] == before["match_score_at_detection"]
    assert after["match_score_now"] >= after["match_score_at_detection"]


# --- US2: объяснение --------------------------------------------------------


def test_notification_carries_a_factual_explanation(signed_client):
    """FR2.1: не «вам подойдёт», а сколько требований закрыто и чего нет."""
    setup_candidate(signed_client)
    signed_client.post(CHECK)
    rewind_checkpoint()

    trigger = signed_client.post(CHECK).json()["triggers"][0]

    assert "Совпадение" in trigger["explanation_ru"]
    assert "обязательных требований" in trigger["explanation_ru"]
    for forbidden in ("подойдёт", "интересн", "рекомендуем"):
        assert forbidden not in trigger["explanation_ru"].lower()


def test_explanation_lives_in_the_one_shared_view(signed_client):
    """FR2.3: та же точка «Почему такой вывод?», что у всех прочих выводов."""
    setup_candidate(signed_client)
    signed_client.post(CHECK)
    rewind_checkpoint()
    trigger = signed_client.post(CHECK).json()["triggers"][0]

    detail = signed_client.get(f"{EXPLANATIONS}/{trigger['explanation_id']}").json()

    assert detail["subject_type"] == "vacancy_match"
    assert detail["conclusion_ru"] == trigger["explanation_ru"]
    assert detail["disputable"] is True
    assert detail["problems"] == []


def test_explanation_is_traceable_to_the_requirement_breakdown(signed_client):
    """FR2.2: своего суждения о релевантности модуль не изобретает."""
    setup_candidate(signed_client)
    signed_client.post(CHECK)
    rewind_checkpoint()
    trigger = signed_client.post(CHECK).json()["triggers"][0]

    detail = signed_client.get(f"{EXPLANATIONS}/{trigger['explanation_id']}").json()
    vacancy = signed_client.get(f"{FEED}/{trigger['vacancy_id']}").json()

    requirement_ids = {
        item["requirement_id"] for item in vacancy["covered"] + vacancy["uncovered"]
    }
    assert set(detail["evidence_refs"]) == requirement_ids


# --- US3/US4: возвращение и накопительный эффект ---------------------------


def test_module_builds_no_scoring_of_its_own():
    """FR4.4: это цикл вокруг чужого расчёта, а не второй расчёт."""
    source = inspect.getsource(module)

    assert "STATUS_SCORE" not in source
    assert "CRITICALITY_WEIGHT" not in source
    assert "match_for" in source


def test_closing_a_gap_shows_up_across_other_vacancies(signed_client):
    """FR4.2/FR4.3: накопительный эффект виден, а не считается молча."""
    setup_candidate(signed_client)
    signed_client.get(RETENTION)

    strengthen(signed_client, API_TEXT, "https://github.com/dev/api")
    payload = signed_client.get(RETENTION).json()

    assert payload["cross_vacancy_events"], "закрытый пробел должен помочь не одной вакансии"
    assert "ещё в" in payload["cross_vacancy_events"][0]["description_ru"]


def test_cross_vacancy_effect_lands_in_the_growth_history(signed_client):
    setup_candidate(signed_client)
    signed_client.get(RETENTION)
    strengthen(signed_client, API_TEXT, "https://github.com/dev/api")
    signed_client.get(RETENTION)

    with SessionLocal() as db:
        events = (
            db.query(ProfileGrowthEvent)
            .filter_by(event_type=growth.MATCH_ACROSS_VACANCIES)
            .all()
        )
    assert events


def test_opening_a_trigger_is_not_an_action(signed_client):
    """§6 FR-Constraint.2: открыл — ещё не значит сделал."""
    setup_candidate(signed_client)
    signed_client.post(CHECK)
    rewind_checkpoint()
    trigger = signed_client.post(CHECK).json()["triggers"][0]

    payload = signed_client.post(f"{RETENTION}/triggers/{trigger['id']}/open").json()

    assert payload["stats"]["acted_upon"] == 0
    assert payload["stats"]["sent"] >= 1


def close_gap(client, competency_ru, text, urls):
    """Закрывает пробел так, как это делает кандидат: рассказ плюс источники.

    Тест не подкручивает состояние в обход продукта — иначе он проверял бы не
    то, что происходит на самом деле.
    """
    parsed = client.post(PARSE, json={"raw_text": text}).json()
    client.post(ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]})

    statement = next(
        item
        for item in client.get(PROFILE).json()["statements"]
        if item["skill_name_ru"] == competency_ru
    )
    for url in urls:
        client.post(LINK, json={"url": url, "statement_ids": [statement["id"]]})
    return statement


def test_only_a_closed_requirement_counts_as_acted_upon(signed_client):
    """FR-Constraint.2: значимая величина одна, и она про действие.

    Повод приходит по вакансии биллинга; закрываем именно её незакрытое
    обязательное требование — оптимизацию запросов.
    """
    setup_candidate(signed_client)
    signed_client.post(CHECK)
    rewind_checkpoint()
    trigger = signed_client.post(CHECK).json()["triggers"][0]
    assert trigger["vacancy_id"] == "vac_004"
    assert signed_client.get(RETENTION).json()["stats"]["acted_upon"] == 0

    close_gap(
        signed_client,
        "Оптимизация запросов",
        "Оптимизировал запросы к отчётам: убрал N+1 и разобрал explain analyze.",
        ("https://github.com/dev/reports", "https://habr.com/ru/articles/900001"),
    )
    after = signed_client.get(RETENTION).json()

    assert after["stats"]["acted_upon"] >= 1
    assert after["stats"]["acted_upon_ratio"] is not None


def test_dismissing_is_not_acting(signed_client):
    setup_candidate(signed_client)
    signed_client.post(CHECK)
    rewind_checkpoint()
    trigger = signed_client.post(CHECK).json()["triggers"][0]

    payload = signed_client.post(f"{RETENTION}/triggers/{trigger['id']}/dismiss").json()

    assert all(item["id"] != trigger["id"] for item in payload["triggers"])
    assert payload["stats"]["acted_upon"] == 0


def test_unknown_trigger_is_not_found(signed_client):
    setup_candidate(signed_client)
    assert signed_client.post(f"{RETENTION}/triggers/rt_999/open").status_code == 404


# --- ограничения ------------------------------------------------------------


def test_no_apply_flow_appears_here_either():
    """§6 FR-Constraint.1: уведомление ведёт к усилению профиля, не к отклику."""
    source = inspect.getsource(module).lower()
    for forbidden in ("apply", "откликн", "заявк"):
        assert forbidden not in source


def test_recruiter_interest_trigger_is_still_not_produced(signed_client):
    """§0: этот повод требует рекрутерской стороны — здесь его нет."""
    setup_candidate(signed_client)
    signed_client.post(CHECK)

    with SessionLocal() as db:
        kinds = {row.trigger_type for row in db.query(ReturnTrigger).all()}
    assert "recruiter_interest" not in kinds


def test_threshold_is_a_named_constant_not_an_inline_number():
    source = inspect.getsource(module)
    assert "MIN_MATCH_SCORE_TO_NOTIFY = 55" in source
    assert source.count("< 55") == 0
