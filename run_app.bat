@echo off
setlocal
cd /d "%~dp0"
title Quasimorph Ritual Optimizer v0.7.0

echo Quasimorph Ritual Optimizer v0.7.0
echo ===================================
echo.
set "PYTHONPATH=%CD%\src"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 desktop.py
    set "APP_EXIT=%ERRORLEVEL%"
    goto finished
)
where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python desktop.py
    set "APP_EXIT=%ERRORLEVEL%"
    goto finished
)
echo ERROR: Python 3 was not found.
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
