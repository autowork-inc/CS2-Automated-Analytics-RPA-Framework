@echo off
chcp 65001 >nul
title CS2 - Bot
cd /d "%~dp0"

if not exist "bot\bot.py" (
    echo Papka bot ne naydena. Zapuskaite iz kornya proekta.
    pause
    exit /b 1
)

cd /d "%~dp0bot"
where python >nul 2>&1
if %errorlevel% neq 0 (
    where py >nul 2>&1
    if %errorlevel% neq 0 (
        echo Ustanovite Python 3.8+
        pause
        exit /b 1
    )
    py -3 -m pip install -r requirements.txt -q 2>nul
    py -3 bot.py
) else (
    python -m pip install -r requirements.txt -q 2>nul
    python bot.py
)

if errorlevel 1 pause
