"""Проверки модуля 8: накопительный профиль и история роста.

Здесь проверяются гарантии, а не экраны:

* закрытие эпизода поиска не делает с профилем ничего;
* подтверждение принадлежит кандидату, а не роли, и переносится без вопросов;
* уже подтверждённое не переспрашивают - ни через время, ни при новой роли;
* устаревание влияет только на PROF.индекс и никогда на Trust Score;
* история роста только пополняется.
"""

import inspect
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import StatementError

from app import growth
from app.db import SessionLocal
from app.models import (
    AppendOnlyViolation,
    CompetencyFreshness,
    Evidence,
    ProfileGrowthEvent,
    ProfRole,
    ReturnTrigger,
    SearchContext,
    Statement,
    User,
)

GROWTH = "/api/growth"
PROF = "/api/prof"
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

MORE_TEXT = "Настроил CI/CD в GitLab и поднял мониторинг на Prometheus с алертами."


def setup_candidate(client, level="Middle"):
    client.post(ROLES, json={"level": level})
    parsed = client.post(PARSE, json={"raw_text": CASE_TEXT}).json()
    client.post(ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]})


def strengthen(client, statement_ids, url="https://github.com/dev/billing"):
    return client.post(LINK, json={"url": url, "statement_ids": statement_ids})


def statement_ids(client):
    return [item["id"] for item in client.get(PROFILE).json()["statements"]]


def user_row(db):
    return db.query(User).first()


def backdate_freshness(days):
    """Отматывает назад и записи актуальности, и сами доказательства.

    Одной записи мало: актуальность считается по датам доказательств этой
    компетенции, поэтому свежая ссылка честно вернула бы её в «актуально».
    """
    moment = datetime.now(timezone.utc) - timedelta(days=days)
    with SessionLocal() as db:
        for item in db.query(Evidence).all():
            item.created_at = moment
        for row in db.query(CompetencyFreshness).all():
            row.last_confirmed_at = moment
            row.decay_countdown_started_at = moment
        db.commit()


def backdate_role(days):
    """Отматывает объявление роли назад: напоминания завязаны на возраст профиля."""
    with SessionLocal() as db:
        for role in db.query(ProfRole).all():
            role.created_at = datetime.now(timezone.utc) - timedelta(days=days)
        db.commit()


# --- US1: ничего не пропадает --------------------------------------------


def test_closing_a_search_context_changes_nothing(signed_client):
    """FR1.1: конец поиска работы - не повод что-то удалять или прятать."""
    setup_candidate(signed_client)
    strengthen(signed_client, statement_ids(signed_client)[:1])

    before_profile = signed_client.get(PROFILE).json()
    before_prof = signed_client.get(PROF).json()
    before_trust = signed_client.get(TRUST).json()

    with SessionLocal() as db:
        user = user_row(db)
        context = SearchContext(user_id=user.id, label="Поиск осенью")
        db.add(context)
        db.commit()
        context.closed_at = datetime.now(timezone.utc)
        db.commit()

    assert signed_client.get(PROFILE).json()["statements"] == before_profile["statements"]
    assert signed_client.get(PROFILE).json()["evidence"] == before_profile["evidence"]
    assert (
        signed_client.get(PROF).json()["snapshots"][0]["overall_score"]
        == before_prof["snapshots"][0]["overall_score"]
    )
    assert signed_client.get(TRUST).json()["components"] == before_trust["components"]


def test_no_module_deletes_statements_or_evidence_on_context_close():
    """FR1.1 как проверка кода: каскадов от эпизода поиска нет ни у кого.

    Гарантия должна держаться конструкцией, а не аккуратностью: сама
    возможность связать удаление с концом поиска - уже дефект.
    """
    from app.routers import growth as growth_router
    from app.routers import moderation, nda, probe, prof, profile, trust, xai

    for module in (growth_router, moderation, nda, probe, prof, profile, trust, xai):
        source = inspect.getsource(module)
        assert "search_context" not in source.lower() or module is growth_router
        assert "SearchContext" not in source


def test_search_context_has_no_cascade_to_evidence():
    """У связи нет ни каскада, ни обратной ссылки, которой можно было бы
    воспользоваться, чтобы что-то снести."""
    assert not hasattr(SearchContext, "evidence")
    assert not hasattr(SearchContext, "statements")


# --- US2: подтверждение принадлежит кандидату ----------------------------


