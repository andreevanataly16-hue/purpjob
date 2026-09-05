"""Схемы кандидатской стороны модуля 13."""

from pydantic import BaseModel


class RevealSettingsIn(BaseModel):
    """Оба поля необязательны: настройки меняются по одной, а не вместе."""

    allow_immediate_identity_reveal: bool | None = None
    consent_for_recruiter_view: bool | None = None
