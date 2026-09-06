"""Роли и разграничение доступа.

До этого модуля роли не было вообще: любой вошедший мог открыть очередь
модератора, исправить чужой балл и посмотреть рекрутерскую сторону. На экране
кнопки были спрятаны, но прямой запрос к API проходил - а прятать кнопку и
называть это доступом нельзя.

Три принципа:

1. **Роль определяется на сервере.** Ни из тела запроса, ни из заголовка, ни
   из куки - только из записи пользователя в базе. Роль, присланную клиентом,
   читать нельзя ни при каких условиях.
2. **Запрещено по умолчанию.** Проверка навешивается на роутер целиком, а не
   на отдельные обработчики: забыть добавить её на новый обработчик проще, чем
   забыть завести новый роутер.
3. **Обращение к чужим данным оставляет след.** Кто, что, над кем и когда. Без
   содержимого: в журнал не должно попадать то, что кандидат закрыл под NDA.

Это минимальная граница, а не система управления доступом. Настоящая ролевая
модель (кто вправе назначать роли, разграничение по компаниям, срок действия)
здесь не строится - но подменить роль запросом уже нельзя.
"""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AccessLog, User
from app.routers.auth import current_user

CANDIDATE = "candidate"
RECRUITER = "recruiter"
MODERATOR = "moderator"

ROLES = (CANDIDATE, RECRUITER, MODERATOR)

ROLE_RU = {
    CANDIDATE: "кандидат",
    RECRUITER: "рекрутер",
    MODERATOR: "модератор",
}

# Роль по умолчанию. Кандидат - самая безобидная из трёх: регистрация не должна
# выдавать никаких прав над чужими данными.
DEFAULT_ROLE = CANDIDATE

# Роли не наследуются. Модератор разбирает споры, но это не делает его
# рекрутером: у него нет причины смотреть базу кандидатов, и наоборот. Общая
# «роль повыше» - привычный способ незаметно раздать лишнее.
CAPABILITIES = {
    CANDIDATE: frozenset(),
    RECRUITER: frozenset({RECRUITER}),
    MODERATOR: frozenset({MODERATOR}),
}

DENIED_RU = (
    "Недостаточно прав: это раздел для роли «{role}». Роль назначается администратором, "
    "запросом её изменить нельзя."
)


def role_of(user: User) -> str:
    """Роль из записи пользователя. Единственный источник."""
    return user.role if user.role in ROLES else DEFAULT_ROLE


def has(user: User, capability: str) -> bool:
    return capability in CAPABILITIES[role_of(user)]


def record(
    db: Session,
    user: User,
    action: str,
    target: str,
    *,
    note: str | None = None,
) -> AccessLog:
    """След обращения к чужим данным.

    Содержимого здесь нет намеренно: журнал отвечает на вопрос «кто и к чему
    обращался», а не хранит второй копией то, что кандидат закрыл. Особенно это
    касается материалов под NDA - их содержимое не должно оказаться в журнале
    доступа даже случайно.
    """
    entry = AccessLog(
        actor_user_id=user.id,
        actor_role=role_of(user),
        action=action,
        target=target,
        note=note,
    )
    db.add(entry)
    db.commit()
    return entry


def _require(capability: str):
    """Зависимость-страж. Вешается на роутер целиком, а не на обработчики."""

    def guard(
        request: Request,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not has(user, capability):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                DENIED_RU.format(role=ROLE_RU[capability]),
            )

        # Путь и метод - достаточное описание обращения. Тело запроса в журнал
        # не идёт: там может быть что угодно, вплоть до закрытого материала.
        record(
            db,
            user,
            action=f"{request.method} {request.url.path}",
            target=request.query_params.get("candidate_id")
            or request.path_params.get("candidate_id")
            or request.path_params.get("case_id")
            or "-",
        )
        return user

    return guard


require_recruiter = _require(RECRUITER)
require_moderator = _require(MODERATOR)
