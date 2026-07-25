@echo off
REM ===========================================================================
REM  build.bat -- build a standalone AE Graph Forge executable on Windows.
REM
REM    build.bat            one-folder build (fast to start, a folder to ship)
REM    build.bat onefile    single .exe (slower first launch, one file)
REM    build.bat clean      remove build artefacts and exit
REM
REM  Output lands in dist\AEGraphForge\.
REM ===========================================================================
setlocal enabledelayedexpansion

set APPNAME=AEGraphForge
set ENTRY=run.py

if /I "%~1"=="clean" (
    echo Cleaning...
    if exist build rmdir /s /q build
    if exist dist rmdir /s /q dist
    if exist %APPNAME%.spec del /q %APPNAME%.spec
    echo Done.
    exit /b 0
)

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: python is not on PATH. Install Python 3.9+ and try again.
    exit /b 1
)

echo === Installing build dependencies ===
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo ERROR: dependency install failed.
    exit /b 1
)

set MODE=--onedir
if /I "%~1"=="onefile" set MODE=--onefile

echo === Building %APPNAME% (%MODE%) ===
python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    %MODE% ^
    --windowed ^
    --name %APPNAME% ^
    --add-data "presets;presets" ^
    --exclude-module tkinter ^
    --exclude-module matplotlib ^
    --exclude-module numpy ^
    --exclude-module PySide6.QtWebEngineCore ^
    --exclude-module PySide6.QtWebEngineWidgets ^
    --exclude-module PySide6.Qt3DCore ^
    --exclude-module PySide6.QtMultimedia ^
    --exclude-module PySide6.QtQuick ^
    --exclude-module PySide6.QtQml ^
    %ENTRY%

if errorlevel 1 (
    echo ERROR: build failed.
    exit /b 1
)

echo.
echo === Build complete ===
if /I "%~1"=="onefile" (
    echo   dist\%APPNAME%.exe
) else (
    echo   dist\%APPNAME%\%APPNAME%.exe
)
exit /b 0
