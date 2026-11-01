@echo off
title Language Translator for Games
cd /d "%~dp0"
echo Canli Oyun Cevirici Baslatiliyor...

where uv >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    uv run python main.py
    goto end
)

if exist "%USERPROFILE%\.local\bin\uv.exe" (
    "%USERPROFILE%\.local\bin\uv.exe" run python main.py
    goto end
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
    goto end
)

python main.py

:end
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Bir hata olustu. Cikis icin bir tusa basin...
    pause
)
