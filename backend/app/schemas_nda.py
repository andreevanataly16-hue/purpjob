"""Схемы модуля 5. Структура ответов повторяет §4 FRD."""

from datetime import datetime

from pydantic import BaseModel, Field


class CaseIn(BaseModel):
    """Новый случай подтверждения под NDA."""

    competency_id: str = Field(min_length=1, max_length=60)
    statement_id: str | None = None


class MethodIn(BaseModel):
    method: str = Field(min_length=1, max_length=20)


class BlindWitnessAnswerIn(BaseModel):
    """Ответ всегда свободным текстом - как и в модуле 4."""

    text: str = Field(min_length=1, max_length=20000)


class NodePlacementIn(BaseModel):
    node_id: str = Field(min_length=1, max_length=20)
    order: int = Field(ge=1, le=50)
    role_ru: str = Field(default="", max_length=200)


class MirrorSolutionIn(BaseModel):
    """Обе части обязательны: одни расставленные узлы ничего не подтверждают."""

    node_arrangement: list[NodePlacementIn] = Field(min_length=1)
    logic_explanation: str = Field(min_length=1, max_length=20000)


class DeclineIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


# --- выход ----------------------------------------------------------------


class DisclaimerOut(BaseModel):
    """Дисклеймер (§3). Пометка о юридической проверке видна в продукте."""

    intro_ru: str
    allowed_ru: list[str]
    never_asked_ru: list[str]
    legal_review_note_ru: str


class MethodOut(BaseModel):
    value: str
    label_ru: str
    description_ru: str
    available: bool
    unavailable_reason_ru: str | None


class BlindWitnessQuestionOut(BaseModel):
    id: str
    position: int
    prompt_ru: str
    reason_ru: str
    answer: str | None
    follow_up_ru: str | None
    follow_up_reason_ru: str | None
    follow_up_answer: str | None


class MirrorNodeOut(BaseModel):
    id: str
    label_ru: str


class MirrorScenarioOut(BaseModel):
    id: str
    title_ru: str
    instructions_ru: str
    framing_ru: str
    nodes: list[MirrorNodeOut]


class MirrorSolutionOut(BaseModel):
    scenario: MirrorScenarioOut
    node_arrangement: list[NodePlacementIn]
    logic_explanation: str | None
    follow_up_ru: str | None
    follow_up_reason_ru: str | None
    follow_up_answer: str | None
    status: str


class CaseOut(BaseModel):
    id: str
    competency_id: str
    competency_name_ru: str
    origin: str
    status: str
    status_ru: str
    suggested_method: str
    chosen_method: str | None
    methods: list[MethodOut]
    disclaimer_acknowledged: bool
    switch_count: int
    blind_witness: list[BlindWitnessQuestionOut]
    mirror_task: MirrorSolutionOut | None
    created_at: datetime


class NDAOut(BaseModel):
    disclaimer: DisclaimerOut
    cases: list[CaseOut]
    active_case_id: str | None
