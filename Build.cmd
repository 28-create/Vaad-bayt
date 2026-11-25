@echo off
cd /d "%~dp0"
python -m PyInstaller --noconfirm --onefile --windowed --name VaadBayt --add-data "vaad/001.sql;vaad" desktop.py
if errorlevel 1 exit /b 1
