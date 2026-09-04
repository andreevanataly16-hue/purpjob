"""Таблицы: кандидат и его сессии входа.

Профиль, Evidence, PROF и Trust появятся отдельными таблицами позже — здесь
только то, что нужно для входа в систему (модуль 1 роадмапа).
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Почта хранится в нижнем регистре, уникальность обеспечивает сама БД,
    # а не проверка в коде — иначе два одновременных запроса создадут дубль.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)

    # Хеш пароля (scrypt), не сам пароль.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)

    # В базе лежит SHA-256 от токена, а не сам токен: утечка дампа не даёт
    # злоумышленнику готовых работающих сессий.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[User] = relationship(back_populates="sessions")

    @property
    def is_expired(self) -> bool:
        expires = self.expires_at
        # Не всякая СУБД возвращает дату с часовым поясом. Считаем такую дату
        # временем UTC - иначе сравнение упало бы на naive/aware.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires <= utcnow()
