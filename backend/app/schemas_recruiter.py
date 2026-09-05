"""Схемы модуля 12.

Полей «показать скрытых» и «журнал просмотров» здесь нет: первого не должно
существовать, второе нужно вводить вместе с настоящими правами доступа, а не
раньше.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class VacancyOptionOut(BaseModel):
    id: str
    title_ru: str
    stated_level: str


class CandidateCardOut(BaseModel):
    candidate_id: str
    display_name: str
    photo_label: str
    levels: list[str]
    # Модуль 13: на первом этапе вместо имени стоит стабильная метка, а не
    # пустое место — видно, что скрыто нарочно.
    identity_revealed: bool = True
    prof_index: int = Field(ge=0, le=100)
    prof_level: str
    trust_score: int = Field(ge=0, le=100)
    match_score: int = Field(ge=0, le=100)
    covered_count: int
    uncovered_count: int
    consent_for_recruiter_view: bool


class ProfComponentOut(BaseModel):
    competency_id: str
    name_ru: str
    status: str
    reason: str
    weight: float
    # Модуль 14: отметка «полезно / ввело в заблуждение» цепляется к тому же
    # объяснению, что видит рекрутер, а не к пересобранному описанию.
    explanation_id: str = ""


class RadarPointOut(BaseModel):
    competency_id: str
    short_ru: str
    candidate_value: float
    reference_value: float


class TrustComponentOut(BaseModel):
    component_id: str
    name_ru: str
    score: int = Field(ge=0, le=100)
    explanation_ru: str
    explanation_id: str
    # Согласие управляет только глубиной: сами доказательства или только вывод.
    evidence_visible: bool
    evidence_refs: list[str]


class RequirementOut(BaseModel):
    requirement_id: str
    label_ru: str
    criticality_ru: str
    status: str
    explanation_ru: str


class CandidateDetailOut(CandidateCardOut):
    vacancy_id: str
    vacancy_title_ru: str
    current_stage: str
    stage_note_ru: str
    advance_label_ru: str
    contact_label_ru: str
    contacts_visible: bool
    contact_note_ru: str
    prof_components: list[ProfComponentOut]
    radar_points: list[RadarPointOut]
    trust_components: list[TrustComponentOut]
    consent_note_ru: str
    # Доказательство, полученное альтернативным способом, отмечается нейтрально
    # и не выглядит хуже прочих (FR3.4).
    nda_note_ru: str | None
    covered: list[RequirementOut]
    uncovered: list[RequirementOut]
    unevaluated_clusters: list[str]
    unevaluated_note_ru: str


class SearchOut(BaseModel):
    note_ru: str
    not_production_safe_ru: str
    vacancy_id: str
    vacancy_title_ru: str
    available_vacancies: list[VacancyOptionOut]
    sort_by: str
    candidates: list[CandidateCardOut]
    computed_at: datetime


class CompareOut(BaseModel):
    vacancy_id: str
    vacancy_title_ru: str
    # Одинаковая структура на всех: своих полей у отдельного кандидата нет,
    # иначе сравнивать было бы нечего (FR5.1).
    candidates: list[CandidateDetailOut]


class RecruiterInterestOut(BaseModel):
    """Что кандидат видит про интерес к себе (модуль 13, US3).

    Это прозрачность, а не право вето: этап уже наступивший кандидат не
    отменяет. Отсюда и набор полей — кто, на каком этапе, и просил ли контакты.
    """

    recruiter_label: str
    current_stage: str
    stage_ru: str
    contact_requested: bool
    contact_opt_in: bool
    created_at: datetime


class RevealOut(BaseModel):
    note_ru: str
    opt_out_label_ru: str
    allow_immediate_identity_reveal: bool
    consent_for_recruiter_view: bool
    interests: list[RecruiterInterestOut]
