"""Модуль 15: плагин рекрутера — серверная часть.

Плагин живёт в чужом интерфейсе: рекрутер продолжает работать там, где работал,
а PurpJob показывает свой разбор поверх. Отсюда всё устройство модуля.

**Что сюда НЕ приходит.** Текст резюме. Никогда. Экспресс-разбор резюме идёт
целиком в браузере рекрутера ([`web/src/express.js`](../../web/src/express.js)),
и у того файла физически нет доступа к сети - это проверяется тестом, читающим
исходник, а не обещанием в документации.

**Единственное, что уходит на сервер до согласия кандидата** - хеш контакта в
«Найти в базе». Ни имени, ни почты в открытом виде, ни текста.

**Что здесь не хранится.** Ничего про кандидатов, которых рекрутер просто
посмотрел. Поиск по хешу не записывается вообще: запись «этот рекрутер искал
этого человека» - уже след, которого быть не должно.

Разбор вакансии - другое дело: это текст объявления, а не персональные данные,
и его разбирает общий фильтр Б ([`app/requirements.py`](../requirements.py)).
Граница проходит ровно здесь и нигде больше.
"""

import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import candidates as pool, requirements
from app.db import get_db
from app.models import User, VerificationInvite
from app.routers.auth import current_user
from app.schemas_plugin import (
    ExtractionOut,
    InviteIn,
    InviteOut,
    LookupIn,
    LookupOut,
    PluginInfoOut,
)

router = APIRouter(prefix="/api/plugin", tags=["plugin"])

# --- три честных состояния светофора (§3 FRD, формулировки дословные) ------

VERIFIED = "verified"
PRELIMINARY = "preliminary"
NEEDS_VERIFICATION = "needs_verification"

TIER_RU = {
    VERIFIED: "Верифицирован",
    PRELIMINARY: "Предварительный",
    NEEDS_VERIFICATION: "Требует верификации",
}

TIER_NOTE_RU = {
    VERIFIED: "Кандидат прошел микро-кейсы, артефакты проверены. Максимальное доверие",
    PRELIMINARY: (
        "Кандидат не проходил верификацию. Это оценка текста, а не доказательство. "
        "Рекрутер видит, что цифра может измениться"
    ),
    NEEDS_VERIFICATION: "Кандидат не зарегистрирован",
}

HONESTY_RU = "Мы не обманываем рекрутера. Мы даем честную оценку с указанием степени достоверности."

LENS_RU = (
    "Плагин — это не «шпион». Это «линза», через которую рекрутер видит больше информации, "
    "но только с согласия кандидата."
)

PRIVACY_RU = (
    "Ничего не читается со страницы само. Разбирается только тот текст, который вы выделили "
    "или скачали сами. Текст резюме на сервер не уходит вообще — он разбирается прямо в "
    "браузере. На сервер уходит один хеш контакта, и только когда вы нажмёте «Найти в базе»."
)

REGISTERED_VERIFIED = "registered_verified"
NOT_REGISTERED = "not_registered"


def _hash(value: str) -> str:
    """Тот же способ хеширования, что и на стороне плагина.

    Нормализация обязательна: без неё «Иван Петров» и «иван петров » дали бы
    разные хеши, и поиск не нашёл бы зарегистрированного человека.
    """
    return "sha256:" + hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def _known_hashes(db: Session) -> dict[str, str]:
    """Хеши тех, кто в базе уже есть.

    Сравниваются хеши с хешами - открытый контакт с той стороны сюда не
    приходит и здесь не восстанавливается.
    """
    found: dict[str, str] = {}

    for candidate in pool.visible_pool():
        found[_hash(candidate.display_name)] = candidate.id

    for user in db.scalars(select(User)):
        found[_hash(user.email)] = f"user_{user.id}"

    return found


@router.get("", response_model=PluginInfoOut)
def read_info(user: User = Depends(current_user)) -> PluginInfoOut:
    """Что плагин говорит о себе до того, как что-то сделает."""
    return PluginInfoOut.model_validate(
        {
            "privacy_ru": PRIVACY_RU,
            "honesty_ru": HONESTY_RU,
            "lens_ru": LENS_RU,
            "tiers": [
                {"tier": tier, "label_ru": TIER_RU[tier], "note_ru": TIER_NOTE_RU[tier]}
                for tier in (VERIFIED, PRELIMINARY, NEEDS_VERIFICATION)
            ],
        }
    )


