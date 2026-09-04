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

    # evidence, statement или question: вопрос Contextual Probe, от которого
    # кандидат отказался по NDA, - тот же самый механизм отказа (FR5.5 модуля 4).
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


class ProfRole(Base):
    """Целевая роль кандидата: сегмент фиксирован, уровень выбирает кандидат.

    Снимок PROF.индекса в базе не хранится - он считается на каждый запрос
    (§8 FRD). Хранить нужно только сам факт «кандидат отслеживает этот уровень».
    """

    __tablename__ = "prof_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "level", name="uq_prof_role_user_level"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VisibilityState(Base):
    """Видимость профиля: hidden или visible, третьего в MVP нет (FR4.3).

    По умолчанию hidden: кандидат приходит без намерения искать работу, и
    Self-Audit не должен требовать публикации. Решение помечено в FRD как
    открытый вопрос к продукту (§9) - если ответ будет другим, меняется
    значение по умолчанию здесь.
    """

    __tablename__ = "visibility_states"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    mode: Mapped[str] = mapped_column(String(20), default="hidden", nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProbeQuestion(Base):
    """Вопрос Contextual Probe (§4.2 FRD).

    Статусы: pending, answered, skipped, declined_nda, flagged_bad. К набору из
    спецификации добавлен `retired`: по FR1.3 вопрос по уже подтверждённой
    компетенции снимается сам, и это надо отличать от пропуска кандидатом.
    """

    __tablename__ = "probe_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    competency_id: Mapped[str] = mapped_column(String(60), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), default="white_spot", nullable=False)

    # Артефакт, вокруг детали которого построен вопрос. None - запасной путь
    # без привязки к материалам (FR2.4).
    artifact_evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True
    )
    template_id: Mapped[str] = mapped_column(String(60), nullable=False)
    text_ru: Mapped[str] = mapped_column(Text, nullable=False)

    # Объяснение «почему этот вопрос» - обязательная часть вопроса, а не
    # необязательная приписка (FR4.1): без него вопрос показывать нельзя.
    reason_ru: Mapped[str] = mapped_column(Text, nullable=False)

    grounded: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Абстрактная переформулировка после отказа по NDA (FR5.2). Второй отказ от
    # неё уже не переформулируется - это обычный пропуск.
    nda_abstract: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Слова «ловушки на жаргон» и заготовка уточняющего вопроса хранятся вместе
    # с вопросом: библиотека шаблонов со временем меняется, а разбирать ответ
    # нужно по тем правилам, по которым вопрос был задан.
    expected_terms: Mapped[str] = mapped_column(Text, default="", nullable=False)
    follow_up_text: Mapped[str] = mapped_column(Text, default="", nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProbeAnswer(Base):
    """Ответ кандидата (§4.3 FRD) вместе с результатом маршрутизации сигналов."""

    __tablename__ = "probe_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("probe_questions.id", ondelete="CASCADE"), index=True, nullable=False
    )

    text: Mapped[str] = mapped_column(Text, nullable=False)

    # Только свободная форма и ничего кроме (US3, FR3.1). Поле существует
    # именно для того, чтобы ограничение можно было проверить тестом, а не
    # держать в голове как договорённость об интерфейсе.
    format: Mapped[str] = mapped_column(String(20), default="free_text", nullable=False)

    typed_duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paste_attempts_blocked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Заполняется только при включённом флаге (FR3.4). Молча - никогда.
    keystroke_meta: Mapped[str | None] = mapped_column(Text, nullable=True)

    understanding_signal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    new_competency_signal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Доказательство, в которое превратился ответ. Пусто, пока ответ не прошёл
    # проверку на конкретность: общая фраза компетенцию не подтверждает.
    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True
    )

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProbeFollowUp(Base):
    """Уточняющий вопрос Semantic Depth (§4.4 FRD). Не больше одного на ответ."""

    __tablename__ = "probe_follow_ups"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    answer_id: Mapped[int] = mapped_column(
        ForeignKey("probe_answers.id", ondelete="CASCADE"), index=True, nullable=False
    )

    trigger_reason: Mapped[str] = mapped_column(String(20), nullable=False)
    text_ru: Mapped[str] = mapped_column(Text, nullable=False)
    # Уточнение тоже не появляется из ниоткуда: видно, что это та же проверка
    # той же компетенции (FR4.3).
    reason_ru: Mapped[str] = mapped_column(Text, default="", nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProbeFeedback(Base):
    """«Вопрос не подходит» (§4.5 FRD).

    Собирается как сырые данные для калибровки шаблонов: механика поощрений за
    найденные плохие вопросы - процесс, а не код (Гл. 13).
    """

    __tablename__ = "probe_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("probe_questions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    template_id: Mapped[str] = mapped_column(String(60), nullable=False)

    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Загрузка скриншота к жалобе не реализована - поле оставлено под неё.
    screenshot_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NDACase(Base):
    """Случай подтверждения под NDA (§4.1 FRD модуля 5).

    Заводится, когда кандидат отказался отвечать на вопрос по NDA (модуль 4)
    или сам попросил подтвердить компетенцию закрытым способом. Отсюда идут
    оба метода - Слепой свидетель и зеркальная задача.
    """

    __tablename__ = "nda_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    competency_id: Mapped[str] = mapped_column(String(60), nullable=False)
    statement_id: Mapped[int | None] = mapped_column(
        ForeignKey("statements.id", ondelete="SET NULL"), nullable=True
    )
    source_evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True
    )
    # Откуда пришёл случай: probe (отказ по вопросу) или white_spot.
    origin: Mapped[str] = mapped_column(String(20), default="white_spot", nullable=False)

    # Пока не подтверждена дисклеймером, дальше выбора метода дело не идёт
    # (FR1.1 - это жёсткие ворота, а не пожелание).
    disclaimer_ack_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    status: Mapped[str] = mapped_column(String(20), default="method_selection", nullable=False)
    suggested_method: Mapped[str] = mapped_column(String(20), default="blind_witness", nullable=False)
    chosen_method: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NDAMethodSwitch(Base):
    """Смена способа подтверждения (§4.2).

    Пишется только для продуктовой аналитики: сколько раз кандидат передумал -
    не повод его в чём-то ограничивать или как-то помечать.
    """

    __tablename__ = "nda_method_switches"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    case_id: Mapped[int] = mapped_column(
        ForeignKey("nda_cases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    from_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_method: Mapped[str] = mapped_column(String(20), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NDABlindWitnessQuestion(Base):
    """Вопрос Слепого свидетеля и ответ на него (§4.3)."""

    __tablename__ = "nda_blind_witness_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    case_id: Mapped[int] = mapped_column(
        ForeignKey("nda_cases.id", ondelete="CASCADE"), index=True, nullable=False
    )

    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    template_id: Mapped[str] = mapped_column(String(60), nullable=False)
    prompt_ru: Mapped[str] = mapped_column(Text, nullable=False)
    # «Почему этот вопрос» - то же требование прозрачности, что в модуле 4.
    reason_ru: Mapped[str] = mapped_column(Text, nullable=False)
    expected_terms: Mapped[str] = mapped_column(Text, default="", nullable=False)

    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Уточняющий вопрос Semantic Depth, если ответ оказался слишком общим.
    follow_up_ru: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_reason_ru: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_answer: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NDAMirrorSolution(Base):
    """Решение зеркальной задачи (§4.5).

    Без объяснения логики решение не считается: расставленные узлы сами по себе
    ничего не подтверждают.
    """

    __tablename__ = "nda_mirror_solutions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    case_id: Mapped[int] = mapped_column(
        ForeignKey("nda_cases.id", ondelete="CASCADE"), index=True, nullable=False
    )

    scenario_id: Mapped[str] = mapped_column(String(80), nullable=False)
    # JSON-строка: [{"node_id": "n1", "order": 1, "role_ru": "..."}]
    node_arrangement: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    logic_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    follow_up_ru: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_reason_ru: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_answer: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
