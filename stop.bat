@echo off
echo Stopping Video Studio...

:: Kill bridge (pythonw.exe running worker.bridge.server)
for /f "tokens=2" %%p in ('netstat -ano ^| findstr ":5161 " ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)

:: Kill Vite dev server
for /f "tokens=2" %%p in ('netstat -ano ^| findstr ":5160 " ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)

echo Done.
timeout /t 2 /nobreak >nul
