@echo off
chcp 65001 >nul
rem Сайт: Vite на порту 8000. Проксирует /api на 8001.
title PurpJob web
cd /d "%~dp0.."
call npm run dev
echo.
echo Сервер остановился. Окно оставлено открытым, чтобы была видна причина.
pause
