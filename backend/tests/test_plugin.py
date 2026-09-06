"""Проверки модуля 15: плагин рекрутера.

Здесь важнее всего не функциональность, а границы:

* со страницы ничего не читается само;
* текст резюме не уходит на сервер вообще;
* до «Найти в базе» на сервер не уходит ничего, а с ним — только хеш;
* приглашение никуда не отправляется само.
"""

import hashlib
import inspect
from pathlib import Path

from app import candidates as pool, requirements
from app.db import SessionLocal
from app.models import VerificationInvite
from app.routers import plugin as router
from app.vacancies import MANDATORY, NICE_TO_HAVE

PLUGIN = "/api/plugin"
WEB = Path(__file__).resolve().parents[2] / "web" / "src"

VACANCY_TEXT = (
    "Backend-разработчик в команду платежей. Обязательно: Python, PostgreSQL, "
    "проектирование REST API. Будет плюсом опыт с Kubernetes и ClickHouse."
)

RESUME_TEXT = (
    "Иван Петров\n"
    "Коммуникабельный и стрессоустойчивый специалист, нацелен на результат. "
    "Ответственный, обучаемый, системный подход к работе в команде и высокая мотивация "
    "позволяют мне эффективно решать задачи в динамично развивающейся компании любого "
    "профиля и масштаба, что подтверждается опытом работы.\n"
    "2018-2024 — разработчик. 2020-2023 — ведущий разработчик. Опыт 12 лет."
)


def hashed(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


# --- граница «ничего не читается само» -------------------------------------


def test_text_enters_only_through_manual_selection():
    """FR1.1: со страницы плагин не читает ничего.

    Проверяется отсутствием средств: ни обхода DOM страницы, ни наблюдателя за
    изменениями — только явное чтение того, что выделил человек.
    """
    source = (WEB / "plugin.js").read_text(encoding="utf-8")

    assert "window.getSelection" in source
    for forbidden in ("MutationObserver", "document.querySelectorAll('body", "innerText"):
        assert forbidden not in source


def test_resume_analysis_has_no_way_to_reach_the_network():
    """FR1.2: архитектурная граница, а не договорённость.

    У файла экспресс-разбора просто нет доступа к сети — ни импорта клиента,
    ни fetch. Соблазн «отправить на сервер, там разбор лучше» слишком велик,
    чтобы держать это на честном слове.
    """
    source = (WEB / "express.js").read_text(encoding="utf-8")

    for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "from './api.js'"):
        assert forbidden not in source, forbidden


def test_no_endpoint_accepts_resume_text():
    """Обратная сторона: на сервере некуда прислать текст резюме."""
    source = inspect.getsource(router)

    assert "content_type" not in source
    # Единственный текстовый вход — вакансия, и он назван прямо.
    assert source.count("raw_text") == 1
    assert "def extract_vacancy" in source


# --- US1: экспресс-разбор в браузере ---------------------------------------


def test_express_analysis_is_labelled_as_a_rough_estimate():
    """FR1.4: это не та же уверенность, что у настоящей Самостоятельности."""
    source = (WEB / "plugin.js").read_text(encoding="utf-8")

    assert "грубая прикидка" in source
    assert "контрольного образца" in source


def test_express_thresholds_are_named_constants():
    source = (WEB / "express.js").read_text(encoding="utf-8")

    for name in ("LONG_SENTENCE_WORDS", "LOW_VARIETY_RATIO", "LOW_FACT_DENSITY"):
        assert f"export const {name}" in source
    assert "неоткалиброванные величины" in source


# --- US2: требования вакансии ----------------------------------------------


def test_vacancy_extraction_reuses_the_taxonomy(recruiter_client):
    """FR2.1: разбор идёт по образцам модуля 2, а не по второму набору правил."""
    source = inspect.getsource(requirements)
    assert "from app.taxonomy import" in source
    assert "competency.regexes" in source

    payload = recruiter_client.post(f"{PLUGIN}/vacancy", json={"raw_text": VACANCY_TEXT}).json()
    labels = [item["label_ru"] for item in payload["requirements"]]

    assert "Python" in labels
    assert "PostgreSQL" in labels


def test_criticality_follows_the_nearest_sentence():
    """Маркер из соседнего предложения не должен понижать требование."""
    items = {item.label_ru: item for item in requirements.extract(VACANCY_TEXT)}

    assert items["Python"].criticality == MANDATORY
    assert items["Проектирование REST API"].criticality == MANDATORY
    assert items["Kubernetes"].criticality == NICE_TO_HAVE


def test_requirements_outside_the_library_are_named_not_dropped():
    """Требование вне эталонов — факт про вакансию, а не пробел разбора."""
    items = requirements.extract(VACANCY_TEXT)
    unknown = {item.label_ru for item in requirements.unknown_requirements(items)}

    assert "ClickHouse" in unknown


def test_every_requirement_carries_an_evidence_hint(recruiter_client):
    """FR2.2: подсказка, чем это подтверждается, — у каждого пункта."""
    payload = recruiter_client.post(f"{PLUGIN}/vacancy", json={"raw_text": VACANCY_TEXT}).json()

    assert payload["requirements"]
    for item in payload["requirements"]:
        assert len(item["evidence_hint_ru"]) > 15
        assert item["matched_text"]


