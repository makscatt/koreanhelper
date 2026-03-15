@echo off
title Deploy techercab 2.0

cd /d "C:\Users\MakscattSchool\Desktop\techercab 2.0"

echo.
echo ========================================
echo   TECHERCAB 2.0 -- deploy to Render
echo ========================================
echo.

git status --short
echo.

set /p MSG="Commit message (Enter = auto): "
if "%MSG%"=="" (
    for /f "tokens=1-3 delims=/ " %%a in ('date /t') do set D=%%c-%%b-%%a
    for /f "tokens=1-2 delims=: " %%a in ('time /t') do set T=%%a:%%b
    set MSG=deploy %D% %T%
)

echo.
echo --- git add .
git add .

echo --- git commit -m "%MSG%"
git commit -m "%MSG%"

if %errorlevel% neq 0 (
    echo.
    echo Nothing to commit.
    pause
    exit /b 0
)

echo --- git push origin main
git push origin main

if %errorlevel% neq 0 (
    echo.
    echo Push failed. Check connection.
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Done! Render will pick it up.
echo ========================================
echo.

pause
