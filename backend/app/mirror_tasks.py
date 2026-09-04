"""Сценарии зеркальных задач (модуль 5).

Как и эталонные профили модуля 3, это курируемые данные рядом с кодом, а не
таблица в базе: набор небольшой, собран руками и правится в JSON.

Покрытие намеренно неполное. Если под компетенцию сценария нет, зеркальная
задача по ней не предлагается вовсе (FR2.1) - придумывать абстрактную
головоломку «лишь бы было» модуль не имеет права.

Файлы проверяются при импорте: сценарий не может ссылаться на несуществующую
компетенцию эталона и не может просить то, чего в этом модуле просить нельзя -
название клиента, точные цифры, файл (FR1.3).
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.reference import PROFILES

SEED_DIR = Path(__file__).resolve().parent / "seed" / "mirror_tasks"

# Ничего из этого сценарий спрашивать не может - проверяется при импорте.
_FORBIDDEN = (
    re.compile(r"назван\w* клиент", re.IGNORECASE),
    re.compile(r"имя клиент", re.IGNORECASE),
    re.compile(r"назван\w* компани", re.IGNORECASE),
    re.compile(r"приложите файл", re.IGNORECASE),
    re.compile(r"загрузите", re.IGNORECASE),
    re.compile(r"выручк", re.IGNORECASE),
    re.compile(r"оборот компании", re.IGNORECASE),
)


@dataclass(frozen=True)
class MirrorNode:
    id: str
    label_ru: str


@dataclass(frozen=True)
class MirrorTaskScenario:
    id: str
    competency_id: str
    title_ru: str
    instructions_ru: str
    nodes: tuple[MirrorNode, ...]


def _known_competencies() -> set[str]:
    return {
        competency.competency_id
        for profile in PROFILES.values()
        for competency in profile.competencies
    }


def _load(path: Path, known: set[str]) -> list[MirrorTaskScenario]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    scenarios: list[MirrorTaskScenario] = []

    for item in raw["scenarios"]:
        if item["competency_id"] not in known:
            raise ValueError(
                f"{path.name}: сценарий {item['id']} ссылается на компетенцию "
                f"{item['competency_id']}, которой нет в эталонных профилях."
            )

        text = item["instructions_ru"] + " " + item["title_ru"]
        for pattern in _FORBIDDEN:
            if pattern.search(text):
                raise ValueError(
                    f"{path.name}: сценарий {item['id']} просит то, чего модуль 5 "
                    f"просить не может ({pattern.pattern})."
                )

        if len(item["nodes"]) < 3:
            raise ValueError(f"{path.name}: в сценарии {item['id']} слишком мало узлов.")

        scenarios.append(
            MirrorTaskScenario(
                id=item["id"],
                competency_id=item["competency_id"],
                title_ru=item["title_ru"],
                instructions_ru=item["instructions_ru"],
                nodes=tuple(MirrorNode(n["id"], n["label_ru"]) for n in item["nodes"]),
            )
        )

    return scenarios


_known = _known_competencies()
SCENARIOS: tuple[MirrorTaskScenario, ...] = tuple(
    scenario for path in sorted(SEED_DIR.glob("*.json")) for scenario in _load(path, _known)
)

BY_COMPETENCY: dict[str, list[MirrorTaskScenario]] = {}
for _scenario in SCENARIOS:
    BY_COMPETENCY.setdefault(_scenario.competency_id, []).append(_scenario)

BY_ID: dict[str, MirrorTaskScenario] = {scenario.id: scenario for scenario in SCENARIOS}


def scenario_for(competency_id: str) -> MirrorTaskScenario | None:
    """Сценарий под компетенцию или None, если его нет.

    None здесь - штатный ответ, а не ошибка: зеркальная задача просто не
    попадёт в список доступных способов.
    """
    options = BY_COMPETENCY.get(competency_id)
    return options[0] if options else None
