"""Ручные правки модератора как отдельный слой поверх расчётов (модуль 7).

Почему слой, а не правка данных. Модули 3 и 6 ничего не хранят: и статус
компетенции, и балл Trust считаются заново на каждый запрос. Значит, «поправить
статус» нельзя записав его куда-то в модуль 3 - следующий же пересчёт вернул бы
прежнее. Поэтому правка живёт своей записью (`ModeratorOverride`) и
накладывается на результат расчёта в самом конце.

Побочная выгода ровно та, ради которой существует модуль: изменить вывод в
обход журнала невозможно физически. Расчёт не знает про модератора, а модератор
не трогает расчёт - между ними одна проверяемая запись с обязательной причиной
(FR-Gov.2).

Ниже - единственное место в продукте, где значение может уменьшиться. Это не
исключение из правила модуля 6 «только сложение»: то правило про действия
кандидата, и оно в силе. Здесь решение принимает человек, письменно и под
запись; отсутствие такой возможности означало бы, что ошибочно завышенный вывод
исправить нельзя.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ModeratorOverride, User

# --- что вообще можно поправить (§4.4) ------------------------------------

TARGET_PROF_STATUS = "prof_competency_status"
TARGET_TRUST_COMPONENT = "trust_component_score"
TARGET_CONTRADICTION = "contradiction_case_resolution"

TARGET_TYPES = (TARGET_PROF_STATUS, TARGET_TRUST_COMPONENT, TARGET_CONTRADICTION)

TARGET_TYPE_RU = {
    TARGET_PROF_STATUS: "Статус компетенции в PROF.индексе",
    TARGET_TRUST_COMPONENT: "Балл компонента Trust Score",
    TARGET_CONTRADICTION: "Разбор нестыковки",
}

NOTE_PREFIX_RU = "Значение изменено модератором вручную."


def for_user(db: Session, user: User) -> list[ModeratorOverride]:
    """Все правки кандидата в порядке применения."""
    return list(
        db.scalars(
            select(ModeratorOverride)
            .where(ModeratorOverride.user_id == user.id)
            .order_by(ModeratorOverride.id)
        )
    )


def latest(overrides: list[ModeratorOverride], target_type: str, target_id: str):
    """Последняя по времени правка конкретного поля конкретного объекта.

    Правок одного поля может быть несколько: модератор ошибся, потом поправил.
    Действует последняя, но предыдущие остаются в журнале - в этом и смысл.
    """
    found = [
        item
        for item in overrides
        if item.target_type == target_type and item.target_id == target_id
    ]
    return found[-1] if found else None


def note_ru(override: ModeratorOverride) -> str:
    """Текст, который видит кандидат рядом с изменённым значением.

    Правка без объяснения на экране - тот же чёрный ящик, что и балл без
    объяснения; разница только в том, что за ним человек, а не алгоритм.
    """
    return (
        f"{NOTE_PREFIX_RU} Было: {override.previous_value}, стало: {override.new_value}. "
        f"Причина: {override.rationale_ru}"
    )
