@echo off
chcp 65001 >nul

:: Сохраняем путь к папке скрипта
set "PROJECT_DIR=%~dp0"

python "%PROJECT_DIR%analyze_project.py" "%PROJECT_DIR%."

pause
