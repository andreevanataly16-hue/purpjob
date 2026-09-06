"""Проверки модуля 9: экспорт профиля.

Главное здесь - не «PDF собрался», а два обещания:

* платформа никуда ничего не отправляет и не может узнать, кто открыл файл;
* из документа не утекает то, что подтверждалось под NDA.
"""

import inspect

from app.db import SessionLocal
from app.models import ExportRequest
from app.resume import (
    KEY_PROJECTS_SHOWN,
    SKILLS_SHOWN,
    pick_projects,
    pick_skills,
    register_font,
)
from app.routers import export as export_router
from app.routers.trust import LEGEND_RU

PREVIEW = "/api/export/preview"
PDF = "/api/export/pdf"
PROF = "/api/prof"
ROLES = "/api/prof/roles"
PARSE = "/api/profile/parse"
ACCEPT = "/api/profile/statements/accept"
LINK = "/api/profile/evidence/link"
PROFILE = "/api/profile"
VISIBILITY = "/api/prof/visibility"

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


# --- US1: обычный, переносимый формат ------------------------------------


def test_only_one_format_exists(signed_client):
    """§0/§2.1: один формат, один вариант длины - и никакого выбора-мастера."""
    assert export_router.FORMATS == ("pdf",)

    setup_candidate(signed_client)
    refused = signed_client.post(PDF, json={"format": "docx", "include_contacts": True})
    assert refused.status_code == 400


def test_export_is_a_real_pdf(signed_client):
    setup_candidate(signed_client)
    response = signed_client.post(PDF, json={"format": "pdf", "include_contacts": True})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert response.content.rstrip().endswith(b"%%EOF")
    assert len(response.content) > 1000


def test_export_needs_no_platform_to_read(signed_client):
    """FR1.3: в файле нет ничего, что требовало бы вернуться в PurpJob."""
    setup_candidate(signed_client)
    content = signed_client.post(PDF, json={"format": "pdf"}).content

    assert b"localhost" not in content
    assert b"/api/" not in content


def test_export_without_a_role_says_why(signed_client):
    assert signed_client.get(PREVIEW).status_code == 409


# --- US2: собирается само -------------------------------------------------


def test_no_manual_text_entry_anywhere_in_this_module():
    """FR2.1/FR2.4: здесь нельзя ни написать, ни переписать текст резюме."""
    source = inspect.getsource(export_router)

    assert "text" not in source.lower().split("ExportOptionsIn")[-1].split("def ")[0]
    from app.schemas_export import ExportOptionsIn

    assert set(ExportOptionsIn.model_fields) == {"format", "include_contacts"}


def test_selection_rules_are_bounded_and_named():
    """FR2.2: «несколько ключевых проектов» - это конкретное число."""
    assert KEY_PROJECTS_SHOWN == 3
    assert SKILLS_SHOWN == 10


def test_skills_are_ordered_by_reference_weight(signed_client):
    setup_candidate(signed_client)
    snapshot = signed_client.get(PROF).json()["snapshots"][0]

    class Component:
        def __init__(self, data):
            self.name_ru = data["name_ru"]
            self.status = data["status"]
            self.weight = data["weight"]

    picked = pick_skills([Component(c) for c in snapshot["components"]])
    by_name = {c["name_ru"]: c["weight"] for c in snapshot["components"]}
    weights = [by_name[name] for name, _ in picked]

    assert weights == sorted(weights, reverse=True)
    assert len(picked) <= SKILLS_SHOWN


def test_unconfirmed_competencies_are_not_advertised(signed_client):
    """Резюме - про подтверждённый опыт. Белые пятна - дело кандидата."""
    setup_candidate(signed_client)
    payload = signed_client.get(PREVIEW).json()

    assert payload["skills"]
    assert all(item["status_ru"] for item in payload["skills"])
    assert all("не подтвержд" not in item["status_ru"] for item in payload["skills"])


def test_re_export_reflects_the_live_profile(signed_client):
    """FR2.3: никаких замороженных копий - каждый файл собирается заново."""
    setup_candidate(signed_client)
    before = signed_client.get(PREVIEW).json()

    parsed = signed_client.post(
        PARSE, json={"raw_text": "Настроил CI/CD в GitLab и мониторинг на Prometheus."}
    ).json()
    signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]}
    )
    ids = [item["id"] for item in signed_client.get(PROFILE).json()["statements"]]
    signed_client.post(LINK, json={"url": "https://gitlab.com/dev/ci", "statement_ids": ids})

    after = signed_client.get(PREVIEW).json()
    assert after["prof_score"] > before["prof_score"]
    assert len(after["skills"]) >= len(before["skills"])


def test_module_stores_no_generated_files():
    """Готовых документов модуль не хранит - только собирает по запросу."""
    source = inspect.getsource(export_router)
    assert "open(" not in source
    assert "write" not in source


# --- US3: Trust Score с легендой -----------------------------------------


