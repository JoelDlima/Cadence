@echo off
setlocal

REM ============================================================
REM Cadence / Cadence - stop backend + frontend
REM ============================================================
REM Kills any running uvicorn (backend) and vite (frontend)
REM processes for the Cadence project.
REM ============================================================

echo.
echo ============================================================
echo   Cadence - stopping backend + frontend
echo ============================================================
echo.

echo [1/2] killing backend (uvicorn on :8000)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*uvicorn*cadence.api*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 1 /nobreak >nul

echo [2/2] killing frontend (vite on :3000)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | Where-Object { $_.CommandLine -like '*vite*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 1 /nobreak >nul

REM also kill stray npm.cmd / cmd.exe spawned by vite if any
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | Where-Object { $_.CommandLine -like '*npm*' -or $_.CommandLine -like '*vite*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

echo.
echo ============================================================
echo   Cadence stopped.
echo.
echo   Logs preserved at:
echo     C:\Cadence\Cadence\api.out / api.err
echo     C:\Cadence\Cadence\frontend\spa.out / spa.err
echo ============================================================
echo.

endlocal
