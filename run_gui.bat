@echo off
cd /d "%~dp0"
echo Starting Lead Generation GUI...
echo.

REM Try python first, then python3
python unified_leadgen.py 2>nul
if errorlevel 1 (
    python3 unified_leadgen.py 2>nul
    if errorlevel 1 (
        echo.
        echo ERROR: Python not found!
        echo Please make sure Python is installed and added to your PATH.
        echo.
        echo You can also try running: python unified_leadgen.py
        echo.
        pause
        exit /b 1
    )
)

if errorlevel 1 (
    echo.
    echo An error occurred. Press any key to exit...
    pause >nul
)

