"""Поэтапное раскрытие (модуль 13).

Модуль существует ради одной проверяемой вещи: первое решение рекрутера должно
приниматься по профессиональным данным, до того как в поле зрения попадёт имя
или фотография - то есть до сигналов, которые коррелируют с возрастом, полом и
происхождением. Это не приватность, переодетая в защиту от предвзятости, - это
именно защита от предвзятости, которая заодно бережёт данные.

Что здесь важнее удобства:

* **Скрывается ровно два поля.** Имя и фотография. Все остальные данные модуля
  12 показываются на первом же этапе целиком - иначе рекрутеру нечем было бы
  принимать решение, и он просто нажимал бы «показать» не глядя.
* **Метка стабильна.** «Кандидат #A17» не меняется от просмотра к просмотру:
  иначе рекрутер не смог бы узнать того, кого смотрел вчера, и поэтапность
  превратилась бы в помеху.
* **Ничего не считается и не пишется в чужие модули.** Это слой отображения.
"""

import hashlib
from dataclasses import dataclass

STAGE_1 = "stage1_professional"
STAGE_2 = "stage2_identity"
STAGE_3 = "stage3_contact"

STAGES = (STAGE_1, STAGE_2, STAGE_3)

STAGE_RU = {
    STAGE_1: "видит только профессиональные данные",
    STAGE_2: "видит имя и фотографию",
    STAGE_3: "видит контакты",
}

RECRUITER_MARKED_INTEREST = "recruiter_marked_interest"
MUTUAL_INTEREST_CONFIRMED = "mutual_interest_confirmed"

ADVANCE_LABEL_RU = "Показать больше об этом кандидате"
CONTACT_LABEL_RU = "Запросить контакты"

STAGE1_NOTE_RU = (
    "Имя и фотография пока скрыты намеренно: первое решение принимается по подтверждённому "
    "опыту, а не по тому, как человека зовут и как он выглядит. Все остальные данные открыты."
)

CANDIDATE_NOTE_TEMPLATE_RU = (
    "Рекрутер по вакансии «{vacancy}» пока видит только ваш PROF.индекс и Trust Score. "
    "Имя и фото будут показаны, если рекрутер отметит интерес к вашему профилю."
)

OPT_OUT_LABEL_RU = "Разрешить рекрутерам сразу видеть моё имя и фото"

# Буквы без похожих начертаний: метку читают и произносят вслух.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"


@dataclass(frozen=True)
class Identity:
    """Как кандидат подписан на текущем этапе."""

    label: str
    photo_label: str
    identity_revealed: bool


def anonymous_label(candidate_id: str) -> str:
    """Стабильная метка вида «Кандидат #A17».

    Считается из идентификатора, а не выдаётся счётчиком: метка должна быть
    одинаковой в любом сеансе и у любого рекрутера, иначе «тот самый кандидат,
    которого я смотрел вчера» перестанет существовать (§7 FRD).
    """
    digest = hashlib.sha256(candidate_id.encode("utf-8")).digest()
    letter = _ALPHABET[digest[0] % len(_ALPHABET)]
    number = digest[1] % 100
    return f"Кандидат #{letter}{number:02d}"


def identity_for(candidate_id: str, display_name: str, photo_label: str, stage: str) -> Identity:
    """Что показать вместо имени и фото на первом этапе.

    Пустое место читалось бы как сломанный профиль, поэтому подставляется
    осмысленная метка: видно, что это скрыто нарочно, а не потеряно (FR1.2).
    """
    if stage == STAGE_1:
        return Identity(label=anonymous_label(candidate_id), photo_label="—", identity_revealed=False)
    return Identity(label=display_name, photo_label=photo_label, identity_revealed=True)


def next_stage(current: str) -> str:
    if current == STAGE_1:
        return STAGE_2
    if current == STAGE_2:
        return STAGE_3
    return STAGE_3
