@echo off
chcp 65001 >nul
title CS2 Inventory Parser
cd /d "%~dp0"

where python >nul 2>&1
if %errorlevel% neq 0 (
    where py >nul 2>&1
    if %errorlevel% neq 0 (
        echo Python ne nayden. Ustanovite Python 3.8+ s https://www.python.org/
        echo Pri ustanovke otmetite Add Python to PATH.
        pause
        exit /b 1
    )
    py -3 launcher.py
) else (
    python launcher.py
)

if errorlevel 1 pause
