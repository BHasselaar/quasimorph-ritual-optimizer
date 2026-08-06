@echo off
setlocal
cd /d "%~dp0"
py -3.12 -m pip install --upgrade pip
py -3.12 -m pip install -e . pyinstaller
py -3.12 -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name QuasimorphRitualOptimizer ^
  --paths src ^
  --add-data "src\quasimorph_optimizer\data\default_inventory.csv;quasimorph_optimizer\data" ^
  desktop.py
if errorlevel 1 exit /b 1
echo.
echo Built: dist\QuasimorphRitualOptimizer.exe
endlocal
