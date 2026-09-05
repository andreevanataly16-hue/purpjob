"""Схемы модуля 9.

Полей получателя, статуса доставки и отслеживания здесь нет намеренно (§7 FRD):
их присутствие «на всякий случай» само по себе было бы первым шагом к рассылке,
которую этот модуль запрещает.
"""

from pydantic import BaseModel, Field


class ExportOptionsIn(BaseModel):
    format: str = Field(default="pdf", max_length=10)
    # Решение принимается на этот экспорт и никак не связано с режимом
    # видимости профиля: отправить документ самому себе и опубликовать профиль
    # на площадке - разные решения (FR4.4).
    include_contacts: bool = True


class SkillOut(BaseModel):
    name_ru: str
    status_ru: str


class ProjectOut(BaseModel):
    name_ru: str
    text: str


class ExportPreviewOut(BaseModel):
    format: str
    note_ru: str
    # Кириллице в PDF нужен встроенный шрифт: если его нет, честно говорим об
    # этом до нажатия кнопки, а не роняем запрос.
    font_available: bool
    font_hint_ru: str

    role_ru: str
    segment_ru: str
    prof_score: int
    trust_score: int
    trust_legend_ru: str
    skills: list[SkillOut]
    projects: list[ProjectOut]
    contact_email: str | None