def test_trust_legend_travels_with_the_number(signed_client):
    """FR3.1: число без объяснения не выпускается наружу."""
    setup_candidate(signed_client)
    payload = signed_client.get(PREVIEW).json()

    assert isinstance(payload["trust_score"], int)
    assert payload["trust_legend_ru"] == LEGEND_RU


def test_legend_is_the_same_for_everyone_and_not_generated(signed_client):
    """FR3.2: абзац фиксированный, а не собранный под кандидата."""
    setup_candidate(signed_client)
    first = signed_client.get(PREVIEW).json()["trust_legend_ru"]

    parsed = signed_client.post(PARSE, json={"raw_text": "Пишу тесты на pytest."}).json()
    signed_client.post(
        ACCEPT, json={"raw_input_id": parsed["raw_input_id"], "items": parsed["items"]}
    )
    second = signed_client.get(PREVIEW).json()["trust_legend_ru"]

    assert first == second == LEGEND_RU


def test_legend_keeps_the_positioning_constraint():
    """FR3.3: «не заменяет интервью» не должно исчезнуть при сокращении."""
    assert "Не заменяет интервью" in LEGEND_RU
    assert "независимыми источниками" in LEGEND_RU


# --- US4: платформа ничего не рассылает ----------------------------------


def test_nothing_in_this_module_can_send_anywhere():
    """FR4.1: не «пока не сделали», а нечем."""
    from app import resume

    for module in (export_router, resume):
        source = inspect.getsource(module).lower()
        for forbidden in ("smtp", "sendmail", "email.mime", "requests.post", "httpx", "upload"):
            assert forbidden not in source, forbidden


def test_data_model_has_no_recipient_or_delivery_field():
    """§4.1: поля получателя нет - и появиться оно не должно даже про запас."""
    from app.models import ExportRequest as Model

    fields = set(Model.__table__.columns.keys())
    for forbidden in ("sent_to", "recipient", "delivery_status", "opened_at", "tracking_id"):
        assert forbidden not in fields


def test_pdf_carries_no_tracking(signed_client):
    """FR4.3: ни уникальных ссылок, ни счётчиков, ни следов сеанса."""
    setup_candidate(signed_client)
    content = signed_client.post(PDF, json={"format": "pdf", "include_contacts": False}).content

    assert b"http://" not in content
    assert b"https://" not in content


def test_contacts_are_independent_from_platform_visibility(signed_client):
    """FR4.4: два переключателя не связаны ни в одну, ни в другую сторону."""
    setup_candidate(signed_client)

    signed_client.put(VISIBILITY, json={"mode": "hidden"})
    with_contacts = signed_client.get(PREVIEW, params={"include_contacts": True}).json()
    assert with_contacts["contact_email"]

    signed_client.put(VISIBILITY, json={"mode": "visible"})
    without = signed_client.get(PREVIEW, params={"include_contacts": False}).json()
    assert without["contact_email"] is None

    # И обратно: экспорт не трогает режим видимости.
    signed_client.post(PDF, json={"format": "pdf", "include_contacts": False})
    assert signed_client.get(PROF).json()["visibility"]["mode"] == "visible"


def test_export_is_recorded_only_for_the_candidate(signed_client):
    setup_candidate(signed_client)
    signed_client.post(PDF, json={"format": "pdf", "include_contacts": True})

    with SessionLocal() as db:
        rows = db.query(ExportRequest).all()
        assert len(rows) == 1
        assert rows[0].format == "pdf"
        assert rows[0].include_contacts is True


# --- NDA не утекает -------------------------------------------------------


def test_nda_confirmations_never_reach_the_document(signed_client):
    """Подтверждение под NDA доказывает опыт, но не разрешает его пересказывать.

    Без этого экспорт стал бы дырой в обещании модуля 5.
    """
    setup_candidate(signed_client)

    class Evidence:
        def __init__(self, type_, text, nda=False):
            self.type = type_
            self.raw_text = text
            self.nda = nda
            self.status = "confirmed"

    class Statement:
        id = 1
        skill_name_ru = "Высокие нагрузки"
        evidence = [
            Evidence("blind_witness_answer", "СЕКРЕТ: клиент — банк «Пример»"),
            Evidence("mirror_task_solution", "СЕКРЕТ: схема их платёжного шлюза"),
            Evidence("free_text", "Закрытый проект", nda=True),
        ]

    picked = pick_projects([Statement()], {"1": "strong"})
    assert picked == []


def test_probe_transcripts_never_reach_the_document(signed_client):
    """В резюме идут слова кандидата, а не наш с ним разговор.

    Ответ на вопрос Contextual Probe хранится вместе с уточняющим вопросом
    системы - в резюме это выглядело бы так, будто кандидат сам себя
    переспрашивает.
    """

    class Evidence:
        def __init__(self, type_, text):
            self.type = type_
            self.raw_text = text
            self.nda = False
            self.status = "confirmed"

    class Statement:
        id = 1
        skill_name_ru = "Проектирование REST API"
        evidence = [
            Evidence(
                "probe_answer",
                "Всё было нормально. За счёт чего именно это получилось: какой инструмент?",
            )
        ]

    assert pick_projects([Statement()], {"1": "strong"}) == []


