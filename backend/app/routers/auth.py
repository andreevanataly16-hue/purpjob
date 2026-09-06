"""Регистрация, вход, выход и текущий пользователь.

Почта не подтверждается. Это осознанно и это же определяет режим регистрации:
раз адрес не проверен, публично открывать регистрацию нельзя - иначе любой
завёл бы профиль на чужую почту, а продукт выглядел бы так, будто адрес
проверен. Поэтому закрытый пилот по приглашению: код знает только тот, кому
его дали, и это единственное, что здесь утверждается про адрес.

Из того же следует, что восстановления пароля нет и быть не может: письмо
ушло бы на адрес, принадлежность которого продукт не проверял. Забытый пароль
в пилоте решает администратор, а не форма на сайте.

Границы решения описаны в README.
"""

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User, UserSession, utcnow
from app.ratelimit import TOO_MANY_ATTEMPTS_RU, client_address, login_limiter
from app.schemas import Credentials, RegisterCredentials, UserOut
from app.security import (
    hash_password,
    hash_session_token,
    new_session_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

INVITE_ONLY = "invite"

REGISTRATION_CLOSED_RU = (
    "Регистрация сейчас закрыта. Профили в пилоте заводятся по приглашению."
)
BAD_INVITE_RU = (
    "Код приглашения не подходит. Пилот закрытый: профиль заводится по коду, "
    "который выдают участникам."
)
UNVERIFIED_EMAIL_RU = (
    "Почта не подтверждается: указывайте свою. Восстановления пароля по почте "
    "в пилоте нет - забытый пароль меняет администратор."
)


def _check_invite(request: Request, code: str | None) -> None:
    """Пускает дальше только с верным кодом приглашения.

    Код общий на пилот, а значит подбираемый, - поэтому попытки считаются тем
    же ограничителем, что и попытки входа. Сравнение постоянное по времени:
    обычное сравнение строк выдаёт длину совпавшего начала.
    """
    if settings.registration_mode != INVITE_ONLY:
        return

    if not settings.pilot_invite_code:
        # Пустой код - не "пускать всех", а "регистрация ещё не настроена".
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, REGISTRATION_CLOSED_RU)

    address = client_address(request)
    wait = login_limiter.retry_after(address, "приглашение")
    if wait is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            TOO_MANY_ATTEMPTS_RU,
            headers={"Retry-After": str(wait)},
        )

    # Сравниваем байты, а не строки: compare_digest на строках не принимает
    # ничего вне ASCII, а код приглашения вполне может быть русским.
    if not secrets.compare_digest(
        (code or "").encode("utf-8"), settings.pilot_invite_code.encode("utf-8")
    ):
        login_limiter.register_failure(address, "приглашение")
        raise HTTPException(status.HTTP_403_FORBIDDEN, BAD_INVITE_RU)


def _open_session(db: Session, user: User, response: Response) -> None:
    """Создаёт сессию и кладёт токен в httpOnly-куку."""
    token = new_session_token()
    db.add(
        UserSession(
            token_hash=hash_session_token(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(days=settings.session_ttl_days),
        )
    )
    db.commit()

    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_days * 24 * 60 * 60,
        httponly=True,      # недоступна из JavaScript - защита от кражи через XSS
        samesite="lax",     # не уходит на чужие сайты - защита от CSRF
        secure=settings.cookie_secure,
        path="/",
    )


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Зависимость для защищённых эндпоинтов."""
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Вы не вошли в систему.")

    session = db.scalar(
        select(UserSession).where(UserSession.token_hash == hash_session_token(token))
    )
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия не найдена.")

    if session.is_expired:
        db.delete(session)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия истекла, войдите заново.")

    return session.user


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(
    data: RegisterCredentials,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> User:
    _check_invite(request, data.invite_code)

    user = User(email=data.email, password_hash=hash_password(data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Уникальный индекс в БД - единственный надёжный арбитр: проверка
        # "существует ли почта" отдельным запросом проигрывает гонке.
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Профиль с такой почтой уже есть. Попробуйте войти.",
        ) from None

    db.refresh(user)
    _open_session(db, user, response)
    return user


@router.post("/login", response_model=UserOut)
def login(
    data: Credentials,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> User:
    # Лимит проверяется до обращения к базе: иначе перебор всё равно нагружал
    # бы проверку пароля, которая намеренно медленная.
    address = client_address(request)
    wait = login_limiter.retry_after(address, data.email)
    if wait is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            TOO_MANY_ATTEMPTS_RU,
            headers={"Retry-After": str(wait)},
        )

    user = db.scalar(select(User).where(User.email == data.email))

    # Одна и та же ошибка на "нет такой почты" и "неверный пароль":
    # иначе форма превращается в способ узнать, кто зарегистрирован. По той же
    # причине неудача считается по присланному адресу, а не по найденному
    # пользователю: несуществующая почта должна упираться в лимит так же, как
    # существующая, иначе разница в поведении сама станет ответом.
    if user is None or not verify_password(data.password, user.password_hash):
        login_limiter.register_failure(address, data.email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверная почта или пароль.")

    login_limiter.register_success(address, data.email)
    _open_session(db, user, response)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        session = db.scalar(
            select(UserSession).where(UserSession.token_hash == hash_session_token(token))
        )
        if session is not None:
            db.delete(session)
            db.commit()

    response.delete_cookie(settings.session_cookie_name, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user
