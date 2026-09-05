"""Набор синтетических кандидатов для рекрутерской стороны (модуль 12).

Настоящих зарегистрированных кандидатов на этой фазе нет, поэтому пул -
рукописный JSON, как эталоны модуля 3, сценарии модуля 5 и вакансии модуля 10.

Важное отличие от «просто мок-данных»: **баллы здесь не записаны.** В наборе
лежат только те же исходные вещи, что есть у живого кандидата - компетенции,
доказательства, ответы на вопросы, - а статусы, PROF.индекс, Trust Score и
совпадение с вакансией считают те же самые движки модулей 2/3/6/10. Записанные
руками цифры разошлись бы с настоящим расчётом в первую же неделю, и
рекрутерский экран показывал бы то, чего в продукте нет.

Жёсткая граница приватности. Кандидат в режиме «Инкогнито» не должен быть
доступен рекрутеру **структурно**, а не косметически: `visible_pool()` -
единственный вход в набор для всего модуля 12, и скрытые записи в него не
попадают. Отфильтровать их «потом, на экране» - это ровно тот способ однажды
показать лишнее.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from app.enrichment import DECLINED, TYPE_FILE, TYPE_LINK, EvidenceFacts, compute_status
from app.prof import StatementView, compute_snapshot
from app.reference import LEVELS, get_profile
from app.trust import (
    ComponentScore,
    EvidenceFacts as TrustEvidenceFacts,
    ProbeFacts,
    authenticity,
    consistency,
    overall,
    understanding,
)

SEED_DIR = Path(__file__).parent / "seed" / "candidates"

VISIBLE = "visible"
HIDDEN = "hidden"


@dataclass(frozen=True)
class SeedEvidence:
    type: str
    source_category: str | None
    status: str


@dataclass(frozen=True)
class SeedStatement:
    skill_name: str
    skill_name_ru: str
    evidence: tuple[SeedEvidence, ...]


@dataclass(frozen=True)
class SeedCandidate:
    id: str
    display_name: str
    photo_label: str
    visibility_mode: str
    consent_for_recruiter_view: bool
    levels: tuple[str, ...]
    statements: tuple[SeedStatement, ...]
    probe_answers: tuple[ProbeFacts, ...]
    nda_confirmations: tuple[SeedEvidence, ...]


def _fail(candidate_id: str, problem: str) -> None:
    raise ValueError(f"Кандидат {candidate_id}: {problem}")


def _load() -> list[SeedCandidate]:
    found: list[SeedCandidate] = []
    seen: set[str] = set()

    for path in sorted(SEED_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for raw in data["candidates"]:
            candidate_id = raw["id"]
            if candidate_id in seen:
                _fail(candidate_id, "такой идентификатор уже есть в наборе")
            seen.add(candidate_id)

            mode = raw["visibility_state"]["mode"]
            if mode not in (VISIBLE, HIDDEN):
                _fail(candidate_id, f"неизвестный режим видимости {mode}")
            for level in raw["levels"]:
                if level not in LEVELS:
                    _fail(candidate_id, f"уровень {level} вне библиотеки эталонов")
            if not raw["statements"]:
                _fail(candidate_id, "нет ни одной компетенции")

            statements = tuple(
                SeedStatement(
                    skill_name=item["skill_name"],
                    skill_name_ru=item["skill_name_ru"],
                    evidence=tuple(
                        SeedEvidence(
                            type=e["type"],
                            source_category=e["source_category"],
                            status=e["status"],
                        )
                        for e in item["evidence"]
                    ),
                )
                for item in raw["statements"]
            )

            found.append(
                SeedCandidate(
                    id=candidate_id,
                    display_name=raw["display_name"],
                    photo_label=raw["photo_label"],
                    visibility_mode=mode,
                    consent_for_recruiter_view=raw["consent_for_recruiter_view"],
                    levels=tuple(raw["levels"]),
                    statements=statements,
                    probe_answers=tuple(
                        ProbeFacts(
                            answer_id=f"{candidate_id}_a{index}",
                            competency_id=item["competency_id"],
                            understanding_signal=item["understanding_signal"],
                            paste_attempts_blocked=item["paste_attempts_blocked"],
                            had_follow_up=item["had_follow_up"],
                            resolved_after_follow_up=item["resolved_after_follow_up"],
                        )
                        for index, item in enumerate(raw["probe_answers"], start=1)
                    ),
                    nda_confirmations=tuple(
                        SeedEvidence(
                            type=item["type"],
                            source_category=item["source_category"],
                            status=item["status"],
                        )
                        for item in raw["nda_confirmations"]
                    ),
                )
            )

    if not found:
        raise ValueError("Пул кандидатов пуст - рекрутерскую сторону не на чем показать.")
    return found


ALL: list[SeedCandidate] = _load()


def visible_pool() -> list[SeedCandidate]:
    """Единственный вход в набор для модуля 12.

    Скрытый профиль сюда не попадает вообще. Не «отфильтруем на экране» -
    его просто нет в наборе, с которым работает рекрутерская сторона.
    """
    return [item for item in ALL if item.visibility_mode == VISIBLE]


def get_visible(candidate_id: str) -> SeedCandidate | None:
    return next((item for item in visible_pool() if item.id == candidate_id), None)


# --- расчёт теми же движками, что и для живого профиля --------------------


def statement_views(candidate: SeedCandidate) -> list[StatementView]:
    """Компетенции кандидата со статусами по правилу §3.4 модуля 2."""
    views: list[StatementView] = []
    for index, item in enumerate(candidate.statements, start=1):
        view = compute_status(
            [
                EvidenceFacts(type=e.type, source_category=e.source_category, status=e.status)
                for e in item.evidence
            ]
        )
        active = [e for e in item.evidence if e.status != DECLINED]
        views.append(
            StatementView(
                id=f"{candidate.id}_stmt_{index:03d}",
                skill_name=item.skill_name,
                skill_name_ru=item.skill_name_ru,
                status=view.status,
                reason=view.reason,
                artifact_count=sum(1 for e in active if e.type in (TYPE_LINK, TYPE_FILE)),
            )
        )
    return views


def prof_snapshots(candidate: SeedCandidate) -> list[dict]:
    views = statement_views(candidate)
    return [compute_snapshot(get_profile(level), views) for level in candidate.levels]


def trust_components(candidate: SeedCandidate) -> list[ComponentScore]:
    """Trust Score теми же тремя функциями модуля 6, без второй формулы."""
    evidence: list[TrustEvidenceFacts] = []
    for index, item in enumerate(candidate.statements, start=1):
        statement_id = f"{candidate.id}_stmt_{index:03d}"
        for position, entry in enumerate(item.evidence, start=1):
            evidence.append(
                TrustEvidenceFacts(
                    id=f"{statement_id}_ev_{position}",
                    type=entry.type,
                    source_category=entry.source_category,
                    status=entry.status,
                    statement_ids=(statement_id,),
                )
            )

    nda = [
        TrustEvidenceFacts(
            id=f"{candidate.id}_nda_{index}",
            type=item.type,
            source_category=item.source_category,
            status=item.status,
            statement_ids=(),
        )
        for index, item in enumerate(candidate.nda_confirmations, start=1)
    ]

    probes = list(candidate.probe_answers)
    return [
        authenticity(probes),
        understanding(probes, nda),
        # Нестыковок и открытых находок у синтетического профиля нет: набор
        # собран согласованным, а отклонённые находки не хранятся нигде.
        consistency(evidence, 0, 0, 0),
    ]


def trust_overall(candidate: SeedCandidate) -> int:
    return overall(trust_components(candidate))

