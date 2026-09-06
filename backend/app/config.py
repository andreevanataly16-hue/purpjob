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

    # Этапы продукта. Модули 10-15 написаны и работают, но написан ≠ включён:
    # первый пилот с кандидатами не должен тащить с собой рекрутерскую
    # сторону. Она не проверена, расширяет поверхность приватности и мешает
    # читать результат - если в пилоте что-то не сойдётся, будет непонятно, из
    # какой половины продукта это следует.
    #
    # Ядро кандидата (модули 1-9) переключателя не имеет: это и есть продукт.
    enable_vacancy_experiment: bool = False
    enable_recruiter_pilot: bool = False

    # Клавиатурный почерк (модуль 4, FR3.4). ВЫКЛЮЧЕН и должен таким
    # оставаться: мастер-документ считает юридическую проверку этой
    # механики блокером запуска MVP-0, а не задачей на потом. Включать
    # только после письменного заключения юриста.
    keystroke_capture_enabled: bool = False


settings = Settings()
