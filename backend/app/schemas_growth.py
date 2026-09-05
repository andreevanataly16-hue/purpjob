"""Схемы модуля 8. Структура ответа повторяет §4 FRD.

Полей доставки и получателей здесь нет и не будет: этот модуль ничего никуда
не отправляет, он только показывает кандидату его собственную историю.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class GrowthEventOut(BaseModel):
    id: str
    event_type: str
    subject_ref: str
    description_ru: str
    from_value: str | None
    to_value: str | None
    occurred_at: datetime


class GrowthPeriodOut(BaseModel):
    """История сгруппирована по месяцам: сплошная лента событий читается как
    выгрузка из базы, а не как рассказ о росте (FR4.3)."""

    label_ru: str
    events: list[GrowthEventOut]


class FreshnessOut(BaseModel):
    competency_id: str
    name_ru: str
    status: str
    status_ru: str
    # Множитель влияет только на PROF.индекс и никогда на Trust Score (§0 FRD).
    market_weight_multiplier: float = Field(gt=0, le=1)
    last_confirmed_at: datetime
    days_since: int
    days_to_decay: int
    hint_ru: str


class TriggerOut(BaseModel):
    id: str
    trigger_type: str
    related_ref: str
    text_ru: str
    status: str
    created_at: datetime


class GrowthStatsOut(BaseModel):
    """H1b: значимо только `acted_upon`, а не «показали».

    Открытое уведомление ничего не доказывает про накопительную ценность.
    Поэтому доля вернувшихся и что-то сделавших вынесена отдельным числом, а
    просмотры не считаются успехом нигде.
    """

    triggers_sent: int
    triggers_acted_upon: int
    acted_upon_ratio: float | None
    confirmed_competencies: int
    reused_across_roles: int


class GrowthOut(BaseModel):
    note_ru: str
    periods: list[GrowthPeriodOut]
    freshness: list[FreshnessOut]
    triggers: list[TriggerOut]
    stats: GrowthStatsOut
