@echo off
rem ---------------------------------------------------------------------------
rem BiliRerank - package into a single CONSOLE exe, then keep ONLY the exe in the
rem project folder. Every PyInstaller product (build/, dist/, *.spec and
rem __pycache__) is removed so the directory stays clean. The exe is self-contained;
rem on first run it writes settings.json next to itself.
rem ---------------------------------------------------------------------------
setlocal

set PY=C:\app\Python313\python.exe
if not exist "%PY%" set PY=python
set NAME=BiliRerank

cd /d "%~dp0"
echo === BiliRerank build ===
echo python: %PY%

echo [1/4] pyinstaller
"%PY%" -m pip install --disable-pip-version-check --quiet pyinstaller
if errorlevel 1 goto :fail

echo [2/4] building console exe - this takes a couple of minutes
"%PY%" -m PyInstaller --noconfirm --clean --onefile --name %NAME% ^
    --exclude-module tkinter --exclude-module PyQt5 --exclude-module PyQt6 ^
    --exclude-module PySide6 --exclude-module PyQt-SiliconUI --exclude-module siui ^
    --exclude-module numpy --exclude-module PIL --exclude-module matplotlib ^
    main.py
if errorlevel 1 goto :fail

echo [3/4] collect exe into the project folder
if exist "%NAME%.exe" del /q "%NAME%.exe"
copy /y "dist\%NAME%.exe" "%NAME%.exe" >nul
if not exist "%NAME%.exe" goto :fail

echo [4/4] remove all build products, keep only the exe
rd /s /q build 2>nul
rd /s /q dist 2>nul
if exist "%NAME%.spec" del /q "%NAME%.spec"
for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul
del /s /q *.pyc 2>nul

echo done: %NAME%.exe
endlocal
exit /b 0

::fail
echo BUILD FAILED
endlocal
exit /b 1
