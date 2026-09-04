"""Схемы модуля 4. Структура ответов повторяет §4 FRD."""

from datetime import datetime

from pydantic import BaseModel, Field


class NextIn(BaseModel):
    """Можно попросить вопрос по конкретному белому пятну, можно - по любому."""

    competency_id: str | None = None


class AnswerIn(BaseModel):
    """Ответ всегда свободным текстом: другого формата в модуле нет (US3)."""

    text: str = Field(min_length=1, max_length=20000)
    typed_duration_ms: int = Field(default=0, ge=0)
    paste_attempts_blocked: int = Field(default=0, ge=0)
    # Приходит только при включённом флаге; иначе сервер это поле игнорирует.
    keystroke_meta: str | None = Field(default=None, max_length=100000)


class FollowUpAnswerIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class DeclineIn(BaseModel):
    """Причина отказа не обязательна - как и везде в продукте (FR5.3)."""

    reason: str | None = Field(default=None, max_length=500)


class FeedbackIn(BaseModel):
    reason: str
    comment: str | None = Field(default=None, max_length=1000)


class QuestionOut(BaseModel):
    id: str
    competency_id: str
    competency_name_ru: str
    target_type: str
    template_id: str
    text_ru: str
    # Обязательная пара к тексту вопроса: без объяснения вопрос не показывают.
    reason_ru: str
    grounded: bool
    nda_abstract: bool
    artifact_evidence_id: str | None
    answer_format: str
    status: str
    status_ru: str
    created_at: datetime


class FollowUpOut(BaseModel):
    id: str
    question_id: str
    trigger_reason: str
    text_ru: str
    reason_ru: str
    answer: str | None


class HistoryOut(QuestionOut):
    """Вопрос вместе с тем, чем он закончился (FR4.4)."""

    answer_text: str | None
    understanding_signal: bool
    new_competency_signal: bool
    declined: bool
    follow_ups: list[FollowUpOut]


class TargetOut(BaseModel):
    competency_id: str
    name_ru: str
    weight: float
    target_type: str


class ReasonOut(BaseModel):
    value: str
    label: str


class ProbeOut(BaseModel):
    available: bool
    # Почему спрашивать нечего - текст для кандидата (FR1.5).
    unavailable_reason: str | None
    question: QuestionOut | None
    follow_up: FollowUpOut | None
    next_target: TargetOut | None
    answered_count: int
    skipped_count: int
    declined_count: int
    answer_format: str
    # Захват клавиатурного почерка. Включается только флагом на сервере.
    keystroke_capture: bool
    feedback_reasons: list[ReasonOut]
