"""Схемы запросов и ответов API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.config import settings


class Credentials(BaseModel):
    """Тело запроса на регистрацию и на вход."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class RegisterCredentials(Credentials):
    """При регистрации к паролю есть требования, при входе - уже нет."""

    password: str = Field(min_length=settings.password_min_length, max_length=1024)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    created_at: datetime
    # Роль отдаётся, чтобы экран показывал только то, чем человек может
    # пользоваться. Решает по-прежнему сервер: это подсказка интерфейсу, а не
    # источник прав - присланную обратно роль никто не читает.
    role: str
