"""Накопительный профиль: правила и константы (модуль 8).

Этот модуль отвечает на вопрос, чем PurpJob отличается от тестового задания.
Результат тестового задания выбрасывают, как только наём закончился. Здесь
подтверждённое становится имуществом кандидата: его не спрашивают дважды, оно
не пропадает, когда закончился один поиск, и оно переносится на новую роль без
новых вопросов.

Собственных вычислений тут почти нет: модуль читает то, что уже посчитали
модули 2, 3, 4, 6 и 7, и следит за тремя вещами - что ничего не потерялось,
что подтверждённое переиспользуется, и что видно, как профиль рос.

Про устаревание (§0 FRD). Мастер-документ описывает понижение веса компетенции
со временем, а модуль 6 запрещает уменьшать балл. Противоречия нет, но читать
это нужно однозначно, и вот выбранное чтение:

* устаревание - это про соответствие рынку, а не про достоверность;
* множитель применяется ТОЛЬКО при сборке PROF.индекса и никогда не попадает в
  Trust Score;
* сам статус компетенции и доказательства не меняются вообще - подтверждённое
  остаётся подтверждённым навсегда и видно всегда;
* одно нажатие «Актуализировать» возвращает полный вес, ничего не требуя
  доказывать заново.

Это чтение помечено в FRD как требующее подтверждения основателя. Если
устаревание должно было касаться и Trust Score, менять надо не здесь, а
правило FR5.1 модуля 6 - и это решение крупнее, чем один модуль.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# --- события роста (§4.2) -------------------------------------------------

EVIDENCE_ADDED = "evidence_added"
STATUS_UPGRADED = "competency_status_upgraded"
TRUST_INCREASED = "trust_component_increased"
ROLE_ADDED = "role_added"
DISPUTE_RESOLVED = "dispute_resolved_in_favor"
REUSED_ACROSS_ROLE = "competency_reused_across_role"
# Модуль 11: подтверждение помогло не только той вакансии, ради которой
# кандидат вернулся. Ради этого события модуль 11 и существует.
MATCH_ACROSS_VACANCIES = "match_score_increased_across_vacancies"

EVENT_TYPES = (
    EVIDENCE_ADDED,
    STATUS_UPGRADED,
    TRUST_INCREASED,
    ROLE_ADDED,
    DISPUTE_RESOLVED,
    REUSED_ACROSS_ROLE,
    MATCH_ACROSS_VACANCIES,
)

# --- поводы вернуться (§4.4) ---------------------------------------------

WHITE_SPOT_REMINDER = "white_spot_reminder"
DECAY_WARNING = "competency_decay_warning"

# Эти два повода строит сам модуль 8. Остальные были помечены там как [MVP-1]:
# им нужны живой поток вакансий и рекрутерская сторона, которых на тот момент
# не существовало.
OWN_TRIGGER_TYPES = (WHITE_SPOT_REMINDER, DECAY_WARNING)

# Достроены позже, когда появилось чем их порождать: лента вакансий (модуль 11)
# и первое действие рекрутера (модуль 13).
NEW_MATCHING_VACANCY = "new_matching_vacancy"
RECRUITER_INTEREST = "recruiter_interest"

# Реестр всех поводов, какие в продукте есть. Он один на всех намеренно: пока
# каждый модуль объявлял свой тип у себя, общий список переставал описывать
# реальность - и обещание «у события уже есть дом» оказывалось слабее, чем
# выглядело.
TRIGGER_TYPES = OWN_TRIGGER_TYPES + (NEW_MATCHING_VACANCY, RECRUITER_INTEREST)

PENDING = "pending"
SENT = "sent"
ACTED_UPON = "acted_upon"
DISMISSED = "dismissed"

# Формулировка про белое пятно взята из мастер-документа дословно (§3 FRD).
WHITE_SPOT_TEXT_RU = "У вас есть неподтверждённая компетенция — один вопрос закроет её."

# А вот текст про устаревание из мастер-документа использовать больше нельзя:
# он обещал понижение веса («мы понизим вес компетенции»), а понижения в
# продукте нет. Оставить обещание наказания, которого не будет, - хуже, чем
# отступить от исходной формулировки. Расхождение отмечено в README.
DECAY_TEXT_TEMPLATE_RU = (
    "Компетенция «{name}» давно не обновлялась. На балл это не влияет — "
    "но если есть новые материалы, профиль от них станет сильнее."
)

# --- калибруемые константы устаревания (§4.3) ----------------------------
#
# Стартовое значение отсчёта взято из мастер-документа и там же помечено как
# неоткалиброванное. Три дня - это очень мало для рынка труда; величина стоит
# отдельной константой именно затем, чтобы её меняли без правки логики.

DECAY_COUNTDOWN_DAYS = 3
STALE_AFTER_DAYS = 30

# За сколько до понижения показывать предупреждение.
WARN_BEFORE_DAYS = 1

FRESH = "fresh"
DECAYING = "decaying"
STALE = "stale"

# Множитель оставлен в модели, но в текущем MVP он ВЕЗДЕ равен единице.
#
# Раньше давность подтверждения понижала вклад компетенции в PROF.индекс. Это
# убрано: прошедшее время не делает доказательство менее доказательством, а
# балл, падающий за паузу, - это наказание, а не измерение опыта.
#
# Словарь не удалён намеренно: когда появится обоснованная модель актуальности
# (Skill Velocity, калибровка по реальным данным), менять придётся эти три
# числа, а не разбирать логику заново. Пока все три - единица, и тест следит,
# чтобы кто-нибудь не вернул понижение тихой правкой.
MULTIPLIER = {FRESH: 1.0, DECAYING: 1.0, STALE: 1.0}

# Статус - это про давность подтверждения, а не про качество. На балл он не
# влияет: формулировки подобраны так, чтобы не читаться как оценка.
FRESHNESS_RU = {
    FRESH: "подтверждено недавно",
    DECAYING: "давно не обновлялось",
    STALE: "давно не обновлялось",
}

# Статусы, которые считаются подтверждением компетенции: с них начинается и
# отсчёт актуальности, и право не спрашивать заново.
CONFIRMED_STATUSES = ("medium", "strong")


@dataclass(frozen=True)
class Freshness:
    """Актуальность одной компетенции на момент запроса."""

    competency_id: str
    status: str
    multiplier: float
    last_confirmed_at: datetime
    days_since: int
    days_to_decay: int


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(moment: datetime) -> datetime:
    """SQLite отдаёт даты без часового пояса - приводим к одному виду."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def freshness_for(competency_id: str, last_confirmed_at: datetime, now: datetime | None = None):
    """Во что превратилось подтверждение со временем.

    Функция чистая и не трогает ничего, кроме арифметики дат: устаревание не
    должно уметь менять данные даже случайно.
    """
    now = now or utcnow()
    days = max(0, (now - _aware(last_confirmed_at)).days)

    if days >= STALE_AFTER_DAYS:
        status = STALE
    elif days >= DECAY_COUNTDOWN_DAYS:
        status = DECAYING
    else:
        status = FRESH

    return Freshness(
        competency_id=competency_id,
        status=status,
        multiplier=MULTIPLIER[status],
        last_confirmed_at=_aware(last_confirmed_at),
        days_since=days,
        days_to_decay=max(0, DECAY_COUNTDOWN_DAYS - days),
    )


