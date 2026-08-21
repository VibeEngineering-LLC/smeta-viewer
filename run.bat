@echo off
chcp 65001 >nul
cd /d "%~dp0"

py -3 -m sv %*
if errorlevel 9009 python -m sv %*

if errorlevel 1 (
    echo.
    echo Launch failed - see the error message above.
    echo Make sure Python 3.12+ is installed with dependencies from requirements.txt:
    echo   pip install -r requirements.txt
    echo.
    pause
)
