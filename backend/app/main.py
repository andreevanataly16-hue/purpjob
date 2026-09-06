"""Точка входа бэкенда PurpJob."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import engine
from app.schema import SchemaOutdated, assert_schema_current
from app.routers import (
    auth,
    export,
    growth,
    moderation,
    nda,
    probe,
    prof,
    profile,
    recruiter,
    retention,
    calibration,
    plugin,
    reveal,
    trust,
    vacancies,
    xai,
)

# Импорт моделей нужен, чтобы вся схема попала в метаданные Base: по ним
# Alembic сверяет базу с кодом.
from app import models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Проверяет, что схема базы соответствует коду - и не правит её молча.

    Раньше здесь стоял `create_all()`. Он умеет только создавать недостающие
    таблицы: новый столбец в уже существующую он не добавляет и об этом не
    сообщает. Приложение поднималось, а падало потом - на первом запросе,
    который этот столбец читал.

    Автоматически применять миграции на старте тоже нельзя: изменение схемы не
    должно случаться побочным эффектом запуска. Поэтому здесь только проверка,
    а команду выполняет человек - её же выполняет и tools/run-api.cmd.
    """
    assert_schema_current(engine)
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
app.include_router(trust.router)
app.include_router(xai.router)
app.include_router(moderation.router)
app.include_router(growth.router)
app.include_router(export.router)
app.include_router(vacancies.router)
app.include_router(retention.router)
app.include_router(recruiter.router)
app.include_router(reveal.router)
app.include_router(calibration.feedback_router)
app.include_router(calibration.router)
app.include_router(plugin.router)


@app.get("/api/health", tags=["service"])
def health() -> dict[str, str]:
    return {"status": "ok"}
