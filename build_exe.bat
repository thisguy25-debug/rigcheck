@echo off
REM Builds "RigCheck.exe" - a single file you can double-click or share.
REM Run this from the folder that contains all the RigCheck .py files.
cd /d "%~dp0"

REM Temporary build files go in a local folder that OneDrive doesn't sync,
REM so file locks from syncing can't break the build.
set "WORK=%LOCALAPPDATA%\RigCheckBuild"

echo Closing RigCheck if it's running...
taskkill /im RigCheck.exe /f >nul 2>&1

echo Installing build tools...
python -m pip install --upgrade pyinstaller psutil pillow certifi
if errorlevel 1 (
    echo.
    echo Could not install PyInstaller. Is Python installed and on your PATH?
    pause
    exit /b 1
)

if exist "%WORK%" rmdir /s /q "%WORK%"

echo.
echo Building the app (this takes a minute or two)...
python -m PyInstaller --noconfirm --onefile --windowed --name "RigCheck" ^
    --workpath "%WORK%\build" --specpath "%WORK%" --distpath "%~dp0dist" --hidden-import certifi rigcheck.py

if exist "dist\RigCheck.exe" (
    echo.
    echo Done! Your app is at: dist\RigCheck.exe
    explorer dist
) else (
    echo.
    echo Build failed - scroll up to see the error.
    echo If it says "Access is denied", move this folder out of OneDrive ^(for example to C:\RigCheck^) and try again.
)
pause
