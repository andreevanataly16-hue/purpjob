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
from sqlalchemy import event
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

    # Модуль 12: можно ли рекрутеру раскрывать сами доказательства. Это про
    # глубину, а не про то, виден ли профиль вообще - два разных решения.
    consent_for_recruiter_view: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # Модуль 13: отказ от поэтапного раскрытия. Выключено у всех по умолчанию -
    # поэтапность и есть механизм против предвзятости, а это осознанный выход
    # из него, а не настройка «по вкусу».
    allow_immediate_identity_reveal: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

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


class TrustFinding(Base):
    """Ответ кандидата на находку об атрибуции (§4.3 FRD модуля 6).

    Сама находка не хранится: она пересчитывается из данных профиля. Хранится
    только решение кандидата - и оно ничего не отнимает ни в каком случае.

    Отказ здесь сильнее обычного: от находки не остаётся следа вовсе. Поэтому
    он не пишется в DeclineRecord - запись об отказе как раз и была бы следом.
    """

    __tablename__ = "trust_findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Источник, про который спросили. Доказательство может быть удалено - тогда
    # запись остаётся сиротой и в расчёт не идёт.
    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True
    )
    candidate_response: Mapped[str] = mapped_column(String(30), nullable=False)
    responded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ContradictionCase(Base):
    """Нестыковка между двумя сведениями самого кандидата (§4.4).

    Найдена локальными проверками - наружу этот модуль не ходит. Разбирается
    одним из трёх способов, и ни один из них не наказание: это обычное
    приведение профиля в порядок.
    """

    __tablename__ = "contradiction_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    statement_id: Mapped[int | None] = mapped_column(
        ForeignKey("statements.id", ondelete="CASCADE"), nullable=True
    )
    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True
    )

    detected_by: Mapped[str] = mapped_column(
        String(30), default="local_consistency_check", nullable=False
    )
    check_type: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), default="minor", nullable=False)
    detail_ru: Mapped[str] = mapped_column(Text, default="", nullable=False)

    resolution_path: Mapped[str | None] = mapped_column(String(20), nullable=True)
    explanation_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    # Приостановка показа профиля по спорному уровню. В этой фазе рекрутерской
    # стороны нет, поэтому поле только заполняется - показывать его негде.
    visibility_suspended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DisputeCase(Base):
    """Спор кандидата с выводом системы (§4.2 модуля 7).

    Появление спора ничего не меняет в самом выводе: статус компетенции и балл
    Trust остаются ровно теми же, пока модератор не решит иначе (FR3.3). Спор -
    это запрос на проверку, а не признание и не автоматическое понижение.

    Текст объяснения и список доказательств копируются сюда на момент спора:
    PROF и Trust пересчитываются на каждый запрос, и без копии модератор увидел
    бы уже другой вывод, а не тот, который оспорили (FR4.2).
    """

    __tablename__ = "dispute_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    explanation_id: Mapped[str] = mapped_column(String(160), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(120), nullable=False)

    # Снимок оспоренного вывода - именно то, что видел кандидат.
    explanation_conclusion_ru: Mapped[str] = mapped_column(Text, default="", nullable=False)
    explanation_evidence_refs: Mapped[str] = mapped_column(Text, default="", nullable=False)

    origin: Mapped[str] = mapped_column(String(30), default="candidate_escalation", nullable=False)

    # Обоснование спора необязательно: «мне кажется, это неверно» - достаточная
    # причина, требовать от кандидата собирать дело мы не будем (FR3.2).
    candidate_statement: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    assigned_moderator: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Конкретный вопрос модератора, когда нужны подробности (FR4.3b).
    info_request_ru: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DisputeHistoryEntry(Base):
    """Запись журнала спора (§4.3). Только добавление, никогда правка.

    Это не стилистическое пожелание, а механизм: если записи можно было бы
    менять, журнал перестал бы годиться на то единственное, ради чего он есть -
    восстановить, почему профиль или Trust изменились (US5). Запрет на UPDATE и
    DELETE стоит ниже обработчиками SQLAlchemy, а не только на словах (FR5.1).
    """

    __tablename__ = "dispute_history_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    dispute_case_id: Mapped[int] = mapped_column(
        ForeignKey("dispute_cases.id", ondelete="CASCADE"), index=True, nullable=False
    )

    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    actor: Mapped[str] = mapped_column(String(20), nullable=False)

    before_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    note_ru: Mapped[str | None] = mapped_column(Text, nullable=True)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ModeratorOverride(Base):
    """Ручное исправление вывода системы (§4.4).

    `rationale_ru` обязателен. Человек без объяснения - ровно та же проблема
    неоспоримого судьи, ради которой существует весь модуль, только судья
    сменился с алгоритма на сотрудника (FR4.3).

    Правка всегда адресная: одно поле одного объекта. Общего «поправить профиль»
    здесь нет и быть не должно (FR4.4).
    """

    __tablename__ = "moderator_overrides"

    id: Mapped[int] = mapped_column(primary_key=True)
    dispute_case_id: Mapped[int] = mapped_column(
        ForeignKey("dispute_cases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(120), nullable=False)

    previous_value: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    new_value: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    rationale_ru: Mapped[str] = mapped_column(Text, nullable=False)

    # Запись журнала, породившая эту правку. Хранится ссылкой, а не пересчётом
    # по совпадению полей: FR5.4 требует прослеживаемости от изменённого балла
    # обратно к строке журнала, а не «где-то там оно записано».
    history_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("dispute_history_entries.id", ondelete="SET NULL"), nullable=True
    )

    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AnomalyFlag(Base):
    """Сигнал детектора аномалий (§4.5). Производителя в этой фазе нет.

    Форма принята, чтобы очередь модератора умела работать со всеми тремя
    источниками сразу, а не переделывалась потом. Но детекторов (стилометрия
    против Raw Input, переключение вкладок) в продукте нет: они вынесены из
    объёма модуля (§2.2). Ни один рабочий путь такие записи не создаёт - это
    проверяется тестом, а не оговоркой в документации.
    """

    __tablename__ = "anomaly_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    flag_type: Mapped[str] = mapped_column(String(30), nullable=False)
    subject_evidence_or_answer_id: Mapped[str] = mapped_column(String(60), nullable=False)

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VacancyCheckpoint(Base):
    """Отметка «до какого момента вакансии уже видели» (§4.3 модуля 11).

    Замена живому парсингу на эту фазу. Когда парсинг появится, он станет
    вторым производителем того же события, а эта отметка просто уйдёт - ниже
    по течению не меняется ничего.
    """

    __tablename__ = "vacancy_checkpoints"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    last_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VacancyMatchState(Base):
    """Каким было совпадение с вакансией в прошлый раз (модуль 11, US4).

    Нужна ровно для одного: понять, что закрытый пробел помог не только той
    вакансии, ради которой кандидат вернулся. Без записи прошлого состояния
    «стало лучше ещё в двух местах» посчитать не из чего - совпадение нигде
    не хранится, оно пересчитывается.
    """

    __tablename__ = "vacancy_match_states"
    __table_args__ = (
        UniqueConstraint("user_id", "vacancy_id", name="uq_match_state_user_vacancy"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    vacancy_id: Mapped[str] = mapped_column(String(40), nullable=False)

    match_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Список закрытых требований через запятую: сравнивать нужно состав, а не
    # только число - балл может не измениться, а требование закрыться.
    covered_requirement_ids: Mapped[str] = mapped_column(Text, default="", nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RevealState(Base):
    """До какого этапа рекрутер дошёл по конкретному кандидату (§4.1 модуля 13).

    Привязка к паре «рекрутер + кандидат», а не к вакансии: раскрытая личность
    не закрывается обратно, если тот же рекрутер найдёт того же человека под
    другой вакансией. И этап одного рекрутера ничего не значит для другого.

    Слой чисто отображающий: никакие данные модулей 3/6/10/12 отсюда не
    меняются, меняется только то, что из них показано.
    """

    __tablename__ = "reveal_states"
    __table_args__ = (
        UniqueConstraint("recruiter_user_id", "candidate_id", name="uq_reveal_recruiter_candidate"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recruiter_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    candidate_id: Mapped[str] = mapped_column(String(60), nullable=False)

    current_stage: Mapped[str] = mapped_column(
        String(30), default="stage1_professional", nullable=False
    )
    advance_trigger: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Третий этап требует ДВУХ решений: рекрутер попросил и кандидат разрешил.
    # Одного действия рекрутера здесь недостаточно - в отличие от второго этапа.
    contact_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    candidate_contact_opt_in: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    stage2_advanced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stage3_advanced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --- журнал только на добавление (FR5.1) ---------------------------------
#
# Запрет держится на уровне кода, а не договорённости: любая попытка изменить
# или удалить запись журнала падает с ошибкой. Исправление ошибочной записи -
# это новая запись, а не правка старой.


class AppendOnlyViolation(RuntimeError):
    """Кто-то попытался изменить или удалить запись журнала споров."""


@event.listens_for(DisputeHistoryEntry, "before_update", propagate=True)
def _forbid_history_update(mapper, connection, target) -> None:  # noqa: ARG001
    raise AppendOnlyViolation(
        "Журнал спора только пополняется: исправление - это новая запись, а не правка старой."
    )


@event.listens_for(DisputeHistoryEntry, "before_delete", propagate=True)
def _forbid_history_delete(mapper, connection, target) -> None:  # noqa: ARG001
    raise AppendOnlyViolation("Записи журнала спора не удаляются.")


class SearchContext(Base):
    """Эпизод поиска работы (§4.1 модуля 8).

    В этой фазе сущность существует ровно затем, чтобы гарантию сохранности
    можно было проверить: закрытие эпизода поиска не должно делать с профилем
    вообще ничего. Настоящего процесса отклика в продукте нет, поэтому записи
    создаются только тестами - но связь `search_context_id` заведена, чтобы
    будущий модуль откликов не спроектировали так, что он умеет каскадно
    удалять доказательства.
    """

    __tablename__ = "search_contexts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    label: Mapped[str] = mapped_column(String(200), default="", nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Заполнение этого поля обязано не иметь последствий ни для чего (FR1.1).
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProfileGrowthEvent(Base):
    """Как профиль становился сильнее (§4.2 модуля 8). Только добавление.

    Это отдельный журнал от журнала споров модуля 7, и сливать их нельзя:
    тот нужен для отчётности - кто и что изменил; этот для кандидата - что у
    него выросло и когда. Разные читатели и разный тон.
    """

    __tablename__ = "profile_growth_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_ref: Mapped[str] = mapped_column(String(120), default="", nullable=False)

    # Что с чем стало. Хранится здесь, потому что статусы нигде не хранятся:
    # они пересчитываются, и без записи прошлое состояние восстановить нечем.
    from_value: Mapped[str | None] = mapped_column(String(120), nullable=True)
    to_value: Mapped[str | None] = mapped_column(String(120), nullable=True)

    description_ru: Mapped[str] = mapped_column(Text, default="", nullable=False)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CompetencyFreshness(Base):
    """Актуальность подтверждения компетенции (§4.3 модуля 8).

    Множитель отсюда читает ТОЛЬКО модуль 3 при сборке индекса. Trust Score его
    не видит и видеть не должен: устаревание - это про соответствие рынку, а не
    про достоверность сведений (§0 FRD). На сам статус компетенции и на
    доказательства это не влияет вообще - подтверждённое остаётся
    подтверждённым навсегда.
    """

    __tablename__ = "competency_freshness"
    __table_args__ = (
        UniqueConstraint("user_id", "competency_id", name="uq_freshness_user_competency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    competency_id: Mapped[str] = mapped_column(String(60), nullable=False)

    last_confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decay_countdown_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ReturnTrigger(Base):
    """Повод вернуться (§4.4 модуля 8).

    Значимая величина здесь одна - `acted_upon`. Открытое уведомление ничего не
    доказывает: гипотеза H1b проверяется тем, вернулся ли человек и сделал ли
    что-то, а не тем, сколько раз ему показали напоминание.
    """

    __tablename__ = "return_triggers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    trigger_type: Mapped[str] = mapped_column(String(40), nullable=False)
    related_ref: Mapped[str] = mapped_column(String(120), default="", nullable=False)

    # Модуль 11, только для повода «появилась подходящая вакансия». Совпадение
    # записывается на момент срабатывания: обещание «62%» должно остаться
    # верным, даже если профиль с тех пор изменился и балл стал другим.
    match_score_at_detection: Mapped[int | None] = mapped_column(Integer, nullable=True)
    explanation_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acted_upon_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@event.listens_for(ProfileGrowthEvent, "before_update", propagate=True)
def _forbid_growth_update(mapper, connection, target) -> None:  # noqa: ARG001
    raise AppendOnlyViolation(
        "История роста только пополняется: переписать прошлое нельзя, иначе она перестанет "
        "быть историей."
    )


@event.listens_for(ProfileGrowthEvent, "before_delete", propagate=True)
def _forbid_growth_delete(mapper, connection, target) -> None:  # noqa: ARG001
    raise AppendOnlyViolation("Записи истории роста не удаляются.")


class ExportRequest(Base):
    """Факт выгрузки резюме (§4.1 модуля 9).

    Запись существует только для самого кандидата: по ней он потом поймёт,
    каким был профиль в момент выгрузки. Полей получателя, статуса доставки и
    отслеживания здесь нет - и добавлять их нельзя: сам факт их появления был
    бы первым шагом к рассылке, которую модуль запрещает.
    """

    __tablename__ = "export_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    format: Mapped[str] = mapped_column(String(10), default="pdf", nullable=False)
    include_contacts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # На какие снимки опирался этот файл - чтобы кандидат мог сопоставить
    # выгруженный документ с состоянием профиля.
    prof_segment: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    prof_level: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    trust_score_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RecruiterFeedback(Base):
    """Что рекрутер увидел вживую после того, как посмотрел профиль (модуль 14).

    Четвёртый механизм обратной связи в продукте, и сливать его с тремя
    предыдущими нельзя: «вопрос не подходит» - про качество вопроса, спор - про
    вывод об одном человеке, поводы вернуться - про удержание. Здесь - про то,
    совпал ли вывод системы с реальностью, и это сигнал про формулу.

    **Отзыв не меняет балл кандидата ни при каких условиях.** Мнение одного
    человека не должно уметь уронить чей-то профиль - на этом стоит весь
    модуль 6, и данные отсюда идут только в общую статистику.
    """

    __tablename__ = "recruiter_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    recruiter_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    candidate_id: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    vacancy_id: Mapped[str | None] = mapped_column(String(60), nullable=True)

    relevance_outcome: Mapped[str] = mapped_column(String(30), nullable=False)

    # Баллы на момент отзыва. Хранятся здесь, потому что сравнивать вывод с
    # исходом нужно по тому, что система утверждала тогда, а не по тому, во что
    # профиль превратился позже.
    trust_score_at_feedback: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prof_score_at_feedback: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    free_text_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ComponentFeedback(Base):
    """Отметка «полезно / ввело в заблуждение» на конкретном выводе.

    Адресуется через `explanation_id` модуля 7 - тем же способом, которым
    адресуется всё остальное. Второй, более рыхлый способ сказать «раздел Trust
    был непонятный» означал бы, что сводку потом не собрать.
    """

    __tablename__ = "component_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    feedback_id: Mapped[int] = mapped_column(
        ForeignKey("recruiter_feedback.id", ondelete="CASCADE"), index=True, nullable=False
    )

    explanation_id: Mapped[str] = mapped_column(String(160), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(120), nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    comment_ru: Mapped[str | None] = mapped_column(Text, nullable=True)

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CalibrationConstantChangeLog(Base):
    """Изменение калибруемой константы (§4.4 модуля 14). Только добавление.

    Единственный законный путь, которым любая калибруемая величина в этом
    продукте вообще может измениться. Человек, меняющий то, как система считает
    всех дальше, отвечает как минимум так же, как модератор, правящий одну
    запись, - поэтому причина обязательна.

    Изменение действует только вперёд: прошлые снимки - исторический факт, и
    задним числом они не переписываются.
    """

    __tablename__ = "calibration_constant_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    constant_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    previous_value: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    new_value: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    rationale_ru: Mapped[str] = mapped_column(Text, nullable=False)

    # На чём основано решение - чтобы через полгода было видно не только что
    # поменяли, но и почему это тогда выглядело обоснованным.
    based_on_feedback_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trust_accuracy_before: Mapped[int | None] = mapped_column(Integer, nullable=True)

    applied_by: Mapped[str] = mapped_column(String(120), default="operator", nullable=False)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuditBatch(Base):
    """Партия профилей, отобранных на ручную проверку (§4.5 модуля 14).

    Этот модуль - отборщик, а модуль 7 - проверяющий: каждый отобранный
    кандидат превращается в обычный спор `origin: sampled_audit` и разбирается
    существующей очередью. Второго экрана разбора здесь нет намеренно.
    """

    __tablename__ = "audit_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    selection_criteria: Mapped[str] = mapped_column(String(30), nullable=False)
    candidate_ids: Mapped[str] = mapped_column(Text, default="", nullable=False)
    dispute_case_ids: Mapped[str] = mapped_column(Text, default="", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


@event.listens_for(CalibrationConstantChangeLog, "before_update", propagate=True)
def _forbid_calibration_update(mapper, connection, target) -> None:  # noqa: ARG001
    raise AppendOnlyViolation(
        "Журнал калибровки только пополняется: исправление - это новая запись."
    )


@event.listens_for(CalibrationConstantChangeLog, "before_delete", propagate=True)
def _forbid_calibration_delete(mapper, connection, target) -> None:  # noqa: ARG001
    raise AppendOnlyViolation("Записи журнала калибровки не удаляются.")


class VerificationInvite(Base):
    """Приглашение кандидату подтвердить профиль (§4.5 модуля 15).

    Записывается только сам факт: кто создал и когда. Ни адресата, ни канала,
    ни статуса доставки - потому что отправки нет. Рекрутер копирует ссылку и
    отправляет сам, своим каналом; то же правило, что у экспорта в модуле 9,
    только с другой стороны.

    Кандидат, пришедший по ссылке, проходит обычный вход и обычное наполнение
    профиля: этот модуль добавляет новую дверь, а не короткий путь.
    """

    __tablename__ = "verification_invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    recruiter_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    note_ru: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="generated", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