def test_status_is_global_not_per_role(signed_client):
    """FR2.1: вторая роль читает те же самые записи, а не свои копии."""
    setup_candidate(signed_client, "Middle")
    strengthen(signed_client, statement_ids(signed_client))

    middle = signed_client.get(PROF).json()["snapshots"][0]
    signed_client.post(ROLES, json={"level": "Senior"})

    payload = signed_client.get(PROF).json()
    by_level = {item["level"]: item for item in payload["snapshots"]}
    senior = by_level["Senior"]

    shared = {c["competency_id"] for c in middle["components"]} & {
        c["competency_id"] for c in senior["components"]
    }
    assert shared

    middle_status = {c["competency_id"]: c["status"] for c in middle["components"]}
    senior_status = {c["competency_id"]: c["status"] for c in senior["components"]}
    for competency_id in shared:
        assert middle_status[competency_id] == senior_status[competency_id]


def test_new_role_asks_nothing_about_already_confirmed(signed_client):
    """FR2.2/FR3.2: объявление второй роли не рождает вопросов по закрытому."""
    setup_candidate(signed_client, "Middle")
    strengthen(signed_client, statement_ids(signed_client))

    confirmed = {
        c["competency_id"]
        for c in signed_client.get(PROF).json()["snapshots"][0]["components"]
        if c["status"] in growth.CONFIRMED_STATUSES
    }
    assert confirmed, "нужна хотя бы одна подтверждённая компетенция"

    signed_client.post(ROLES, json={"level": "Senior"})

    for _ in range(5):
        probe = signed_client.get(PROBE).json()
        question = probe.get("question")
        if not question:
            break
        assert question["competency_id"] not in confirmed
        signed_client.post(f"{PROBE}/questions/{question['id']}/skip")


def test_reuse_across_roles_is_a_visible_event(signed_client):
    """FR2.4: перенос виден кандидату, а не растворяется в пересчёте."""
    setup_candidate(signed_client, "Middle")
    strengthen(signed_client, statement_ids(signed_client))
    signed_client.get(GROWTH)

    signed_client.post(ROLES, json={"level": "Senior"})
    payload = signed_client.get(GROWTH).json()

    reused = [
        event
        for period in payload["periods"]
        for event in period["events"]
        if event["event_type"] == growth.REUSED_ACROSS_ROLE
    ]
    assert reused
    assert "без дополнительных вопросов" in reused[0]["description_ru"]
    assert payload["stats"]["reused_across_roles"] == len(reused)


def test_carried_over_status_is_not_downgraded_by_a_stricter_role(signed_client):
    """FR2.3: пока правила сравнения глубины нет, статус переносится как есть.

    Молча заблокировать переиспользование было бы хуже: это ровно то
    «докажите заново», ради отсутствия которого существует модуль.
    """
    setup_candidate(signed_client, "Middle")
    strengthen(signed_client, statement_ids(signed_client))
    middle = signed_client.get(PROF).json()["snapshots"][0]

    signed_client.post(ROLES, json={"level": "Senior"})
    payload = signed_client.get(PROF).json()
    senior = next(item for item in payload["snapshots"] if item["level"] == "Senior")

    middle_status = {c["competency_id"]: c["status"] for c in middle["components"]}
    for component in senior["components"]:
        if component["competency_id"] in middle_status:
            assert component["status"] == middle_status[component["competency_id"]]


# --- US3: не спрашивают дважды -------------------------------------------


def test_returning_after_a_gap_never_re_asks(signed_client):
    """FR3.3: пауза не повод перепроверять уже доказанное."""
    setup_candidate(signed_client)
    strengthen(signed_client, statement_ids(signed_client))

    confirmed = {
        c["competency_id"]
        for c in signed_client.get(PROF).json()["snapshots"][0]["components"]
        if c["status"] in growth.CONFIRMED_STATUSES
    }

    with SessionLocal() as db:
        long_ago = datetime.now(timezone.utc) - timedelta(days=400)
        for item in db.query(Evidence).all():
            item.created_at = long_ago
        for item in db.query(Statement).all():
            item.updated_at = long_ago
        db.commit()

    for _ in range(5):
        question = signed_client.get(PROBE).json().get("question")
        if not question:
            break
        assert question["competency_id"] not in confirmed
        signed_client.post(f"{PROBE}/questions/{question['id']}/skip")


# --- US4: история роста ---------------------------------------------------


