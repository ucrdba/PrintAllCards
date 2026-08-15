@echo off
REM ===================================================
REM   Student Photo Print Automator - Full Build Script
REM   Builds PyInstaller EXE & Inno Setup Installer
REM ===================================================

REM Always navigate to project root directory where build_all.cmd is located
cd /d "%~dp0"

REM Suppress setuptools pkg_resources UserWarning during PyInstaller compilation
set PYTHONWARNINGS=ignore

echo [1/2] Building PyInstaller Standalone Executable...
pyinstaller --clean StudentPhotoPrintAutomator.spec

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] PyInstaller compilation failed!
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [2/2] Compiling Windows Setup Installer with Inno Setup...
set ISCC_PATH="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

if not exist %ISCC_PATH% (
    echo.
    echo [ERROR] Inno Setup Compiler not found at %ISCC_PATH%
    echo Please download and install Inno Setup 6 from: https://jrsoftware.org/isdl.php
    pause
    exit /b 1
)

%ISCC_PATH% installer_setup\setup_builder.iss

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Inno Setup compilation failed!
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo =========================================================
echo   SUCCESS! ALL BUILD ARTIFACTS CREATED SUCCESSFULLY:
echo   - Executable: dist\StudentPhotoPrintAutomator.exe
echo   - Installer:  installer_setup\Output\StudentPhotoPrintAutomator_Setup_v2.0.exe
echo =========================================================
pause
