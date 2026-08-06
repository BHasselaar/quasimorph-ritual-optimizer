@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%CD%\src
py -3 desktop.py
endlocal