def test_history_reads_as_growth_not_as_a_database_dump(signed_client):
    """FR4.3: ведём итогом, а не механизмом."""
    setup_candidate(signed_client)
    strengthen(signed_client, statement_ids(signed_client)[:1])

    payload = signed_client.get(GROWTH).json()
    texts = [
        event["description_ru"] for period in payload["periods"] for event in period["events"]
    ]

    assert texts
    assert all("Evidence" not in text and "Statement" not in text for text in texts)
    assert any(text.startswith("Компетенция") for text in texts)


def test_history_is_grouped_by_month(signed_client):
    setup_candidate(signed_client)
    payload = signed_client.get(GROWTH).json()

    assert payload["periods"]
    assert all(period["label_ru"] and period["events"] for period in payload["periods"])


def test_history_covers_every_kind_of_strengthening(signed_client):
    """FR4.2: доказательство, статус, Trust и новая роль - всё попадает в ленту."""
    setup_candidate(signed_client)
    strengthen(signed_client, statement_ids(signed_client))
    signed_client.post(ROLES, json={"level": "Senior"})

    payload = signed_client.get(GROWTH).json()
    kinds = {
        event["event_type"] for period in payload["periods"] for event in period["events"]
    }

    assert growth.EVIDENCE_ADDED in kinds
    assert growth.STATUS_UPGRADED in kinds
    assert growth.ROLE_ADDED in kinds


def test_history_is_available_in_hidden_mode(signed_client):
    """FR4.4: скрытый профиль - тот же Self-Audit, а не урезанная версия."""
    setup_candidate(signed_client)
    strengthen(signed_client, statement_ids(signed_client)[:1])

    signed_client.put("/api/prof/visibility", json={"mode": "hidden"})
    hidden = signed_client.get(GROWTH).json()
    signed_client.put("/api/prof/visibility", json={"mode": "visible"})
    visible = signed_client.get(GROWTH).json()

    assert hidden["periods"] == visible["periods"]


def test_growth_event_cannot_be_edited(signed_client):
    """§7: тот же запрет на правку, что у журнала споров модуля 7."""
    setup_candidate(signed_client)
    signed_client.get(GROWTH)

    with SessionLocal() as db:
        item = db.query(ProfileGrowthEvent).first()
        item.description_ru = "переписал историю"
        with pytest.raises((AppendOnlyViolation, StatementError)):
            db.commit()


def test_growth_event_cannot_be_deleted(signed_client):
    setup_candidate(signed_client)
    signed_client.get(GROWTH)

    with SessionLocal() as db:
        item = db.query(ProfileGrowthEvent).first()
        db.delete(item)
        with pytest.raises((AppendOnlyViolation, StatementError)):
            db.commit()


def test_growth_log_is_not_the_dispute_log(signed_client):
    """§4.2: два журнала с разными читателями не сливаются в один."""
    from app.routers import growth as growth_router

    source = inspect.getsource(growth_router)
    assert "DisputeHistoryEntry" not in source


# --- устаревание ----------------------------------------------------------


def test_decay_never_touches_the_confirmed_status_itself(signed_client):
    """§0: подтверждённое остаётся подтверждённым навсегда."""
    setup_candidate(signed_client)
    strengthen(signed_client, statement_ids(signed_client))
    signed_client.get(GROWTH)

    before = {
        c["competency_id"]: c["status"]
        for c in signed_client.get(PROF).json()["snapshots"][0]["components"]
    }

    backdate_freshness(days=90)

    after = {
        c["competency_id"]: c["status"]
        for c in signed_client.get(PROF).json()["snapshots"][0]["components"]
    }
    assert after == before


def test_time_alone_lowers_neither_prof_nor_trust(signed_client):
    """Давность подтверждения больше не понижает ничего.

    Раньше этот тест проверял обратное: множитель актуальности уменьшал вклад
    компетенции в PROF.индекс. Гипотеза снята в стабилизационном спринте -
    прошедшие тридцать дней не делают доказательство менее доказательством, а
    балл, падающий за паузу, это наказание, а не измерение опыта.

    Сам признак давности остался и показывается кандидату как повод вернуться;
    проверяется здесь же, что он не исчез вместе с понижением.
    """
    setup_candidate(signed_client)
    strengthen(signed_client, statement_ids(signed_client))
    signed_client.get(GROWTH)

    prof_before = signed_client.get(PROF).json()["snapshots"][0]["overall_score"]
    trust_before = signed_client.get(TRUST).json()

    with SessionLocal() as db:
        assert db.query(CompetencyFreshness).all(), "нужна подтверждённая компетенция"

    backdate_freshness(days=90)

    prof_after = signed_client.get(PROF).json()["snapshots"][0]["overall_score"]
    trust_after = signed_client.get(TRUST).json()

    assert prof_after == prof_before
    assert trust_after["overall_score"] == trust_before["overall_score"]
    assert trust_after["components"] == trust_before["components"]

    # Признак давности при этом виден - убрано только влияние на балл.
    freshness = signed_client.get(GROWTH).json()["freshness"]
    assert any(item["status"] == growth.STALE for item in freshness)


