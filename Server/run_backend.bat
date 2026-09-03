@echo off
chcp 65001 >nul
title CS2 Parser - Backend
cd /d "%~dp0"

if not exist "backend\main.py" (
    echo Papka backend ne naydena. Zapuskaite iz kornya proekta.
    pause
    exit /b 1
)

cd /d "%~dp0backend"
if not exist "main.py" (
    echo V papke backend net main.py.
    pause
    exit /b 1
)

where python >nul 2>&1
if %errorlevel% neq 0 (
    where py >nul 2>&1
    if %errorlevel% neq 0 (
        echo Ustanovite Python 3.8+
        pause
        exit /b 1
    )
    py -3 -m pip install -r requirements.txt -q 2>nul
    py -3 -m uvicorn main:app --host 0.0.0.0 --port 8000
) else (
    python -m pip install -r requirements.txt -q 2>nul
    python -m uvicorn main:app --host 0.0.0.0 --port 8000
)

if errorlevel 1 pause
