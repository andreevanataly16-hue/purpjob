"""Калибровка по обратной связи рекрутеров (модуль 14).

Всё остальное в продукте может быть внутренне непротиворечивым и при этом
ошибаться насчёт мира. Этот модуль - единственное место, где система сверяется
с реальностью через людей, которые её наблюдали: рекрутеров, дошедших до
собеседования.

Четыре механизма обратной связи в продукте похожи только на слух, и сливать их
нельзя:

* «вопрос не подходит» (модуль 4) - кандидат про качество вопроса;
* спор (модуль 7) - кандидат про вывод о себе, случай разбирается поштучно;
* поводы вернуться (модуль 8) - удержание, а не правильность;
* **обратная связь рекрутера (здесь)** - совпал ли вывод системы с тем, что
  человек увидел вживую. Это сигнал про формулу, а не про кандидата.

Отсюда главное ограничение: **отзыв рекрутера не меняет балл кандидата.**
Ни при каких условиях. Мнение одного человека не должно уметь уронить чей-то
профиль - иначе рушится всё, на чём построен модуль 6.

И второе: **никакой автоматической подстройки формул.** Человек смотрит на
накопленные данные и принимает решение письменно, под запись - та же
дисциплина, что у правки модератора в модуле 7, только уровнем выше: не один
случай, а то, как система считает всех дальше.
"""

from dataclasses import dataclass

# --- исходы взаимодействия -------------------------------------------------

CONFIRMED_RELEVANT = "confirmed_relevant"
NOT_RELEVANT = "not_relevant"
PARTIALLY_RELEVANT = "partially_relevant"

OUTCOMES = (CONFIRMED_RELEVANT, NOT_RELEVANT, PARTIALLY_RELEVANT)

OUTCOME_RU = {
    CONFIRMED_RELEVANT: "Да",
    NOT_RELEVANT: "Нет",
    PARTIALLY_RELEVANT: "Частично",
}

OUTCOME_PROMPT_RU = "Кандидат оказался релевантен после собеседования?"
COMPONENT_PROMPT_RU = "Эта информация оказалась полезной или вводящей в заблуждение?"

USEFUL = "useful"
MISLEADING = "misleading"
VERDICTS = (USEFUL, MISLEADING)

VERDICT_RU = {USEFUL: "полезно", MISLEADING: "ввело в заблуждение"}

# --- калибруемые константы -------------------------------------------------
#
# Все три - неоткалиброванные величины, как и всё остальное в этом проекте.
# Держатся именованными константами ровно затем, чтобы их можно было менять,
# не трогая логику - и чтобы такая замена была видна в журнале (§4.4 FRD).

# Ниже этого числа отзывов «систематической проблемы» не бывает: один
# комментарий не должен уметь поднять флаг.
MIN_SAMPLE_SIZE = 5

# Доля «ввело в заблуждение», выше которой стоит присмотреться.
MISLEADING_RATE_THRESHOLD = 0.3

# Балл, выше которого система фактически утверждает «этот профиль
# подтверждён». Нужен, чтобы сравнить её утверждение с исходом.
HIGH_SCORE_THRESHOLD = 60

# Именованный список констант, которые вообще разрешено менять этим модулем.
# Список закрытый: «поменять что угодно по имени» - это способ обойти запись.
CALIBRATABLE = {
    "module3.status_score_mapping": "Перевод статуса компетенции в вклад (модуль 3)",
    "module6.independence_weighting": "Вес повторного источника в Trust Score (модуль 6)",
    "module8.decay_countdown_days": "Отсчёт устаревания компетенции (модуль 8)",
    "module10.criticality_weight": "Вес обязательного требования против желательного (модуль 10)",
    "module11.min_match_score_to_notify": "Порог уведомления о вакансии (модуль 11)",
    "module14.min_sample_size": "Минимальная выборка для флага (модуль 14)",
    "module14.misleading_rate_threshold": "Порог доли «ввело в заблуждение» (модуль 14)",
}

RANDOM = "random"
HIGH_DIVERGENCE = "high_divergence"
SELECTION_CRITERIA = (RANDOM, HIGH_DIVERGENCE)

SELECTION_RU = {
    RANDOM: "случайная выборка",
    HIGH_DIVERGENCE: "там, где вывод разошёлся с исходом",
}


@dataclass(frozen=True)
class Insight:
    """Насколько часто конкретный вывод вводил рекрутеров в заблуждение."""

    subject_type: str
    subject_id: str
    sample_size: int
    misleading_rate: float
    useful_rate: float
    flagged_for_review: bool


def outcomes_agree(outcome: str, score: int) -> bool | None:
    """Совпал ли вывод системы с тем, что рекрутер увидел вживую.

    Правило вынесено отдельной функцией намеренно: как считать «частично» и где
    проходит порог высокого балла - это само по себе калибровочное решение, а
    не установленный факт. В документе, полном заведомо временных формул, эта
    не должна незаметно стать первой «окончательной».

    `None` означает «не считаем ни совпадением, ни расхождением»: частичный
    исход честнее не записывать ни в один лагерь, чем натянуть.
    """
    if outcome == PARTIALLY_RELEVANT:
        return None
    high = score >= HIGH_SCORE_THRESHOLD
    return high if outcome == CONFIRMED_RELEVANT else not high


def insight_for(subject_type: str, subject_id: str, verdicts: list[str]) -> Insight:
    """Сводка по одному виду вывода.

    Флаг поднимается только при двух условиях сразу: набралась выборка И доля
    выше порога. Одного отзыва достаточно, чтобы заметить, но недостаточно,
    чтобы объявить закономерность - ровно та ошибка, которую этот модуль
    должен предотвращать, а не совершать.
    """
    total = len(verdicts)
    misleading = verdicts.count(MISLEADING)
    rate = misleading / total if total else 0.0

    return Insight(
        subject_type=subject_type,
        subject_id=subject_id,
        sample_size=total,
        misleading_rate=round(rate, 2),
        useful_rate=round(1 - rate, 2) if total else 0.0,
        flagged_for_review=total >= MIN_SAMPLE_SIZE and rate > MISLEADING_RATE_THRESHOLD,
    )


def trust_accuracy(pairs: list[tuple[str, int]]) -> dict:
    """«Trust Accuracy» - совпадение оценки системы с живым интервью.

    Если это число держится около случайного даже на приличной выборке, дело
    не в константах: значит, ошибается сама модель. Разница между «подкрутить
    коэффициент» и «пересобрать подход» должна оставаться видимой.
    """
    judged = [(outcome, score) for outcome, score in pairs if outcomes_agree(outcome, score) is not None]
    matching = sum(1 for outcome, score in judged if outcomes_agree(outcome, score))

    return {
        "total_feedback_count": len(pairs),
        "comparable_count": len(judged),
        "matching_count": matching,
        "trust_accuracy_pct": round(100 * matching / len(judged)) if judged else None,
    }
