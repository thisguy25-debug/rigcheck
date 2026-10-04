@echo off
REM Builds "RigCheck.exe" - a single file you can double-click or share.
REM Run this from the folder that contains all the RigCheck .py files.
cd /d "%~dp0"

echo Installing build tools...
python -m pip install --upgrade pyinstaller psutil pillow
if errorlevel 1 (
    echo.
    echo Could not install PyInstaller. Is Python installed and on your PATH?
    pause
    exit /b 1
)

echo.
echo Building the app (this takes a minute or two)...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "RigCheck" rigcheck.py

if exist "dist\RigCheck.exe" (
    echo.
    echo Done! Your app is at: dist\RigCheck.exe
    explorer dist
) else (
    echo.
    echo Build failed - scroll up to see the error.
)
pause
