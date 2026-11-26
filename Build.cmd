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
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    echo === Building Windows Installer dist\VaadBayt-Setup.exe ===
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "installer\VaadBayt.iss"
)
echo === Build succeeded ===
if not defined CI pause
