"""Схемы запросов и ответов модуля 2.

Имена полей повторяют §3.1-3.3 FRD: наружу отдаём ровно ту структуру, которая
описана в спецификации, чтобы фронтенд и будущие модули не переучивались.
"""

from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator

from app.enrichment import SOURCE_CATEGORIES
from app.taxonomy import CATEGORIES

# --- вход -----------------------------------------------------------------


class LinkIn(BaseModel):
    """FR1.1-FR1.2: ссылка на профессиональный источник."""

    # AnyHttpUrl проверяет формат, но никуда не ходит: живой проверки ссылки
    # на этом этапе нет и по FRD не требуется.
    url: AnyHttpUrl
    source_category: str | None = None
    statement_ids: list[str] = Field(default_factory=list)

    @field_validator("source_category")
    @classmethod
    def known_category(cls, value: str | None) -> str | None:
        if value is not None and value not in SOURCE_CATEGORIES:
            raise ValueError("Неизвестный тип источника.")
        return value


class FreeTextIn(BaseModel):
    """FR2.1: описание проекта или кейса в свободной форме."""

    raw_text: str = Field(min_length=1, max_length=20000)


class AcceptedItem(BaseModel):
    """Одна компетенция, которую кандидат оставил после разбора (FR2.3)."""

    skill_name: str | None = None
    skill_name_ru: str = Field(min_length=1, max_length=120)
    category: str = Field(default="Hard Skill")
    excerpt: str = Field(default="", max_length=2000)

    @field_validator("category")
    @classmethod
    def known_category(cls, value: str) -> str:
        if value not in CATEGORIES:
            raise ValueError("Неизвестная категория компетенции.")
        return value


class AcceptIn(BaseModel):
    raw_input_id: str
    items: list[AcceptedItem] = Field(default_factory=list)


class StatementIn(BaseModel):
    """Компетенция, добавленная кандидатом вручную."""

    skill_name_ru: str = Field(min_length=1, max_length=120)
    category: str = Field(default="Hard Skill")

    @field_validator("category")
    @classmethod
    def known_category(cls, value: str) -> str:
        if value not in CATEGORIES:
            raise ValueError("Неизвестная категория компетенции.")
        return value


class BlindWitnessIn(BaseModel):
    """FR4.4: ответ про логику решений вместо самого артефакта."""

    answer: str = Field(min_length=1, max_length=20000)
    statement_ids: list[str] = Field(default_factory=list)


class DeclineIn(BaseModel):
    """Причина всегда необязательна - это правило §3.3, а не UI-послабление."""

    reason: str | None = Field(default=None, max_length=500)


# --- выход ----------------------------------------------------------------


class ParsedItemOut(BaseModel):
    skill_name: str
    skill_name_ru: str
    category: str
    excerpt: str
    confidence: str


class ParseOut(BaseModel):
    raw_input_id: str
    items: list[ParsedItemOut]


class EvidenceOut(BaseModel):
    id: str
    type: str
    source_category: str | None
    url: str | None
    file_ref: str | None
    file_name: str | None
    raw_text: str | None
    nda: bool
    status: str
    linked_statement_ids: list[str]
    created_at: datetime


class StatementOut(BaseModel):
    id: str
    skill_name: str
    skill_name_ru: str
    category: str
    source_of_claim: str
    status: str
    status_reason: str
    next_action: str
    next_action_kind: str
    evidence_ids: list[str]
    declined: bool
    created_at: datetime
    updated_at: datetime


class DeclineOut(BaseModel):
    id: str
    target_type: str
    target_id: str
    reason: str | None
    timestamp: datetime


class ProfileOut(BaseModel):
    """Весь профиль одним ответом: страница перерисовывается из него целиком."""

    statements: list[StatementOut]
    evidence: list[EvidenceOut]
    declines: list[DeclineOut]
