@echo off
chcp 65001 >nul
cd /d "%~dp0"

py -3 -m sv %*
if errorlevel 9009 goto :try_python
if errorlevel 1 goto :missing_deps
goto :eof

:try_python
python -m sv %*
if errorlevel 1 goto :missing_deps
goto :eof

:missing_deps
echo.
echo App did not start - trying to install missing dependencies...
py -3 -m pip install --user -q -r requirements.txt 2>nul
if errorlevel 1 python -m pip install --user -q -r requirements.txt

py -3 -m sv %*
if errorlevel 9009 python -m sv %*

if errorlevel 1 (
    echo.
    echo Launch failed - see the error message above.
    echo Make sure Python 3.12+ is installed, then run manually:
    echo   pip install -r requirements.txt
    echo.
    pause
)
