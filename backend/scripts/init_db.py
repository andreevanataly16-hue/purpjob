r"""Создаёт базу данных, если её ещё нет.

Запуск (из папки backend):
    ..\.venv\Scripts\python.exe -m scripts.init_db

Скрипт подключается к служебной базе postgres теми же учётными данными, что
указаны в .env, и создаёт базу из DATABASE_URL. Таблицы внутри неё создаёт уже
само приложение при старте.
"""

import sys

import psycopg
from sqlalchemy.engine import make_url

from app.config import settings


def main() -> int:
    url = make_url(settings.database_url)
    target = url.database

    if not target:
        print("В DATABASE_URL не указано имя базы.", file=sys.stderr)
        return 1

    admin_dsn = (
        f"host={url.host or 'localhost'} port={url.port or 5432} "
        f"user={url.username} password={url.password} dbname=postgres"
    )

    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            exists = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (target,)
            ).fetchone()

            if exists:
                print(f"База «{target}» уже есть — ничего делать не нужно.")
                return 0

            # Имя базы нельзя подставить параметром, поэтому экранируем кавычки вручную.
            safe_name = target.replace('"', '""')
            conn.execute(f'CREATE DATABASE "{safe_name}" ENCODING \'UTF8\'')
            print(f"База «{target}» создана.")
            return 0

    except psycopg.OperationalError as error:
        print(f"Не удалось подключиться к PostgreSQL: {error}", file=sys.stderr)
        print(
            "Проверьте пароль в .env и что служба postgresql запущена.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
