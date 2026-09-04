"""Расчёт PROF.индекса.

Индекс ничего не собирает сам: он читает статусы компетенций из модуля 2 и
проецирует их на эталонный профиль. Данные модуля 2 при этом не меняются -
здесь только чтение (§4 FRD).

Индекс считается на каждый запрос заново (§8 FRD): данных мало, а устаревший
снимок хуже лишнего вычисления.

Что означает число. PROF v0 - это покрытие требований эталона доказательствами,
а не измерение навыка. «Python - 60» читается как «доказательная база по этой
компетенции тянет на 0.6 по текущей модели», а не «кандидат знает Python на
60%». Разница принципиальная: индекс растёт от новых доказательств, а не от
того, что человек стал лучше разбираться.

Требуемая глубина (basic / working / deep) в расчёт не входит вообще: она
задаёт ориентир эталона на радаре. Включать её в формулу коэффициентом «на
глаз» нельзя - глубину нужно калибровать на реальных данных (Гл. 13).
"""

from dataclasses import dataclass, field

from app.enrichment import LIMITED, MEDIUM, NOT_STARTED, STRONG
from app.reference import ReferenceCompetency, ReferenceProfile
from app.taxonomy import BY_KEY

# --- калибруемые константы -----------------------------------------------
#
# Ниже - рабочая гипотеза первого сегмента (Гл. 13 мастер-документа), а не
# проверенная формула. Держатся отдельными именованными константами именно
# для того, чтобы калибровка не требовала правки логики.

# §4.4 FRD: статус компетенции -> вклад в индекс.
STATUS_SCORE: dict[str, float] = {
    NOT_STARTED: 0.0,
    LIMITED: 0.25,
    MEDIUM: 0.6,
    STRONG: 1.0,
}

# Требование эталона -> точка на радаре. В §4.3 FRD reference_value показан как
# 1.0, но тогда все требования выглядят одинаковыми; глубина из §4.1 как раз и
# отличает «нужно базово» от «нужно глубоко».
DEPTH_REFERENCE: dict[str, float] = {
    "basic": 0.4,
    "working": 0.7,
    "deep": 1.0,
}

# FR1.5: эвристика сложности решённых задач. Артефакт (ссылка или файл) плюс
# развёрнутое описание поднимают limited до medium. Это заглушка вместо
# несуществующей модели анализа сложности, а не оценка глубины задачи.
COMPLEXITY_MIN_DESCRIPTION = 200
COMPLEXITY_HEURISTIC_NOTE = (
    "Учтён артефакт с подробным описанием — черновая эвристика сложности, "
    "она ждёт калибровки."
)

# Порядок статусов: чем больше, тем сильнее подтверждено.
_STATUS_RANK = {NOT_STARTED: 0, LIMITED: 1, MEDIUM: 2, STRONG: 3}

# §3.1 FRD: белое пятно - это not_started или limited.
WHITE_SPOT_STATUSES = (NOT_STARTED, LIMITED)


@dataclass(frozen=True)
class StatementView:
    """Компетенция кандидата из модуля 2 в том виде, в каком её читает индекс."""

    id: str
    skill_name: str
    skill_name_ru: str
    status: str
    reason: str
    artifact_count: int = 0
    longest_text: int = 0


@dataclass
class CompetencyResult:
    """§4.2 FRD плюс то, без чего требование FR2.2 не выполнить: объяснение."""

    competency_id: str
    name_ru: str
    short_ru: str
    category: str
    weight: float
    required_depth: str
    status: str
    reason: str
    statement_ids: list[str] = field(default_factory=list)
    evidence_count: int = 0
    score_contribution: float = 0.0
    heuristic_applied: bool = False
    suggested_skill_key: str = ""
    suggested_skill_ru: str = ""


def _rank(statement: StatementView) -> tuple[int, int]:
    """Чем сильнее подтверждена компетенция, тем она «главнее» в объяснении.

    У требования эталона может быть несколько ключей («Python или Go»):
    кандидату не обязательно закрывать оба, достаточно сильнейшего.
    """
    return (_STATUS_RANK[statement.status], statement.artifact_count)