def test_trust_never_reads_the_freshness_multiplier():
    """Проверка кодом: связать устаревание с Trust слишком легко случайно."""
    from app import trust as trust_logic
    from app.routers import trust as trust_router

    for module in (trust_logic, trust_router):
        source = inspect.getsource(module)
        assert "market_weight_multiplier" not in source
        assert "CompetencyFreshness" not in source
        assert "freshness" not in source.lower()


def test_refresh_updates_the_date_and_nothing_else(signed_client):
    """FR5.3 в новом прочтении: кнопка не создаёт доказательств и не двигает балл.

    Раньше «Актуализировать» возвращало полный вес компетенции. Это означало,
    что балл двигается от нажатия кнопки, за которым не стоит ничего нового, -
    и вместе с понижением за давность механика снята. Кнопка осталась отметкой
    «я это ещё делаю», меняющей только дату.
    """
    setup_candidate(signed_client)
    strengthen(signed_client, statement_ids(signed_client))
    signed_client.get(GROWTH)

    backdate_freshness(days=90)

    stale = signed_client.get(GROWTH).json()["freshness"]
    assert stale and stale[0]["status"] == growth.STALE
    competency_id = stale[0]["competency_id"]
    evidence_before = len(signed_client.get(PROFILE).json()["evidence"])
    prof_before = signed_client.get(PROF).json()["snapshots"][0]["overall_score"]

    payload = signed_client.post(f"{GROWTH}/freshness/{competency_id}/refresh").json()

    refreshed = next(
        item for item in payload["freshness"] if item["competency_id"] == competency_id
    )
    assert refreshed["status"] == growth.FRESH
    # Доказательств не прибавилось: нажатие кнопки ничего не доказывает.
    assert len(signed_client.get(PROFILE).json()["evidence"]) == evidence_before
    # И балл не сдвинулся - ни вниз до этого, ни вверх сейчас.
    assert signed_client.get(PROF).json()["snapshots"][0]["overall_score"] == prof_before


def test_refresh_of_an_unknown_competency_is_not_found(signed_client):
    setup_candidate(signed_client)
    signed_client.get(GROWTH)
    assert signed_client.post(f"{GROWTH}/freshness/made_up/refresh").status_code == 404


# --- поводы вернуться -----------------------------------------------------


def test_module_8_builds_exactly_two_trigger_types():
    """FR5.1: «подходящая вакансия» и «интерес рекрутера» - не этот модуль.

    Позже их достроили модули 11 и 13, когда появилось чем их порождать, и в
    общем реестре они есть. Но производителей у модуля 8 по-прежнему два: это
    его собственная граница, и стирать её не за чем.
    """
    assert growth.OWN_TRIGGER_TYPES == (growth.WHITE_SPOT_REMINDER, growth.DECAY_WARNING)

    from app.routers import growth as growth_router

    source = inspect.getsource(growth_router)
    assert "new_matching_vacancy" not in source
    assert "recruiter_interest" not in source


def test_white_spot_reminder_uses_the_established_wording(signed_client):
    setup_candidate(signed_client)
    backdate_role(days=5)

    payload = signed_client.get(GROWTH).json()
    reminders = [
        item for item in payload["triggers"] if item["trigger_type"] == growth.WHITE_SPOT_REMINDER
    ]
    assert reminders
    assert reminders[0]["text_ru"] == growth.WHITE_SPOT_TEXT_RU


def test_showing_a_reminder_is_never_counted_as_success(signed_client):
    """FR5.4: значимо только `acted_upon`, показ успехом не считается."""
    setup_candidate(signed_client)
    backdate_role(days=5)

    payload = signed_client.get(GROWTH).json()
    assert payload["stats"]["triggers_sent"] >= 1
    assert payload["stats"]["triggers_acted_upon"] == 0
    assert payload["stats"]["acted_upon_ratio"] == 0.0


