@echo off
chcp 65001 >nul
title CS2  — настройка сервера
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
    py -3 setup_server.py
) else (
    python setup_server.py
)

if errorlevel 1 pause
