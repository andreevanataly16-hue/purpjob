"""Схемы модуля 3. Структура ответа повторяет §4 FRD."""

from datetime import datetime

from pydantic import BaseModel, Field


class LevelIn(BaseModel):
    level: str = Field(min_length=1, max_length=40)


class VisibilityIn(BaseModel):
    mode: str = Field(min_length=1, max_length=20)


class VisibilityOut(BaseModel):
    mode: str
    changed_at: datetime


class ComponentOut(BaseModel):
    """`CompetencyResult` из §4.2 плюс объяснение статуса - без него показывать
    компетенцию нельзя (FR2.2)."""

    competency_id: str
    name_ru: str
    short_ru: str
    category: str
    weight: float
    required_depth: str
    status: str
    reason: str
    statement_ids: list[str]
    evidence_count: int
    score_contribution: float
    heuristic_applied: bool
    suggested_skill_key: str
    suggested_skill_ru: str

    # Модуль 7: единая точка «Почему такой вывод?» рядом с каждым статусом
    # (FR1.3) и след ручной правки, если она была (FR-Gov.2).
    explanation_id: str = ""
    moderator_note_ru: str | None = None

    # Модуль 8: насколько компетенция считается сейчас. Единица - полный вес.
    market_weight_multiplier: float = 1.0


class RadarPointOut(BaseModel):
    competency_id: str
    short_ru: str
    candidate_value: float
    reference_value: float


class SnapshotOut(BaseModel):
    """`PROFIndexSnapshot` из §4.3. `computed_at` не храним: снимок считается
    на каждый запрос, дата в нём - это дата ответа."""

    level: str
    segment: str
    reference_profile_id: str
    overall_score: int
    components: list[ComponentOut]
    white_spots: list[str]
    radar_points: list[RadarPointOut]


class ProfOut(BaseModel):
    segment: str
    available_levels: list[str]
    max_roles: int
    snapshots: list[SnapshotOut]
    visibility: VisibilityOut
