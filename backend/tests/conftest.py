"""Общая настройка тестов.

Тесты гоняются на временной SQLite-базе, а не на PostgreSQL: они проверяют
логику авторизации, а не работу СУБД, и не должны требовать поднятого сервера
или трогать реальные данные. Переменная окружения задаётся до импорта
приложения — движок создаётся в момент импорта app.db.
"""

import os
import tempfile
from pathlib import Path

import pytest

_db_file = Path(tempfile.mkdtemp()) / "test.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_db_file}"

# Загруженные в тестах файлы не должны попадать в рабочую папку проекта.
_uploads = Path(tempfile.mkdtemp()) / "uploads"
os.environ["UPLOAD_DIR"] = str(_uploads)

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client():
    """Чистая база на каждый тест — тесты не должны зависеть друг от друга."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def credentials():
    return {"email": "nataly@example.com", "password": "verysecret123"}


@pytest.fixture
def signed_client(client, credentials):
    """Клиент с уже открытой сессией: модуль 2 весь под входом.

    Роль по умолчанию - кандидат. Рекрутерские и модераторские разделы ему
    недоступны, и это проверяется отдельными тестами: регистрация не должна
    выдавать прав над чужими данными.
    """
    client.post("/api/auth/register", json=credentials)
    return client


def _with_role(email, role):
    """Отдельный вход с ролью: своя сессия, своя кука.

    Клиент именно отдельный. Если бы роли жили на одном TestClient, каждая
    следующая регистрация перетирала бы куку предыдущей, и тест «кандидат не
    может в модерацию» проверял бы не то, что написано в его названии.

    Роль выдаётся записью в базе, а не запросом от клиента: в продукте это
    делает администратор скриптом `scripts/set_role.py`, и отдельного
    эндпоинта «стать модератором» нет и быть не должно.
    """
    from app.access import role_of
    from app.db import SessionLocal
    from app.models import User

    fresh = TestClient(app)
    fresh.post("/api/auth/register", json={"email": email, "password": "verysecret123"})
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=email).one()
        user.role = role
        db.commit()
        assert role_of(user) == role
    return fresh


@pytest.fixture
def recruiter_client(client):
    """Отдельный вход с ролью рекрутера."""
    return _with_role("recruiter@example.com", "recruiter")


@pytest.fixture
def moderator_client(client):
    """Отдельный вход с ролью модератора."""
    return _with_role("moderator@example.com", "moderator")
