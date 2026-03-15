@echo off
chcp 65001 >nul
title Деплой techercab 2.0

cd /d "C:\Users\MakscattSchool\Desktop\techercab 2.0"

echo.
echo ══════════════════════════════════════
echo   TECHERCAB 2.0 — деплой на Render
echo ══════════════════════════════════════
echo.

:: Проверяем, есть ли изменения
git status --short
echo.

:: Спрашиваем комментарий к коммиту
set /p MSG="Комментарий к коммиту (Enter = auto): "
if "%MSG%"=="" (
    for /f "tokens=1-3 delims=/ " %%a in ('date /t') do set D=%%c-%%b-%%a
    for /f "tokens=1-2 delims=: " %%a in ('time /t') do set T=%%a:%%b
    set MSG=deploy %D% %T%
)

echo.
echo → git add .
git add .

echo → git commit -m "%MSG%"
git commit -m "%MSG%"

if %errorlevel% neq 0 (
    echo.
    echo Нет изменений для коммита.
    pause
    exit /b 0
)

echo → git push origin main
git push origin main

if %errorlevel% neq 0 (
    echo.
    echo ✗ Ошибка push. Проверь подключение и авторизацию.
    pause
    exit /b 1
)

echo.
echo ══════════════════════════════════════
echo   Готово! Render подхватит автоматически.
echo   Деплой занимает ~2-3 минуты.
echo ══════════════════════════════════════
echo.

pause
