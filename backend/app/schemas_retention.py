"""Схемы модуля 11.

Счётчик отправленных уведомлений здесь есть только рядом с числом сработавших:
показ сам по себе ничего не доказывает, и выносить его отдельной «метрикой
успеха» нельзя (§6 FR-Constraint.2).
"""

from datetime import datetime

from pydantic import BaseModel, Field


class VacancyTriggerOut(BaseModel):
    id: str
    vacancy_id: str
    vacancy_title_ru: str
    company_label: str

    # Совпадение на момент срабатывания и сейчас - разные числа, и это честно
    # показывается: обещание в уведомлении не должно задним числом «уточняться».
    match_score_at_detection: int = Field(ge=0, le=100)
    match_score_now: int = Field(ge=0, le=100)

    explanation_id: str | None
    explanation_ru: str
    status: str
    created_at: datetime


class CrossVacancyEventOut(BaseModel):
    id: str
    description_ru: str
    occurred_at: datetime


class RetentionStatsOut(BaseModel):
    sent: int
    acted_upon: int
    acted_upon_ratio: float | None


class RetentionOut(BaseModel):
    note_ru: str
    min_match_score_to_notify: int
    triggers: list[VacancyTriggerOut]
    cross_vacancy_events: list[CrossVacancyEventOut]
    stats: RetentionStatsOut
