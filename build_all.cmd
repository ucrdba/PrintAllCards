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

REM Locate the Inno Setup compiler. Newest first, then PATH, so the script keeps
REM working whether Inno Setup 7 or 6 is installed and in either Program Files.
set "ISCC_PATH="
for %%P in (
    "C:\Program Files\Inno Setup 7\ISCC.exe"
    "C:\Program Files (x86)\Inno Setup 7\ISCC.exe"
    "C:\Program Files\Inno Setup 6\ISCC.exe"
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
) do if not defined ISCC_PATH if exist %%P set "ISCC_PATH=%%~P"

if not defined ISCC_PATH (
    for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do if not defined ISCC_PATH set "ISCC_PATH=%%I"
)

if not defined ISCC_PATH (
    echo.
    echo [ERROR] Inno Setup Compiler ^(ISCC.exe^) not found.
    echo Looked in "C:\Program Files\Inno Setup 7", "C:\Program Files ^(x86^)\Inno Setup 7",
    echo the matching Inno Setup 6 folders, and PATH.
    echo Please download and install Inno Setup from: https://jrsoftware.org/isdl.php
    pause
    exit /b 1
)

echo Using compiler: %ISCC_PATH%
"%ISCC_PATH%" installer_setup\setup_builder.iss

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
echo   - Installer:  installer_setup\Output\
echo     ^(StudentPhotoPrintAutomator_Setup_v^<version^>.exe, from
echo      MyAppVersion in setup_builder.iss^)
echo =========================================================
pause
