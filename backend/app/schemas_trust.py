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

    # Измерен ли компонент вообще. Поле обязательное: `score` без него
    # неоднозначен - ноль означает и «посмотрели, не засчитали», и «смотреть
    # было нечем», а это принципиально разные вещи.
    measured: bool

    # Модуль 7: точка входа в объяснение и след ручной правки.
    explanation_id: str = ""
    moderator_note_ru: str | None = None


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


class TrustTraceOut(BaseModel):
    """След ручной правки балла (FR5.4 модуля 7).

    Версия снимка растёт от каждой такой правки, и от неё можно дойти до
    записи журнала, которая её вызвала: «балл улучшился» без адреса - ровно
    тот чёрный ящик, который модуль 7 и закрывает."""

    component_id: str
    previous_value: str
    new_value: str
    rationale_ru: str
    dispute_case_id: str
    history_entry_id: str | None
    applied_at: datetime


class TrustOut(BaseModel):
    overall_score: int = Field(ge=0, le=100)
    # Рассчитан ли балл вообще. Когда ни один компонент не измерен, показывать
    # ноль нельзя: это читается как «всё проверили, доверия нет», хотя
    # проверять было нечего.
    overall_measured: bool
    computed_at: datetime
    version: int = Field(ge=1)
    legend_ru: str
    components: list[ComponentOut]
    next_actions: list[NextActionOut]
    findings: list[FindingOut]
    contradictions: list[ContradictionOut]
    moderation_trace: list[TrustTraceOut] = Field(default_factory=list)
