@echo off
chcp 65001 >nul
title CS2 Parser - Admin
cd /d "%~dp0"

where python >nul 2>&1
if %errorlevel% neq 0 (
    where py >nul 2>&1
    if %errorlevel% neq 0 (
        echo Python ne nayden. Ustanovite Python 3.8+
        pause
        exit /b 1
    )
    py -3 -m pip install -r requirements.txt -q 2>nul
    py -3 admin_app.py
) else (
    python -m pip install -r requirements.txt -q 2>nul
    python admin_app.py
)

if errorlevel 1 pause