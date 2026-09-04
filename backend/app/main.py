"""Точка входа бэкенда PurpJob."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import Base, engine
from app.routers import auth, nda, probe, prof, profile

# Импорт моделей нужен, чтобы они попали в метаданные Base до create_all.
from app import models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    # На этом этапе таблицы создаются напрямую. Когда схема начнёт меняться
    # (профиль, Evidence, PROF), сюда придёт Alembic с миграциями.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="PurpJob API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(prof.router)
app.include_router(probe.router)
app.include_router(nda.router)


@app.get("/api/health", tags=["service"])
def health() -> dict[str, str]:
    return {"status": "ok"}
