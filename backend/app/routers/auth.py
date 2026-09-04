"""Регистрация, вход, выход и текущий пользователь.

Подтверждение почты намеренно не предусмотрено: после регистрации кандидат
сразу оказывается внутри. Последствия этого решения описаны в README.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User, UserSession, utcnow
from app.schemas import Credentials, RegisterCredentials, UserOut
from app.security import (
    hash_password,
    hash_session_token,
    new_session_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


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
def register(data: RegisterCredentials, response: Response, db: Session = Depends(get_db)) -> User:
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
def login(data: Credentials, response: Response, db: Session = Depends(get_db)) -> User:
    user = db.scalar(select(User).where(User.email == data.email))

    # Одна и та же ошибка на "нет такой почты" и "неверный пароль":
    # иначе форма превращается в способ узнать, кто зарегистрирован.
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверная почта или пароль.")

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