def needs_decay_warning(item: Freshness) -> bool:
    """Предупреждать стоит перед понижением и пока оно не разобрано."""
    return item.status != FRESH or item.days_to_decay <= WARN_BEFORE_DAYS


def decay_text(name_ru: str, item: Freshness) -> str:
    """Текст напоминания. Про балл здесь больше не говорится ничего.

    Понижения нет, поэтому обещать «вернём полный вес» нельзя - терять нечего.
    Напоминание осталось поводом вернуться и обновить материалы, если у
    кандидата есть чем.
    """
    return (
        f"Компетенцию «{name_ru}» вы подтверждали {item.days_since} дней назад. "
        "На балл это никак не влияет — подтверждённое остаётся подтверждённым. "
        "Но если с тех пор появились новые материалы, профиль от них станет сильнее."
    )


# --- тексты истории роста (§3: результат, а не механизм) -----------------


def describe(event_type: str, subject_ru: str, from_value: str | None, to_value: str | None) -> str:
    """Что показывать кандидату. Ведём итогом, а не названием таблицы.

    «Добавлена запись Evidence типа link» - это про устройство базы. Человек
    возвращается посмотреть, что у него выросло, а не что записалось.
    """
    if event_type == EVIDENCE_ADDED:
        return f"Добавлено доказательство: {subject_ru}."
    if event_type == STATUS_UPGRADED:
        return f"Компетенция «{subject_ru}» подтверждена сильнее: {from_value} → {to_value}."
    if event_type == TRUST_INCREASED:
        return f"Trust Score вырос по составляющей «{subject_ru}»: {from_value} → {to_value}."
    if event_type == ROLE_ADDED:
        return f"Добавлена целевая роль: {subject_ru}."
    if event_type == DISPUTE_RESOLVED:
        return f"Спор решён в вашу пользу: {subject_ru} — {from_value} → {to_value}."
    if event_type == MATCH_ACROSS_VACANCIES:
        return f"Подтверждение пригодилось ещё в {to_value} вакансиях вашей ленты."
    if event_type == REUSED_ACROSS_ROLE:
        return (
            f"Компетенция «{subject_ru}» уже была подтверждена — переносим в новую роль "
            "без дополнительных вопросов."
        )
    return subject_ru


# Заголовок группы - именительный падеж: «Сентября 2026» читается как обрывок
# даты, а не как название периода.
MONTHS_TITLE_RU = (
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)


def month_label(moment: datetime) -> str:
    """Заголовок группы: история должна читаться, а не пересчитываться глазами."""
    return f"{MONTHS_TITLE_RU[moment.month - 1]} {moment.year}"


def stale_threshold(now: datetime | None = None) -> datetime:
    """С какого момента белое пятно считается «висит давно» (FR5.2)."""
    return (now or utcnow()) - timedelta(days=DECAY_COUNTDOWN_DAYS)
