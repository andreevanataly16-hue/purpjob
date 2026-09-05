"""Схемы модуля 14. Структура повторяет §4 FRD.

Сводки (`CalibrationInsight`, `TrustAccuracyMetric`) отдельными записями не
хранятся: они считаются из отзывов на чтение. Отдельный накопительный счётчик
однажды разошёлся бы с тем, из чего он якобы посчитан.
"""

from datetime import datetime

from pydantic import BaseModel, Field


# --- сторона рекрутера ----------------------------------------------------


class ComponentVerdictIn(BaseModel):
    """Отметка на конкретном выводе, адресованная его же идентификатором."""

    explanation_id: str = Field(min_length=1, max_length=160)
    subject_type: str = Field(min_length=1, max_length=40)
    subject_id: str = Field(min_length=1, max_length=120)
    verdict: str = Field(min_length=1, max_length=20)
    comment_ru: str | None = Field(default=None, max_length=2000)


class FeedbackIn(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=60)
    vacancy_id: str | None = Field(default=None, max_length=60)
    # Единственное обязательное поле: чем тяжелее форма, тем реже её заполняют,
    # а без базового действия вся калибровка остаётся без данных (FR1.2).
    relevance_outcome: str = Field(min_length=1, max_length=30)
    component_feedback: list[ComponentVerdictIn] = Field(default_factory=list)
    free_text_comment: str | None = Field(default=None, max_length=4000)


class FeedbackOut(BaseModel):
    id: str
    candidate_id: str
    vacancy_id: str | None
    relevance_outcome: str
    relevance_outcome_ru: str
    trust_score_at_feedback: int
    prof_score_at_feedback: int
    free_text_comment: str | None
    component_count: int
    submitted_at: datetime


class FeedbackStateOut(BaseModel):
    """То, что видит рекрутер на карточке кандидата."""

    prompt_ru: str
    component_prompt_ru: str
    options: list[dict]
    verdicts: list[dict]
    note_ru: str
    submitted: FeedbackOut | None
    component_verdicts: dict[str, str]


# --- сторона оператора ----------------------------------------------------


class InsightOut(BaseModel):
    subject_type: str
    subject_type_ru: str
    subject_id: str
    sample_size: int
    misleading_rate: float
    useful_rate: float
    # Флаг требует и выборки, и доли: один комментарий закономерностью не бывает.
    flagged_for_review: bool


class AccuracyOut(BaseModel):
    period_label: str
    total_feedback_count: int
    comparable_count: int
    matching_count: int
    trust_accuracy_pct: int | None


class ConstantOut(BaseModel):
    constant_ref: str
    label_ru: str
    current_value: str


class ChangeLogOut(BaseModel):
    id: str
    constant_ref: str
    label_ru: str
    previous_value: str
    new_value: str
    rationale_ru: str
    based_on_feedback_count: int
    trust_accuracy_before: int | None
    applied_at: datetime


class ChangeIn(BaseModel):
    constant_ref: str = Field(min_length=1, max_length=120)
    new_value: str = Field(min_length=1, max_length=200)
    # Обязательно на уровне схемы, а не «по договорённости в форме» (FR3.3).
    rationale_ru: str = Field(min_length=1, max_length=4000)


class BatchIn(BaseModel):
    selection_criteria: str = Field(min_length=1, max_length=30)
    size: int = Field(default=3, ge=1, le=20)


class BatchOut(BaseModel):
    id: str
    selection_criteria: str
    selection_ru: str
    candidate_ids: list[str]
    dispute_case_ids: list[str]
    created_at: datetime
    # Сводка по всей партии - то, чего в модуле 7 нет: он разбирает по одному.
    pattern_ru: str
    overridden_by_subject_type: dict[str, int]


class CalibrationOut(BaseModel):
    not_production_safe_ru: str
    note_ru: str
    accuracy: AccuracyOut
    insights: list[InsightOut]
    constants: list[ConstantOut]
    changes: list[ChangeLogOut]
    batches: list[BatchOut]
    selection_options: list[dict]
