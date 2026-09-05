@echo off
rem Сайт: Vite на порту 8000. Проксирует /api на 8001.
cd /d "%~dp0.."
title PurpJob web
call npm run dev
echo.
echo Сервер остановился. Окно оставлено открытым, чтобы была видна причина.
pause
