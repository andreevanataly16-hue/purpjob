@echo off
chcp 65001 >nul
rem Запуск PurpJob: два сервера в двух окнах.
rem
rem Их действительно нужно два, и это не усложнение: FastAPI отдаёт API на 8001,
rem Vite отдаёт страницу на 8000 и проксирует /api на 8001. Если поднять только
rem сайт, страница откроется, а вход выдаст ошибку - именно так это и выглядит,
rem когда кажется, что «проект не запускается».
rem
rem Сами команды лежат в tools\run-api.cmd и tools\run-web.cmd отдельными
rem файлами намеренно: в одну строку со start их пришлось бы обернуть во
rem вложенные кавычки, а cmd на них спотыкается - и окно молча закрывается.
rem
rem Файл сохранён с переносами CRLF. Это не мелочь: на юниксовых переносах
rem cmd.exe ведёт себя непредсказуемо и чаще всего просто закрывает окно.

cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\python.exe" (
  echo.
  echo Не нашли окружение Python: .venv\Scripts\python.exe
  echo Похоже, зависимости ещё не установлены. Что делать - в README, раздел «Первый раз».
  echo.
  pause
  exit /b 1
)

if not exist "%~dp0node_modules\vite" (
  echo.
  echo Не нашли зависимости сайта: node_modules\vite
  echo Выполните в этой папке: npm install
  echo.
  pause
  exit /b 1
)

echo Запускаю сервер приложения (FastAPI, порт 8001)...
start "PurpJob API" "%~dp0tools\run-api.cmd"

echo Запускаю сайт (Vite, порт 8000)...
start "PurpJob web" "%~dp0tools\run-web.cmd"

echo.
echo Готово. Через несколько секунд откройте http://localhost:8000
echo Чтобы остановить - закройте два открывшихся окна.
echo.
pause
