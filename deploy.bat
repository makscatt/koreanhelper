@echo off
setlocal EnableDelayedExpansion

:: ============================================
:: deploy.bat - Deploy JARVIS to Render
:: ============================================

echo.
echo === JARVIS Deploy Script ===
echo.

:: Check git repo
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Not a git repository!
    echo Run: git init
    echo Run: git remote add origin https://github.com/YOUR_USERNAME/jarvis.git
    pause
    exit /b 1
)

:: Check remote
git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Remote "origin" not set!
    pause
    exit /b 1
)

:: Get current branch
for /f "tokens=*" %%a in ('git branch --show-current') do set BRANCH=%%a
if "!BRANCH!"=="" set BRANCH=main

:: ============================================
:: Migration check
:: ============================================
echo [0/5] Checking for pending migrations...
where alembic >nul 2>&1
if errorlevel 1 (
    echo [WARN] Alembic not installed locally, skipping local migration check.
    echo        Make sure Render Build Command includes: alembic upgrade head
) else (
    :: Auto-generate migration if models changed
    echo Do you want to auto-generate a new migration?
    set /p DO_MIGRATE="(y/N): "
    if /i "!DO_MIGRATE!"=="y" (
        set /p MIG_MSG="Migration message: "
        if "!MIG_MSG!"=="" set MIG_MSG=auto migration
        alembic revision --autogenerate -m "!MIG_MSG!"
        if errorlevel 1 (
            echo [ERROR] Migration generation failed!
            pause
            exit /b 1
        )
        echo [OK] Migration file created. Review it in alembic/versions/
        echo.
    )
)

:: Show status
echo.
echo [1/5] Changes:
git status --short
echo.

:: Build default commit message with current date/time
for /f "tokens=1-3 delims=. " %%a in ('date /t') do set D=%%a.%%b.%%c
for /f "tokens=1-2 delims=: " %%a in ('time /t') do set T=%%a:%%b
set DEFAULT_MSG=deploy %D% %T%

:: Commit message
set /p COMMIT_MSG="Commit message (Enter = !DEFAULT_MSG!): "
if "!COMMIT_MSG!"=="" set COMMIT_MSG=!DEFAULT_MSG!

:: Add
echo.
echo [2/5] Adding files...
git add -A

:: Commit
echo [3/5] Committing...
git commit -m "!COMMIT_MSG!"

:: Push
echo [4/5] Pushing to GitHub (branch: !BRANCH!)...
git push -u origin !BRANCH!
if errorlevel 1 (
    echo.
    echo [ERROR] Push failed.
    pause
    exit /b 1
)

echo.
echo === [5/5] DONE! ===
echo.
echo Render will auto-deploy in 2-5 min.
echo Migrations will run via Build Command: alembic upgrade head
echo.
pause
