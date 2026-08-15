@echo off
echo ===================================================
echo   Building Student Photo Print Automator Executable
echo ===================================================

echo Cleaning past build outputs...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

echo Running PyInstaller single-file build...
python -m PyInstaller --clean StudentPhotoPrintAutomator.spec

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PyInstaller build failed.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ===================================================
echo   Executable Built Successfully!
echo   Location: dist\StudentPhotoPrintAutomator.exe
echo ===================================================
pause
