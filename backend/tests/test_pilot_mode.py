"""Режим регистрации закрытого пилота.

Почта в продукте не подтверждается. Само по себе это не дефект - дефектом это
становится при открытой регистрации: тогда любой заводит профиль на чужой
адрес, а выглядит всё так, будто адрес проверен. Закрытый пилот убирает именно
это: код приглашения не доказывает, что адрес твой, но и продукт больше
ничего такого не утверждает.

Здесь проверяется граница, а не сам код: что закрытый режим действительно
закрывает, что пустая настройка не означает «пускать всех», и что подобрать
код нельзя перебором.
"""

import pytest

from app.config import settings
from app.ratelimit import login_limiter
from app.routers.auth import (
    BAD_INVITE_RU,
    REGISTRATION_CLOSED_RU,
    UNVERIFIED_EMAIL_RU,
)

REGISTER = "/api/auth/register"
LOGIN = "/api/auth/login"

CODE = "пилот-2026-осень"


@pytest.fixture
def invite_only(monkeypatch):
    """Рабочий режим поставки: приглашение обязательно."""
    monkeypatch.setattr(settings, "registration_mode", "invite")
    monkeypatch.setattr(settings, "pilot_invite_code", CODE)


def register(client, code=None, email="newcomer@example.com"):
    body = {"email": email, "password": "verysecret123"}
    if code is not None:
        body["invite_code"] = code
    return client.post(REGISTER, json=body)


# --- закрытый режим -------------------------------------------------------


def test_registration_without_an_invite_is_refused(client, invite_only):
    response = register(client)

    assert response.status_code == 403
    assert response.json()["detail"] == BAD_INVITE_RU


def test_a_wrong_invite_is_refused(client, invite_only):
    assert register(client, code="не тот код").status_code == 403


def test_the_right_invite_creates_the_profile(client, invite_only):
    response = register(client, code=CODE)

    assert response.status_code == 201
    assert response.json()["email"] == "newcomer@example.com"


def test_an_empty_configured_code_closes_registration_rather_than_opening_it(
    client, monkeypatch
):
    """Ненастроенный пилот не должен молча оказаться открытым для всех.

    Это самая дорогая ошибка в этом месте: свежая поставка без .env выглядела
    бы работающей, а на деле пускала бы кого угодно.
    """
    monkeypatch.setattr(settings, "registration_mode", "invite")
    monkeypatch.setattr(settings, "pilot_invite_code", "")

    response = register(client)
    assert response.status_code == 503
    assert response.json()["detail"] == REGISTRATION_CLOSED_RU

    # И код тут не поможет: настройки просто нет.
    assert register(client, code="хоть какой-нибудь").status_code == 503


def test_the_shipped_default_is_the_closed_mode():
    """Значение по умолчанию - закрытый режим.

    Открытый режим существует для локальной разработки; если бы по умолчанию
    стоял он, забытая настройка означала бы публичную регистрацию.
    """
    from app.config import Settings

    assert Settings.model_fields["registration_mode"].default == "invite"
    assert Settings.model_fields["pilot_invite_code"].default == ""


# --- подбор кода ----------------------------------------------------------


def test_the_invite_code_cannot_be_brute_forced(client, invite_only):
    """Код общий на весь пилот, значит подбираемый - и он под тем же лимитом,
    что и пароль."""
    for _ in range(login_limiter.max_attempts):
        assert register(client, code="мимо").status_code == 403

    refused = register(client, code="мимо")
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) > 0


def test_the_invite_limit_does_not_lock_out_the_login_form(client, credentials, invite_only):
    """Ведро приглашений отдельное: перебор кода не должен закрывать вход
    человеку, у которого профиль уже есть."""
    client.post(REGISTER, json={**credentials, "invite_code": CODE})
    for _ in range(login_limiter.max_attempts + 1):
        register(client, code="мимо")

    assert client.post(LOGIN, json=credentials).status_code == 200


# --- открытый режим -------------------------------------------------------


def test_open_mode_ignores_the_invite_entirely(client, monkeypatch):
    """Локальная разработка: кода нет и он не нужен."""
    monkeypatch.setattr(settings, "registration_mode", "open")
    monkeypatch.setattr(settings, "pilot_invite_code", "")

    assert register(client).status_code == 201


# --- что продукт говорит про почту ---------------------------------------


def test_the_product_never_claims_the_email_is_verified(client, credentials):
    """Ни одно поле ответа не должно выглядеть как «адрес проверен»."""
    payload = client.post(REGISTER, json=credentials).json()

    assert "verified" not in str(payload).lower()
    assert "подтвержд" not in str(payload).lower()


def test_the_warning_about_the_email_says_both_consequences():
    """Человеку важны обе: адрес не проверяется и пароль не восстановить."""
    assert "не подтверждается" in UNVERIFIED_EMAIL_RU
    assert "Восстановления пароля" in UNVERIFIED_EMAIL_RU


def test_there_is_no_password_recovery_endpoint(client):
    """Восстановление по неподтверждённой почте было бы дырой, а не удобством:
    письмо ушло бы на адрес, принадлежность которого никто не проверял."""
    for path in (
        "/api/auth/forgot-password",
        "/api/auth/reset-password",
        "/api/auth/password-reset",
    ):
        assert client.post(path, json={"email": "nataly@example.com"}).status_code == 404
