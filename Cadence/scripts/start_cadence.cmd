@echo off
REM Cadence one-click launcher (Windows).
REM
REM What it does:
REM   1. Kills any process holding port 8000 or 3000 (uvicorn, vite, stale Node/Python)
REM   2. Starts the backend (uvicorn) in a new minimized window
REM   3. Starts the frontend (Vite) in a new minimized window
REM   4. Waits for both to be healthy
REM   5. Opens 3 tabs in Chrome: the SPA, the API health, and the architecture diagram
REM
REM Usage: double-click this file. Press Ctrl+C in the spawned windows to stop.

setlocal

set "REPO_ROOT=%~dp0..\.."
cd /d "%REPO_ROOT%"

set "VENV_PY=%REPO_ROOT%\Cadence\.venv\Scripts\python.exe"
set "VITE_CMD=%REPO_ROOT%\Cadence\frontend\node_modules\.bin\vite.cmd"

echo =====================================================
echo  Cadence - one-click dev launcher
echo =====================================================
echo  This will:
echo    1. kill any process holding ports 8000 or 3000
echo    2. start the backend on :8000
echo    3. start the frontend on :3000
echo    4. open 3 tabs in Chrome
echo.

REM ---------------------------------------------------------------
REM Step 1: kill anything on 8000 or 3000
REM ---------------------------------------------------------------
echo [1/4] killing any stale process on :8000 or :3000 ...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING') do (
    echo       killing pid %%P on :8000
    taskkill /F /PID %%P >nul 2>&1
)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":3000 " ^| findstr LISTENING') do (
    echo       killing pid %%P on :3000
    taskkill /F /PID %%P >nul 2>&1
)
REM Also kill stray uvicorn and vite by name
taskkill /F /IM python.exe /FI "WINDOWTITLE eq Cadence - backend*" >nul 2>&1
taskkill /F /IM node.exe /FI "WINDOWTITLE eq Cadence - frontend*" >nul 2>&1
ping -n 2 127.0.0.1 >nul
echo       done.

REM ---------------------------------------------------------------
REM Step 2: start backend in a new minimized window
REM ---------------------------------------------------------------
echo [2/4] starting backend (uvicorn) on :8000 ...
start "Cadence - backend" /MIN "%VENV_PY%" -m uvicorn revive.api.app:app --host 127.0.0.1 --port 8000 --app-dir "%REPO_ROOT%\Cadence" > "%REPO_ROOT%\Cadence\logs\api.out" 2> "%REPO_ROOT%\Cadence\logs\api.err"
echo       launched.

REM ---------------------------------------------------------------
REM Step 3: start frontend in a new minimized window
REM ---------------------------------------------------------------
echo [3/4] starting frontend (Vite) on :3000 ...
start "Cadence - frontend" /MIN cmd /c "cd /d %REPO_ROOT%\Cadence\frontend && npm run dev -- --host 127.0.0.1 --port 3000" > "%REPO_ROOT%\Cadence\logs\web.out" 2> "%REPO_ROOT%\Cadence\logs\web.err"
echo       launched.

REM ---------------------------------------------------------------
REM Step 4: wait for both, then open Chrome
REM ---------------------------------------------------------------
echo [4/4] waiting for backend and frontend to come up ...

set "BACKEND_OK=0"
set "FRONTEND_OK=0"
for /L %%i in (1,1,30) do (
    ping -n 2 127.0.0.1 >nul
    "%VENV_PY%" -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/status', timeout=1).status==200 else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "BACKEND_OK=1"
    )
    "%VENV_PY%" -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:3000', timeout=1).status==200 else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "FRONTEND_OK=1"
    )
    if "!BACKEND_OK!"=="1" if "!FRONTEND_OK!"=="1" goto :ready
)
:ready

if "!BACKEND_OK!"=="1" if "!FRONTEND_OK!"=="1" (
    echo       both up.
) else (
    echo       WARNING: one of the servers did not come up in 30s.
    echo       check Cadence\logs\api.err and Cadence\logs\web.err
)

echo.
echo Opening 3 tabs in Chrome...
start "" "http://127.0.0.1:3000"
start "" "http://127.0.0.1:8000/api/status"
start "" "file:///%REPO_ROOT%\Cadence\docs\Cadence-architecture.html"
echo.

echo Done. The two server windows are minimized. Close them to stop.
echo Press any key in this window to close the launcher.
pause >nul

endlocal
