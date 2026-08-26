@echo off
echo ===================================================
echo   Building Installer (.exe) with Inno Setup
echo ===================================================

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
    echo [ERROR] Inno Setup Compiler ^(ISCC.exe^) not found.
    echo Looked in "C:\Program Files\Inno Setup 7", "C:\Program Files ^(x86^)\Inno Setup 7",
    echo the matching Inno Setup 6 folders, and PATH.
    echo Please install Inno Setup from https://jrsoftware.org/isdl.php
    pause
    exit /b 1
)

echo Using compiler: %ISCC_PATH%
"%ISCC_PATH%" installer_setup\setup_builder.iss

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Installer build failed.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ===================================================
echo   Installer Created Successfully!
echo   Location: installer_setup\Output\
echo   ^(filename is StudentPhotoPrintAutomator_Setup_v^<version^>.exe,
echo    taken from MyAppVersion in setup_builder.iss^)
echo ===================================================
pause
