@echo off
rem Сервер приложения: FastAPI на порту 8001. Отдаёт всё, что под /api.
cd /d "%~dp0.."
title PurpJob API
cd backend
"%~dp0..\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload --port 8001
echo.
echo Сервер остановился. Окно оставлено открытым, чтобы была видна причина.
pause
