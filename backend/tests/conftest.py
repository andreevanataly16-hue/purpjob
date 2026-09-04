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
    """Клиент с уже открытой сессией: модуль 2 весь под входом."""
    client.post("/api/auth/register", json=credentials)
    return client
