@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    python -m vaad
) else (
    py -3 -m vaad
)
if errorlevel 1 pause
