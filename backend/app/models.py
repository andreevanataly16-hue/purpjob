"""Таблицы: кандидат, его сессии входа, утверждения профиля и Evidence.

Схема Statement / Evidence / DeclineRecord повторяет §4 FRD модуля 2 - имена
полей взяты оттуда дословно, чтобы JSON наружу совпадал со спецификацией.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
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


# Связь Statement <-> Evidence именно многие-ко-многим (FR3.5): одна ссылка на
# GitHub может подтверждать несколько компетенций, а одну компетенцию может
# подтверждать несколько разных доказательств.
statement_evidence = Table(
    "statement_evidence",
    Base.metadata,
    Column("statement_id", ForeignKey("statements.id", ondelete="CASCADE"), primary_key=True),
    Column("evidence_id", ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True),
)


class Statement(Base):
    """Заявленная компетенция кандидата (§3.1 FRD)."""

    __tablename__ = "statements"
    __table_args__ = (
        # Одна компетенция на кандидата: повторная находка не плодит дубли,
        # а усиливает уже существующее утверждение (FR2.4).
        UniqueConstraint("user_id", "skill_name", name="uq_statement_user_skill"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Канонический ключ таксономии - по-английски, чтобы позже сопоставляться
    # с эталонной библиотекой PROF; отдельным полем - название для кандидата.
    skill_name: Mapped[str] = mapped_column(String(120), nullable=False)
    skill_name_ru: Mapped[str] = mapped_column(String(120), nullable=False)

    category: Mapped[str] = mapped_column(String(40), nullable=False)
    source_of_claim: Mapped[str] = mapped_column(String(20), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    evidence: Mapped[list["Evidence"]] = relationship(
        secondary=statement_evidence, back_populates="statements", lazy="selectin"
    )


class Evidence(Base):
    """Доказательство: ссылка, файл, фрагмент текста или ответ Слепого свидетеля (§3.2)."""

    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_category: Mapped[str | None] = mapped_column(String(20), nullable=True)

    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    file_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # nda=True означает: самого артефакта здесь нет и не будет (FR4.2).
    nda: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    statements: Mapped[list[Statement]] = relationship(
        secondary=statement_evidence, back_populates="evidence", lazy="selectin"
    )


class DeclineRecord(Base):
    """Отказ раскрыть источник или факт (§3.3).

    Никогда ничего не отнимает: причина необязательна, статус компетенции от
    отказа не падает, а сам отказ обратим (FR4.3, FR4.7).
    """

    __tablename__ = "decline_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RawInput(Base):
    """Исходный текст кандидата дословно (FR2.5).

    Разбор на компетенции его не заменяет и не правит: контрольный образец
    нужен модулям 6 и 9, поэтому он хранится отдельно и не удаляется.
    """

    __tablename__ = "raw_inputs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
