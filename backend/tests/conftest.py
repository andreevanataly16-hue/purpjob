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

# В тестах включены все этапы продукта: проверять модули 10-15 надо независимо
# от того, включены ли они в текущей поставке. Что выключение действительно
# убирает их из приложения - проверяется отдельно, на отдельном процессе с
# выключенными флагами (test_stabilization.py).
os.environ["ENABLE_VACANCY_EXPERIMENT"] = "true"
os.environ["ENABLE_RECRUITER_PILOT"] = "true"

# Регистрация в тестах без кода приглашения: почти каждый тест начинается с
# создания профиля, и код приглашения в каждом из них проверял бы фикстуру, а
# не продукт. Что закрытый режим действительно закрывает регистрацию -
# проверяется отдельно, переключением настройки (test_pilot_mode.py).
os.environ["REGISTRATION_MODE"] = "open"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

import contextlib  # noqa: E402


@contextlib.asynccontextmanager
async def _no_schema_check(_app):
    """Пустой запуск приложения для тестов.

    Приложение при старте требует применённых миграций - иначе оно поднялось
    бы на схеме, не соответствующей коду. В тестах схема строится из моделей,
    поэтому проверка здесь только мешала бы: она проверяла бы фикстуру, а не
    продукт. Сами миграции проверяются отдельным тестом - тем, что дают ровно
    такую же схему.
    """
    yield


app.router.lifespan_context = _no_schema_check


@pytest.fixture
def client():
    """Чистая база на каждый тест — тесты не должны зависеть друг от друга.

    Схема здесь строится из моделей, а не прогоном миграций: база создаётся
    заново на каждый тест, и миграции в этом месте проверяли бы скорость
    Alembic, а не логику продукта. Сами миграции проверяются отдельно - тем,
    что дают ровно ту же схему (см. test_stabilization.py).
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _clean_login_limiter():
    """Счётчик попыток входа живёт в памяти процесса, а не в базе.

    База пересоздаётся на каждый тест, а счётчик - нет: без этой фикстуры
    тесты, которые намеренно вводят неверный пароль, копили бы неудачи друг
    другу и однажды получили бы 429 вместо 401 в тесте совсем про другое.
    """
    from app.ratelimit import login_limiter

    login_limiter.reset()
    yield
    login_limiter.reset()


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
