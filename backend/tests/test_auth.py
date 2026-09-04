"""Проверки регистрации, входа, выхода и хранения пароля."""

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User, UserSession
from app.security import verify_password

REGISTER = "/api/auth/register"
LOGIN = "/api/auth/login"
LOGOUT = "/api/auth/logout"
ME = "/api/auth/me"

WRONG_PAIR = "Неверная почта или пароль."


def test_health(client):
    assert client.get("/api/health").status_code == 200


def test_me_without_session_is_401(client):
    assert client.get(ME).status_code == 401


def test_register_creates_user_and_opens_session(client, credentials):
    response = client.post(REGISTER, json=credentials)

    assert response.status_code == 201
    assert response.json()["email"] == credentials["email"]
    assert "purpjob_session" in client.cookies

    me = client.get(ME)
    assert me.status_code == 200
    assert me.json()["email"] == credentials["email"]


def test_register_never_returns_password(client, credentials):
    body = client.post(REGISTER, json=credentials).text
    assert credentials["password"] not in body
    assert "hash" not in body


def test_email_is_normalized(client):
    response = client.post(
        REGISTER, json={"email": "  Nataly@Example.COM  ", "password": "verysecret123"}
    )
    assert response.json()["email"] == "nataly@example.com"


def test_duplicate_email_is_409(client, credentials):
    client.post(REGISTER, json=credentials)
    second = client.post(REGISTER, json={**credentials, "password": "anotherpass123"})
    assert second.status_code == 409


def test_short_password_is_rejected(client):
    response = client.post(REGISTER, json={"email": "a@example.com", "password": "1234"})
    assert response.status_code == 422


def test_malformed_email_is_rejected(client):
    response = client.post(REGISTER, json={"email": "not-an-email", "password": "verysecret123"})
    assert response.status_code == 422


def test_login_with_correct_credentials(client, credentials):
    client.post(REGISTER, json=credentials)
    client.post(LOGOUT)

    response = client.post(LOGIN, json=credentials)
    assert response.status_code == 200
    assert client.get(ME).status_code == 200


def test_login_accepts_different_case_and_spaces(client, credentials):
    client.post(REGISTER, json=credentials)
    client.post(LOGOUT)

    response = client.post(
        LOGIN, json={"email": "  NATALY@example.com  ", "password": credentials["password"]}
    )
    assert response.status_code == 200


def test_wrong_password_and_unknown_email_look_identical(client, credentials):
    """Ответ не должен подсказывать, зарегистрирована ли почта."""
    client.post(REGISTER, json=credentials)
    client.post(LOGOUT)

    wrong_password = client.post(LOGIN, json={**credentials, "password": "wrongpass123"})
    unknown_email = client.post(
        LOGIN, json={"email": "nobody@example.com", "password": "verysecret123"}
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"] == WRONG_PAIR


def test_logout_ends_session(client, credentials):
    client.post(REGISTER, json=credentials)

    assert client.post(LOGOUT).status_code == 204
    assert client.get(ME).status_code == 401


def test_password_is_stored_hashed(client, credentials):
    client.post(REGISTER, json=credentials)

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == credentials["email"]))

    assert credentials["password"] not in user.password_hash
    assert user.password_hash.startswith("scrypt$")
    assert verify_password(credentials["password"], user.password_hash)
    assert not verify_password("verysecret124", user.password_hash)


def test_session_token_is_not_stored_raw(client, credentials):
    """В базе лежит хеш токена: дамп таблицы не даёт готовых сессий."""
    client.post(REGISTER, json=credentials)
    raw_token = client.cookies.get("purpjob_session")

    with SessionLocal() as db:
        stored = db.scalars(select(UserSession.token_hash)).all()

    assert raw_token not in stored


def test_forged_cookie_is_rejected(client, credentials):
    client.post(REGISTER, json=credentials)
    client.cookies.set("purpjob_session", "forged-token-that-was-never-issued")

    assert client.get(ME).status_code == 401
