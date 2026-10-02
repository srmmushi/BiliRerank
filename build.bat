@echo off
rem ---------------------------------------------------------------------------
rem BiliHook - package the tool into a single exe with PyInstaller.
rem
rem   build.bat
rem
rem Output: dist\BiliHook.exe   (windowed, icon drawn by src\ui\icon.py)
rem The exe keeps settings, scripts and icon next to itself, never inside the
rem PyInstaller extraction dir - see src\core\config.py.
rem ---------------------------------------------------------------------------
setlocal

set PY=C:\app\Python313\python.exe
if not exist "%PY%" set PY=python
set NAME=BiliHook

cd /d "%~dp0"
echo === BiliHook build ===
echo python: %PY%

echo [1/4] pyinstaller
%PY% -m pip install --disable-pip-version-check --quiet pyinstaller
if errorlevel 1 goto :fail

echo [2/4] icon
if not exist "icon.ico" (
    %PY% -c "from src.ui.icon import render; render('icon.ico')"
)
set ICONARG=
if exist "icon.ico" set ICONARG=--icon icon.ico

echo [3/4] building - this takes a couple of minutes
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name %NAME% %ICONARG% ^
    --collect-data siui ^
    --add-data "src\assets\scripts;src\assets\scripts" ^
    --exclude-module tkinter --exclude-module PyQt6 --exclude-module PySide6 ^
    --exclude-module pygame ^
    main.py
if errorlevel 1 goto :fail

echo [4/4] done
dir /b dist
endlocal
exit /b 0

:fail
echo BUILD FAILED
endlocal
exit /b 1
