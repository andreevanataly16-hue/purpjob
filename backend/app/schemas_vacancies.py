"""Схемы модуля 10. Структура ответа повторяет §4 FRD.

Полей отклика, счётчика просмотров и «осталось 2 дня» здесь нет намеренно:
модуль устроен вокруг связи профиля с одной возможностью, а не вокруг объёма.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class VacancyCardOut(BaseModel):
    id: str
    title_ru: str
    company_label: str
    stated_level: str
    role_breadth: str
    role_breadth_ru: str
    industry_context: str | None
    ai_leverage_flag: bool | None
    source_channels: list[str]
    created_at: datetime

    overall_match_score: int = Field(ge=0, le=100)
    covered_count: int
    uncovered_count: int
    mandatory_gaps: int


class RequirementOut(BaseModel):
    requirement_id: str
    label_ru: str
    criticality: str
    criticality_ru: str
    status: str
    # Голого процента и голой метки быть не должно нигде (FR3.2).
    explanation_ru: str
    recommended_action: str | None
    competency_id: str | None


class ClusterScoreOut(BaseModel):
    cluster_label_ru: str
    score: int = Field(ge=0, le=100)


class VacancyDetailOut(VacancyCardOut):
    note_ru: str
    covered: list[RequirementOut]
    uncovered: list[RequirementOut]
    unevaluated_clusters: list[str]
    unevaluated_note_ru: str
    cluster_scores: list[ClusterScoreOut]


class VacanciesOut(BaseModel):
    note_ru: str
    levels: list[str]
    vacancies: list[VacancyCardOut]
    computed_at: datetime
