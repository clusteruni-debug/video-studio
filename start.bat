@echo off
title Video Studio
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1

echo Starting Video Studio...

:: Clean bytecode cache (stale pyc causes code changes to not take effect)
for /d /r worker %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul

:: Start bridge server (detached, minimized, -B = no bytecode cache)
start "VS-Bridge" /min .venv\Scripts\pythonw.exe -B -m worker.bridge.server

:: Wait for bridge to be ready
timeout /t 4 /nobreak >nul

:: Start Vite dev server
start "VS-Vite" /min cmd /c "npm run dev"

timeout /t 2 /nobreak >nul

echo.
echo ========================================
echo   Video Studio Ready!
echo   UI:     http://127.0.0.1:5160
echo   Bridge: http://127.0.0.1:5161
echo ========================================
echo.
echo Press any key to open browser...
pause >nul
start http://127.0.0.1:5160
