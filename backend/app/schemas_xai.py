"""Схемы модуля 7: объяснения, споры, журнал, очередь модератора.

Структура повторяет §4 FRD. Одно отличие описано в `app/xai.py`: `explanation_id`
здесь не счётчик, а собранный идентификатор, переживающий пересчёт индекса.
"""

from datetime import datetime

from pydantic import BaseModel, Field


# --- объяснения -----------------------------------------------------------


class EvidenceRefOut(BaseModel):
    """Ссылка на доказательство, раскрытая до настоящей записи (FR2.1).

    Ссылка, которая никуда не ведёт, - дефект, а не допустимое упрощение,
    поэтому `resolved` здесь есть отдельным полем: непроверяемое «ну наверное
    оно там есть» этот модуль как раз и должен исключать.
    """

    ref: str
    kind: str
    resolved: bool
    title_ru: str
    detail_ru: str | None = None
    url: str | None = None
    file_name: str | None = None


class ExplanationOut(BaseModel):
    id: str
    subject_type: str
    subject_type_ru: str
    subject_id: str
    subject_label_ru: str
    subject_value_ru: str
    conclusion_ru: str
    evidence_refs: list[str]
    generated_by: str
    candidate_consent_for_recruiter_view: bool
    created_at: datetime

    # Спор доступен у любого объяснения без исключений (FR-Gov.1).
    dispute_label_ru: str
    disputable: bool
    open_dispute_id: str | None = None


class ExplanationDetailOut(ExplanationOut):
    """То же плюс раскрытые доказательства - экран «Почему такой вывод?»."""

    resolved_evidence: list[EvidenceRefOut]
    problems: list[str] = Field(default_factory=list)


class ExplanationsOut(BaseModel):
    why_label_ru: str
    explanations: list[ExplanationOut]


# --- споры ----------------------------------------------------------------


class DisputeIn(BaseModel):
    explanation_id: str = Field(min_length=1, max_length=160)
    # Необязательно и остаётся необязательным (FR3.2).
    candidate_statement: str | None = Field(default=None, max_length=4000)


class CandidateReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class HistoryEntryOut(BaseModel):
    id: str
    event_type: str
    event_ru: str
    actor: str
    actor_ru: str
    before_value: str | None
    after_value: str | None
    note_ru: str | None
    timestamp: datetime


class OverrideOut(BaseModel):
    id: str
    target_type: str
    target_id: str
    previous_value: str
    new_value: str
    rationale_ru: str
    applied_at: datetime


class DisputeOut(BaseModel):
    id: str
    explanation_id: str
    subject_type: str
    subject_type_ru: str
    subject_id: str
    conclusion_ru: str
    evidence_refs: list[str]
    origin: str
    candidate_statement: str | None
    status: str
    status_ru: str
    assigned_moderator: str | None
    info_request_ru: str | None
    created_at: datetime
    history: list[HistoryEntryOut]
    override: OverrideOut | None = None


class DisputesOut(BaseModel):
    dispute_label_ru: str
    note_ru: str
    cases: list[DisputeOut]


# --- модерация ------------------------------------------------------------


class ModerationActionIn(BaseModel):
    """Обоснование обязательно у всех трёх действий, а не только у правки."""

    rationale_ru: str = Field(min_length=1, max_length=4000)


class InfoRequestIn(BaseModel):
    question_ru: str = Field(min_length=1, max_length=1000)


class OverrideIn(BaseModel):
    target_type: str = Field(min_length=1, max_length=40)
    target_id: str = Field(min_length=1, max_length=120)
    new_value: str = Field(min_length=1, max_length=120)
    rationale_ru: str = Field(min_length=1, max_length=4000)


class QueueCaseOut(DisputeOut):
    candidate_email: str
    resolved_evidence: list[EvidenceRefOut]


class QueueStatsOut(BaseModel):
    """Данные под гипотезы H1: посильна ли ручная модерация и что чаще спорят."""

    resolved_count: int
    median_minutes_to_resolve: float | None
    disputes_by_subject_type: dict[str, int]


class QueueOut(BaseModel):
    # Что именно закрыто доступом, а что ещё нет - едет в ответе API, а не
    # только в README: границу должно быть видно оттуда, где ей пользуются.
    access_note_ru: str
    open_count: int
    cases: list[QueueCaseOut]
    override_targets: dict[str, list[str]]
    stats: QueueStatsOut
