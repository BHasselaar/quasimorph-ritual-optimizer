@echo off
setlocal
cd /d "%~dp0"
title Quasimorph Ritual Optimizer v0.7.15

echo Quasimorph Ritual Optimizer v0.7.15
echo ===================================
echo.
set "PYTHONPATH=%CD%\src"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3.11 -c "import UnityPy, TypeTreeGeneratorAPI, numpy" >nul 2>nul
    if errorlevel 1 (
        echo ERROR: Dependencies are missing from Python 3.11.
        echo Run: py -3.11 -m pip install -e .
        set "APP_EXIT=1"
        goto finished
    )
    py -3.11 desktop.py
    set "APP_EXIT=%ERRORLEVEL%"
    goto finished
)
where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python desktop.py
    set "APP_EXIT=%ERRORLEVEL%"
    goto finished
)
echo ERROR: Python 3.11 launcher was not found.
set "APP_EXIT=9009"

:finished
echo.
echo Application exit code: %APP_EXIT%
if not "%APP_EXIT%"=="0" (
    echo The application stopped with an error.
    echo Send startup_error.log or the error above to ChatGPT.
)
echo.
pause
exit /b %APP_EXIT%
