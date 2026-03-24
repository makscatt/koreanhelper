@echo off
chcp 65001 >nul
python "%~dp0analyze_project.py" "%~dp0."
pause
