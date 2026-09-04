"""Настройки приложения. Читаются из .env в корне проекта."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Подключение к PostgreSQL. Пароль задаётся в .env и в репозиторий не попадает.
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/purpjob"

    # Имя базы, которую создаёт scripts/init_db.py, если её ещё нет.
    database_name: str = "purpjob"

    # Сессия: непрозрачный токен в httpOnly-куке, срок жизни в днях.
    session_cookie_name: str = "purpjob_session"
    session_ttl_days: int = 30

    # На проде кука должна уходить только по HTTPS. Локально работаем по http,
    # поэтому по умолчанию False; в .env продакшена ставится True.
    cookie_secure: bool = False

    # Минимальная длина пароля. Дублируется в валидации на фронтенде.
    password_min_length: int = 8

    # Куда складываются файлы-артефакты кандидата (модуль 2). В тестах
    # переопределяется переменной окружения UPLOAD_DIR на временную папку.
    upload_dir: Path = PROJECT_ROOT / "backend" / "uploads"


settings = Settings()
