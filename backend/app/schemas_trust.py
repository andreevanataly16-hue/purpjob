"""Схемы модуля 6. Структура ответа повторяет §4 FRD.

Отрицательных значений в этой модели нет нигде и быть не может: у баллов стоит
ограничение ge=0 на уровне схемы, а не «по договорённости» (§7 FRD).
"""

from datetime import datetime

from pydantic import BaseModel, Field


class FindingResponseIn(BaseModel):
    response: str = Field(min_length=1, max_length=30)


class ResolutionIn(BaseModel):
    path: str = Field(min_length=1, max_length=20)
    explanation_text: str | None = Field(default=None, max_length=4000)
    corrected_value: str | None = Field(default=None, max_length=500)


class ComponentOut(BaseModel):
    component_id: str
    name_ru: str
    score: int = Field(ge=0, le=100)
    # Объяснение обязательно и должно быть проверяемым фактом (FR2.1).
    explanation_ru: str
    contributing_evidence_ids: list[str]
    notes_ru: list[str]


class NextActionOut(BaseModel):
    """Следующее лучшее действие: конкретное, с адресом, а не «улучшите профиль»."""

    component_id: str
    text_ru: str
    target_kind: str
    target_id: str | None
    weight: float


class FindingOut(BaseModel):
    id: str
    finding_text_ru: str
    source_ref: str
    candidate_response: str | None


class ContradictionOut(BaseModel):
    id: str
    check_type: str
    detected_by: str
    severity: str
    detail_ru: str
    statement_id: str | None
    statement_name_ru: str | None
    evidence_id: str | None
    resolution_path: str | None
    explanation_text: str | None
    corrected_value: str | None
    status: str
    visibility_suspended: bool
    created_at: datetime


class TrustOut(BaseModel):
    overall_score: int = Field(ge=0, le=100)
    computed_at: datetime
    version: int = Field(ge=1)
    legend_ru: str
    components: list[ComponentOut]
    next_actions: list[NextActionOut]
    findings: list[FindingOut]
    contradictions: list[ContradictionOut]
