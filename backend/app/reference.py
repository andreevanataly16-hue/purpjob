"""Эталонные профили PROF.индекса.

Профили лежат рядом в JSON (`seed/reference_profiles`) и версионируются вместе
с кодом - так и требует §8 FRD: это курируемые данные, а не миграция и не
админка. Правка весов не требует изменения кода.

Файлы проверяются при импорте: если сумма весов уехала или в профиле опечатка
в ключе компетенции модуля 2, приложение не поднимется. Молча считать индекс по
сломанному эталону хуже, чем не запуститься.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from app.taxonomy import BY_KEY

SEED_DIR = Path(__file__).resolve().parent / "seed" / "reference_profiles"

# MVP зафиксирован на одном сегменте и двух уровнях (FR1.1).
SEGMENT = "Backend/Fullstack (Python/Go)"
LEVELS = ("Middle", "Senior")

CATEGORIES = ("hard_skill", "task_complexity")
DEPTHS = ("basic", "working", "deep")

# Насколько сумма весов может отличаться от 1.0 - на погрешность float.
_WEIGHT_TOLERANCE = 1e-9


@dataclass(frozen=True)
class ReferenceCompetency:
    competency_id: str
    name_ru: str
    short_ru: str
    category: str
    weight: float
    required_depth: str
    taxonomy_keys: tuple[str, ...]


@dataclass(frozen=True)
class ReferenceProfile:
    id: str
    segment: str
    level: str
    competencies: tuple[ReferenceCompetency, ...]


def _load(path: Path) -> ReferenceProfile:
    raw = json.loads(path.read_text(encoding="utf-8"))

    if raw["level"] not in LEVELS:
        raise ValueError(f"{path.name}: уровень {raw['level']} вне MVP-набора {LEVELS}.")

    competencies: list[ReferenceCompetency] = []
    for item in raw["competencies"]:
        if item["category"] not in CATEGORIES:
            raise ValueError(f"{path.name}: неизвестная категория {item['category']}.")
        if item["required_depth"] not in DEPTHS:
            raise ValueError(f"{path.name}: неизвестная глубина {item['required_depth']}.")

        unknown = [key for key in item["taxonomy_keys"] if key not in BY_KEY]
        if unknown:
            raise ValueError(
                f"{path.name}: компетенция {item['competency_id']} ссылается на "
                f"несуществующие ключи таксономии модуля 2: {unknown}."
            )

        competencies.append(
            ReferenceCompetency(
                competency_id=item["competency_id"],
                name_ru=item["name_ru"],
                short_ru=item["short_ru"],
                category=item["category"],
                weight=float(item["weight"]),
                required_depth=item["required_depth"],
                taxonomy_keys=tuple(item["taxonomy_keys"]),
            )
        )

    total = sum(c.weight for c in competencies)
    if abs(total - 1.0) > _WEIGHT_TOLERANCE:
        raise ValueError(
            f"{path.name}: сумма весов {total}, а по договорённости в самом файле "
            "должна быть 1.0 по всему профилю."
        )

    return ReferenceProfile(
        id=raw["id"],
        segment=raw["segment"],
        level=raw["level"],
        competencies=tuple(competencies),
    )


PROFILES: dict[str, ReferenceProfile] = {
    profile.level: profile for profile in (_load(path) for path in sorted(SEED_DIR.glob("*.json")))
}

_missing = [level for level in LEVELS if level not in PROFILES]
if _missing:
    raise ValueError(f"Не найдены эталонные профили для уровней: {_missing}.")


def get_profile(level: str) -> ReferenceProfile:
    return PROFILES[level]