def test_extraction_never_generates_a_live_question():
    """FR2.2: подсказка — не вопрос. Живой вопрос задаёт модуль 4."""
    for module in (requirements, router):
        source = inspect.getsource(module)
        assert "ProbeQuestion" not in source
        assert "generate_question" not in source


def test_mandatory_requirements_come_first(recruiter_client):
    """FR2.3: тот же приоритет, что у белых пятен и рекомендаций."""
    payload = recruiter_client.post(f"{PLUGIN}/vacancy", json={"raw_text": VACANCY_TEXT}).json()
    order = [item["criticality"] for item in payload["requirements"]]

    assert order == sorted(order, key=lambda value: 0 if value == MANDATORY else 1)


def test_empty_vacancy_text_says_why(recruiter_client):
    assert recruiter_client.post(f"{PLUGIN}/vacancy", json={"raw_text": "  "}).status_code == 400


# --- US4: «Найти в базе» и светофор ----------------------------------------


def test_lookup_accepts_only_a_hash(recruiter_client):
    """FR-Priv.2: на сервер уходит хеш, а не контакт."""
    refused = recruiter_client.post(f"{PLUGIN}/lookup", json={"contact_hash": "ivan@example.com"})
    assert refused.status_code == 422


def test_registered_candidate_gets_the_green_tier(recruiter_client):
    candidate = pool.visible_pool()[0]
    payload = recruiter_client.post(
        f"{PLUGIN}/lookup", json={"contact_hash": hashed(candidate.display_name)}
    ).json()

    assert payload["result"] == "registered_verified"
    assert payload["candidate_id"] == candidate.id
    assert payload["tier_label_ru"] == "Верифицирован"


def test_unknown_person_gets_the_grey_tier_and_no_number(recruiter_client):
    payload = recruiter_client.post(
        f"{PLUGIN}/lookup", json={"contact_hash": hashed("никого-с-таким-именем-нет")}
    ).json()

    assert payload["result"] == "not_registered"
    assert payload["candidate_id"] is None
    assert payload["tier_label_ru"] == "Требует верификации"
    assert payload["tier_note_ru"] == "Кандидат не зарегистрирован"


def test_lookup_leaves_no_trace(recruiter_client):
    """FR-Priv.3: «искали этого человека» — уже персональные данные."""
    source = inspect.getsource(router)
    lookup_body = source[source.index("def lookup") : source.index("def create_invite")]

    assert "db.add(" not in lookup_body
    assert "db.commit(" not in lookup_body


def test_three_tiers_use_the_agreed_wording(recruiter_client):
    payload = recruiter_client.get(PLUGIN).json()
    labels = {item["tier"]: item["label_ru"] for item in payload["tiers"]}

    assert labels == {
        "verified": "Верифицирован",
        "preliminary": "Предварительный",
        "needs_verification": "Требует верификации",
    }
    assert payload["honesty_ru"] == (
        "Мы не обманываем рекрутера. Мы даем честную оценку с указанием степени достоверности."
    )
    assert "не «шпион»" in payload["lens_ru"]


def test_verified_tier_reuses_module_12_rendering(recruiter_client):
    """FR4.3: свой показ PROF и Trust плагин не строит — он ведёт в модуль 12."""
    source = inspect.getsource(router)

    assert "trust_components" not in source
    assert "prof_components" not in source


def test_progressive_reveal_is_not_applied_here():
    """FR4.4: этапность здесь бессмысленна — рекрутер уже смотрит на имя.

    Это осознанное решение, а не забытая интеграция.
    """
    for source in (
        inspect.getsource(router),
        (WEB / "plugin.js").read_text(encoding="utf-8"),
    ):
        assert "RevealState" not in source
        assert "stage1_professional" not in source


# --- US3: приглашение ------------------------------------------------------


def test_invite_is_generated_but_never_sent(recruiter_client):
    """FR3.2: то же правило, что у экспорта в модуле 9, только с другой стороны."""
    response = recruiter_client.post(f"{PLUGIN}/invites", json={"note_ru": None})
    assert response.status_code == 201

    payload = response.json()
    assert payload["invite_link"].startswith("/?invite=")
    assert "отправьте сами" in payload["send_note_ru"]

    source = inspect.getsource(router).lower()
    for forbidden in ("smtp", "sendmail", "email.mime", "requests.post", "httpx"):
        assert forbidden not in source


def test_invite_model_has_no_recipient_or_delivery_field():
    fields = set(VerificationInvite.__table__.columns.keys())
    for forbidden in ("sent_to", "recipient", "delivery_status", "channel", "opened_at"):
        assert forbidden not in fields


def test_invite_is_recorded_for_the_recruiter_only(recruiter_client):
    recruiter_client.post(f"{PLUGIN}/invites", json={"note_ru": "по вакансии платежей"})

    with SessionLocal() as db:
        rows = db.query(VerificationInvite).all()
        assert len(rows) == 1
        assert rows[0].status == "generated"
        assert rows[0].token


def test_invited_candidate_goes_through_the_normal_path():
    """FR3.3: приглашение — новая дверь, а не короткий путь верификации."""
    source = inspect.getsource(router)

    assert "Statement(" not in source
    assert "Evidence(" not in source