@router.post("/vacancy", response_model=ExtractionOut)
def extract_vacancy(
    data: dict, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ExtractionOut:
    """FR2.1-FR2.3: требования вакансии тем же фильтром Б, что у модуля 10.

    Сюда приходит текст объявления, а не резюме. Это не персональные данные, и
    граница между «можно на сервер» и «только в браузере» проходит ровно здесь.
    """
    text = str(data.get("raw_text") or "")
    if not text.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Выделите текст вакансии.")

    items = requirements.extract(text)
    return ExtractionOut.model_validate(
        {
            "requirements": [
                {
                    "competency_id": item.competency_id,
                    "taxonomy_key": item.taxonomy_key,
                    "label_ru": item.label_ru,
                    "criticality": item.criticality,
                    "criticality_ru": (
                        "обязательное" if item.criticality == "mandatory" else "желательное"
                    ),
                    "evidence_hint_ru": item.evidence_hint_ru,
                    "in_reference_profile": item.competency_id is not None,
                    "matched_text": item.matched_text,
                }
                for item in items
            ],
            "unknown_count": len(requirements.unknown_requirements(items)),
            "unknown_note_ru": (
                "Эти требования не покрыты эталонами ролей — библиотека охватывает один сегмент. "
                "Это факт про вакансию, а не пробел разбора."
            ),
        }
    )


@router.post("/lookup", response_model=LookupOut)
def lookup(
    data: LookupIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> LookupOut:
    """FR4.2: единственное действие, которое вообще что-то передаёт на сервер.

    Приходит только хеш. Ни имени, ни почты, ни текста - и ничего из этого не
    записывается: поиск не оставляет следа, потому что след «искали этого
    человека» сам по себе персональные данные.
    """
    if not data.contact_hash.startswith("sha256:") or len(data.contact_hash) != 71:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Ожидается хеш контакта, а не сам контакт.",
        )

    candidate_id = _known_hashes(db).get(data.contact_hash)
    if candidate_id is None:
        return LookupOut.model_validate(
            {
                "result": NOT_REGISTERED,
                "candidate_id": None,
                "tier": NEEDS_VERIFICATION,
                "tier_label_ru": TIER_RU[NEEDS_VERIFICATION],
                "tier_note_ru": TIER_NOTE_RU[NEEDS_VERIFICATION],
            }
        )

    return LookupOut.model_validate(
        {
            "result": REGISTERED_VERIFIED,
            "candidate_id": candidate_id,
            "tier": VERIFIED,
            "tier_label_ru": TIER_RU[VERIFIED],
            "tier_note_ru": TIER_NOTE_RU[VERIFIED],
        }
    )


@router.post("/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
def create_invite(
    data: InviteIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> InviteOut:
    """FR3.1-FR3.3: ссылка-приглашение, которую отправляет сам рекрутер.

    Никакой автоматической отправки здесь нет - то же правило, что у экспорта
    кандидата в модуле 9, только с другой стороны. Платформа не пишет людям
    вместо тех, кто решил им написать.
    """
    invite = VerificationInvite(
        recruiter_user_id=user.id,
        token=secrets.token_urlsafe(16),
        note_ru=(data.note_ru or "").strip() or None,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    link = f"/?invite={invite.token}"
    return InviteOut.model_validate(
        {
            "id": f"inv_{invite.id:03d}",
            "invite_link": link,
            "status": invite.status,
            "created_at": invite.created_at,
            "message_ru": (
                "Здравствуйте! Чтобы подтвердить профессиональный профиль, пройдите короткую "
                f"проверку на PurpJob: {link} — это займёт несколько минут и останется вашим "
                "независимо от этой вакансии."
            ),
            "send_note_ru": (
                "Скопируйте и отправьте сами — своим каналом. PurpJob ничего никому не "
                "отправляет за вас."
            ),
        }
    )