def test_closing_the_white_spot_marks_the_trigger_acted_upon(signed_client):
    setup_candidate(signed_client)
    backdate_role(days=5)

    payload = signed_client.get(GROWTH).json()
    reminder = next(
        item for item in payload["triggers"] if item["trigger_type"] == growth.WHITE_SPOT_REMINDER
    )
    competency_id = reminder["related_ref"]

    with SessionLocal() as db:
        user = user_row(db)
        trigger = (
            db.query(ReturnTrigger)
            .filter_by(user_id=user.id, related_ref=competency_id)
            .first()
        )
        assert trigger.status == growth.SENT

    # Закрываем белое пятно так, как это делает сам кандидат.
    parsed = signed_client.post(PARSE, json={"raw_text": MORE_TEXT}).json()
    signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]}
    )
    strengthen(signed_client, statement_ids(signed_client), "https://gitlab.com/dev/ci")
    signed_client.get(GROWTH)

    with SessionLocal() as db:
        user = user_row(db)
        closed = [
            item
            for item in db.query(ReturnTrigger).filter_by(user_id=user.id).all()
            if item.status == growth.ACTED_UPON
        ]
        assert closed, "закрытое белое пятно должно закрыть и напоминание"
        assert all(item.acted_upon_at is not None for item in closed)


def test_dismissing_a_reminder_is_not_an_action(signed_client):
    setup_candidate(signed_client)
    backdate_role(days=5)
    payload = signed_client.get(GROWTH).json()
    trigger_id = payload["triggers"][0]["id"]

    after = signed_client.post(f"{GROWTH}/triggers/{trigger_id}/dismiss").json()

    assert all(item["id"] != trigger_id for item in after["triggers"])
    assert after["stats"]["triggers_acted_upon"] == 0


def test_decay_warning_promises_no_penalty(signed_client):
    """Напоминание не должно обещать наказание, которого не будет."""
    setup_candidate(signed_client)
    strengthen(signed_client, statement_ids(signed_client))
    signed_client.get(GROWTH)

    backdate_freshness(days=10)

    payload = signed_client.get(GROWTH).json()
    warnings = [
        item for item in payload["triggers"] if item["trigger_type"] == growth.DECAY_WARNING
    ]
    assert warnings
    assert "не влияет" in warnings[0]["text_ru"].lower()
    for forbidden in ("понизим", "снизим", "потеряете"):
        assert forbidden not in warnings[0]["text_ru"].lower()


# --- чистые функции устаревания ------------------------------------------


def test_freshness_thresholds_are_named_constants():
    """Пороги давности остались, а понижающего множителя больше нет.

    Раньше здесь проверялось, что множитель падает со временем. Теперь
    проверяется обратное: статус давности различается, а вес - нет. Модель
    актуальности сохранена под будущую калибровку, но балл она не трогает.
    """
    now = datetime.now(timezone.utc)

    fresh = growth.freshness_for("x", now)
    decaying = growth.freshness_for("x", now - timedelta(days=growth.DECAY_COUNTDOWN_DAYS))
    stale = growth.freshness_for("x", now - timedelta(days=growth.STALE_AFTER_DAYS))

    assert fresh.status == growth.FRESH
    assert decaying.status == growth.DECAYING
    assert stale.status == growth.STALE

    assert {fresh.multiplier, decaying.multiplier, stale.multiplier} == {1.0}


def test_multiplier_is_neutral_in_this_phase():
    """Понижения нет вообще: все три значения - единица.

    Словарь оставлен под будущую модель актуальности, поэтому тест следит
    именно за тем, чтобы понижение не вернулось тихой правкой одного числа.
    """
    assert set(growth.MULTIPLIER.values()) == {1.0}


def test_decay_copy_no_longer_threatens_a_penalty():
    """Осознанное отступление от формулировки мастер-документа.

    Исходный текст обещал: «через 3 дня мы понизим вес компетенции». Понижения
    в продукте больше нет, и оставить обещание наказания, которого не будет, -
    хуже, чем отступить от исходной формулировки. Расхождение отмечено в README.
    """
    text = growth.DECAY_TEXT_TEMPLATE_RU.format(name="Проектирование REST API")

    assert "понизим" not in text
    assert "на балл это не влияет" in text.lower()
