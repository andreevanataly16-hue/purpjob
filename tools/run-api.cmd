@echo off
chcp 65001 >nul
rem Сервер приложения: FastAPI на порту 8001. Отдаёт всё, что под /api.
title PurpJob API
cd /d "%~dp0..\backend"
rem Миграции применяются перед запуском: приложение отказывается стартовать на
rem схеме, не соответствующей коду, - и это правильно, но чинить это вручную
rem каждый раз незачем.
"%~dp0..\.venv\Scripts\python.exe" -m alembic upgrade head
if errorlevel 1 (
  echo.
  echo Миграции не применились. Сервер не запускаю: на несовпадающей схеме он
  echo всё равно упадёт, только позже и непонятнее.
  echo.
  pause
  exit /b 1
)

"%~dp0..\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload --port 8001
echo.
echo Сервер остановился. Окно оставлено открытым, чтобы была видна причина.
pause
