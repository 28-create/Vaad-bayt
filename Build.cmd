@echo off
setlocal
cd /d "%~dp0"
echo === Running test suite ===
python -m unittest discover -s tests -v
if errorlevel 1 (
    echo Tests failed! Aborting build.
    if not defined CI pause
    exit /b 1
)
echo === Building dist\VaadBayt.exe ===
python -m PyInstaller --clean --noconfirm VaadBayt.spec
if errorlevel 1 (
    echo PyInstaller build failed!
    if not defined CI pause
    exit /b 1
)
echo === Build succeeded: dist\VaadBayt.exe ===
if not defined CI pause