def _apply_complexity_heuristic(
    competency: ReferenceCompetency, status: str, statements: list[StatementView]
) -> tuple[str, bool]:
    """FR1.5: сложность задач подтверждается артефактом, а не словами."""
    if competency.category != "task_complexity" or status != LIMITED:
        return status, False

    has_artifact = any(item.artifact_count > 0 for item in statements)
    detailed = any(item.longest_text >= COMPLEXITY_MIN_DESCRIPTION for item in statements)

    if has_artifact and detailed:
        return MEDIUM, True
    return status, False


def _reason(
    competency: ReferenceCompetency,
    status: str,
    statements: list[StatementView],
    heuristic_applied: bool,
) -> str:
    """Статус без объяснения показывать нельзя (FR2.2)."""
    if not statements:
        return (
            "В профиле нет ни одной компетенции, которая закрывала бы это требование эталона."
        )

    source = max(statements, key=_rank)
    reason = source.reason

    # Если компетенция эталона собрана из нескольких навыков, говорим, какой
    # именно сработал - иначе объяснение повисает в воздухе.
    if len(competency.taxonomy_keys) > 1:
        reason = f"{source.skill_name_ru}: {reason[0].lower()}{reason[1:]}"

    if heuristic_applied:
        reason = f"{reason} {COMPLEXITY_HEURISTIC_NOTE}"

    return reason


def compute_results(
    profile: ReferenceProfile, statements: list[StatementView]
) -> list[CompetencyResult]:
    by_key: dict[str, list[StatementView]] = {}
    for statement in statements:
        by_key.setdefault(statement.skill_name, []).append(statement)

    results: list[CompetencyResult] = []

    for competency in profile.competencies:
        matched: list[StatementView] = []
        for key in competency.taxonomy_keys:
            matched.extend(by_key.get(key, []))

        status = max(
            (item.status for item in matched), key=lambda s: _STATUS_RANK[s], default=NOT_STARTED
        )
        status, heuristic_applied = _apply_complexity_heuristic(competency, status, matched)

        results.append(
            CompetencyResult(
                competency_id=competency.competency_id,
                name_ru=competency.name_ru,
                short_ru=competency.short_ru,
                category=competency.category,
                weight=competency.weight,
                required_depth=competency.required_depth,
                status=status,
                reason=_reason(competency, status, matched, heuristic_applied),
                statement_ids=[item.id for item in matched],
                evidence_count=sum(item.artifact_count for item in matched),
                score_contribution=round(STATUS_SCORE[status] * competency.weight, 6),
                heuristic_applied=heuristic_applied,
                suggested_skill_key=competency.taxonomy_keys[0],
                suggested_skill_ru=BY_KEY[competency.taxonomy_keys[0]].ru,
            )
        )

    return results


def compute_snapshot(profile: ReferenceProfile, statements: list[StatementView]) -> dict:
    """§4.3 FRD: снимок индекса на момент запроса."""
    results = compute_results(profile, statements)
    overall = round(sum(item.score_contribution for item in results) * 100)

    # Белые пятна идут по весу: сначала то, что сильнее двигает индекс (FR3.2).
    white_spots = sorted(
        (item for item in results if item.status in WHITE_SPOT_STATUSES),
        key=lambda item: (-item.weight, item.name_ru),
    )

    return {
        "level": profile.level,
        "segment": profile.segment,
        "reference_profile_id": profile.id,
        "overall_score": overall,
        "components": [
            {
                "competency_id": item.competency_id,
                "name_ru": item.name_ru,
                "short_ru": item.short_ru,
                "category": item.category,
                "weight": item.weight,
                "required_depth": item.required_depth,
                "status": item.status,
                "reason": item.reason,
                "statement_ids": item.statement_ids,
                "evidence_count": item.evidence_count,
                "score_contribution": item.score_contribution,
                "heuristic_applied": item.heuristic_applied,
                # С чего кандидату начинать, если компетенции ещё нет в профиле:
                # имя навыка из таксономии модуля 2, а не название требования
                # эталона - иначе созданное утверждение не сойдётся с эталоном.
                "suggested_skill_key": item.suggested_skill_key,
                "suggested_skill_ru": item.suggested_skill_ru,
            }
            for item in results
        ],
        "white_spots": [item.competency_id for item in white_spots],
        "radar_points": [
            {
                "competency_id": item.competency_id,
                "short_ru": item.short_ru,
                "candidate_value": STATUS_SCORE[item.status],
                "reference_value": DEPTH_REFERENCE[item.required_depth],
            }
            for item in results
        ],
    }