def test_open_text_still_reaches_the_document(signed_client):
    """Обратная проверка: обычный рассказ кандидата в документ попадает."""
    setup_candidate(signed_client)
    payload = signed_client.get(PREVIEW).json()

    assert payload["projects"]
    texts = [item["text"] for item in payload["projects"]]

    # Слова кандидата, а не пересказ системы.
    assert any("rps" in text.lower() or "биллинг" in text.lower() for text in texts)
    # И каждый пункт про своё: повторять один и тот же абзац трижды незачем.
    assert len(set(texts)) == len(texts)


# --- шрифт ----------------------------------------------------------------


def test_font_state_is_reported_before_the_button_is_pressed(signed_client):
    """Кириллице в PDF нужен встроенный шрифт - об этом говорят заранее."""
    setup_candidate(signed_client)
    payload = signed_client.get(PREVIEW).json()

    assert isinstance(payload["font_available"], bool)
    assert "DejaVuSans.ttf" in payload["font_hint_ru"]


def test_cyrillic_is_embedded_when_a_font_exists(signed_client):
    """Если шрифт есть, кириллица должна быть настоящей, а не квадратами."""
    if not register_font():
        import pytest

        pytest.skip("на этой машине нет шрифта с кириллицей")

    setup_candidate(signed_client)
    content = signed_client.post(PDF, json={"format": "pdf"}).content

    # Встроенный TrueType-шрифт - признак того, что текст не свёлся к латинице.
    assert b"/TrueType" in content or b"/Type0" in content
    assert b"/FontFile2" in content


# --- что на самом деле оказалось в файле ---------------------------------


def _pdf_text(content: bytes) -> str:
    """Читает готовый PDF так же, как его прочитает получатель."""
    import io

    import pytest

    pypdf = pytest.importorskip("pypdf", reason="pypdf нужен только для этой проверки")
    reader = pypdf.PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() for page in reader.pages)


def _flat(content: bytes) -> str:
    """То же, но одной строкой: в файле абзацы разбиты по ширине страницы."""
    return " ".join(_pdf_text(content).split())


def test_cyrillic_survives_to_the_finished_file(signed_client):
    """Проверка не «шрифт зарегистрировался», а «текст читается».

    Кириллица в PDF ломается тихо: файл собирается, открывается и показывает
    квадраты. Единственный честный способ убедиться - прочитать готовый файл.
    """
    if not register_font():
        import pytest

        pytest.skip("на этой машине нет шрифта с кириллицей")

    setup_candidate(signed_client)
    text = _pdf_text(signed_client.post(PDF, json={"format": "pdf"}).content)

    assert "PROF.индекс" in text
    assert "Компетенции" in text
    # Легенда переносится по ширине страницы, поэтому сверяем её по плоскому
    # тексту: разрыв строки внутри абзаца - это вёрстка, а не пропажа абзаца.
    assert "Не заменяет интервью" in " ".join(text.split())


def test_finished_file_contains_no_nda_material(signed_client):
    """Утечка должна проверяться на самом документе, а не только на отборе."""
    if not register_font():
        import pytest

        pytest.skip("на этой машине нет шрифта с кириллицей")

    setup_candidate(signed_client)
    text = _pdf_text(signed_client.post(PDF, json={"format": "pdf"}).content)

    # Ни одной формулировки, которая появляется только в механиках модуля 5.
    for forbidden in ("слепого свидетеля", "зеркальн", "под nda"):
        assert forbidden not in text.lower()


def test_contacts_are_absent_from_the_file_when_excluded(signed_client):
    if not register_font():
        import pytest

        pytest.skip("на этой машине нет шрифта с кириллицей")

    setup_candidate(signed_client)
    text = _pdf_text(
        signed_client.post(PDF, json={"format": "pdf", "include_contacts": False}).content
    )

    assert "Контакты" not in text
    assert "@" not in text


def test_build_pdf_does_not_depend_on_call_order():
    """Сборка документа сама заботится о шрифте.

    Иначе первый вызов из нового места падает на внутренностях reportlab
    вместо понятного сообщения - а это ровно то, что случилось при ручной
    проверке.
    """
    import reportlab.pdfbase.pdfmetrics as pdfmetrics

    from app.resume import FONT_NAME, ResumeData, build_pdf, find_font
    from datetime import datetime, timezone

    if find_font() is None:
        import pytest

        pytest.skip("на этой машине нет шрифта с кириллицей")

    # Убираем регистрацию, как будто процесс только что стартовал.
    pdfmetrics._fonts.pop(FONT_NAME, None)
    pdfmetrics._typefaces.pop(FONT_NAME, None)

    data = ResumeData(
        role_ru="Middle — Backend",
        segment_ru="Профиль",
        prof_score=10,
        trust_score=20,
        trust_measured=True,
        trust_legend_ru="Легенда",
        skills=[],
        projects=[],
        contact_email=None,
        generated_at=datetime.now(timezone.utc),
    )
    assert build_pdf(data).startswith(b"%PDF-")
