"""Схемы модуля 15.

Поля `raw_text` в запросах к серверу есть ровно одно - для текста вакансии.
Для резюме такого поля нет и быть не должно: его разбор целиком в браузере.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class TierOut(BaseModel):
    tier: str
    label_ru: str
    note_ru: str


class PluginInfoOut(BaseModel):
    privacy_ru: str
    # Формулировка из FRD, менять нельзя: это заявленная позиция продукта.
    honesty_ru: str
    lens_ru: str
    tiers: list[TierOut]


class RequirementOut(BaseModel):
    competency_id: str | None
    taxonomy_key: str | None
    label_ru: str
    criticality: str
    criticality_ru: str
    # Подсказка, а не сгенерированный вопрос: живой вопрос задаёт модуль 4.
    evidence_hint_ru: str
    in_reference_profile: bool
    # Фрагмент текста, из которого требование извлечено. Разбор должен быть
    # проверяемым: рекрутер видит основание, а не только вывод — то же правило,
    # что и везде в продукте.
    matched_text: str


class ExtractionOut(BaseModel):
    requirements: list[RequirementOut]
    unknown_count: int
    unknown_note_ru: str


class LookupIn(BaseModel):
    """Единственное, что уходит на сервер до согласия кандидата."""

    contact_hash: str = Field(min_length=71, max_length=71)


class LookupOut(BaseModel):
    result: str
    candidate_id: str | None
    tier: str
    tier_label_ru: str
    tier_note_ru: str


class InviteIn(BaseModel):
    note_ru: str | None = Field(default=None, max_length=1000)


class InviteOut(BaseModel):
    id: str
    invite_link: str
    status: str
    created_at: datetime
    message_ru: str
    send_note_ru: str
