@echo off
echo ===================================================
echo   Building Installer (.exe) with Inno Setup
echo ===================================================

set ISCC_PATH="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

if not exist %ISCC_PATH% (
    echo [ERROR] Inno Setup Compiler not found at: %ISCC_PATH%
    echo Please install Inno Setup 6 from https://jrsoftware.org/isdl.php
    pause
    exit /b 1
)

%ISCC_PATH% installer_setup\setup_builder.iss

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Installer build failed.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ===================================================
echo   Installer Created Successfully!
echo   Location: installer_setup\Output\StudentPhotoPrintAutomator_Setup_v2.0.exe
echo ===================================================
pause
