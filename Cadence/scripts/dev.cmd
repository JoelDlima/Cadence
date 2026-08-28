@echo off
REM Cadence one-command dev launcher (Windows).
REM Brings up: FastAPI on :8000, Vite dev server on :3000.
REM Press Ctrl+C in this window to stop both.
REM
REM Usage:  Cadence\scripts\dev.cmd

setlocal

set "REPO_ROOT=%~dp0..\.."
cd /d "%REPO_ROOT%"

echo ====================================================
echo Cadence dev launcher
echo ====================================================
echo Backend : http://127.0.0.1:8000  (FastAPI + uvicorn)
echo Frontend: http://127.0.0.1:3000  (Vite + React)
echo.

REM Ensure the venv exists. If not, create it.
if not exist "Cadence\.venv\Scripts\python.exe" (
    echo [setup] creating Cadence\.venv ...
    python -m venv Cadence\.venv
    if errorlevel 1 goto :fail
)

REM Ensure the frontend deps are installed. If not, install.
if not exist "Cadence\frontend\node_modules" (
    echo [setup] running npm install in Cadence\frontend ...
    pushd "Cadence\frontend"
    call npm install
    if errorlevel 1 popd & goto :fail
    popd
)

REM Ensure the Python package is editable-installed (so `import revive` works).
echo [setup] ensuring Cadence is pip-installed (editable) ...
"Cadence\.venv\Scripts\python.exe" -m pip install -q -e "Cadence\.[dev]"
if errorlevel 1 goto :fail

REM Ensure a .env exists. If not, copy from the example.
if not exist "Cadence\.env" (
    echo [setup] copying Cadence\.env.example to Cadence\.env
    copy /Y "Cadence\.env.example" "Cadence\.env" >nul
)

REM Make sure the logs dir exists.
if not exist "Cadence\logs" mkdir "Cadence\logs"

echo.
echo Starting backend (FastAPI) on :8000 ...
start "cadence-api" /B "Cadence\.venv\Scripts\python.exe" -m uvicorn revive.api.app:app --host 127.0.0.1 --port 8000 --app-dir Cadence > "Cadence\logs\api.out" 2> "Cadence\logs\api.err"

echo Starting frontend (Vite) on :3000 ...
start "cadence-web" /B cmd /c "cd /d Cadence\frontend && npm run dev -- --host 127.0.0.1 --port 3000 > ..\logs\web.out 2> ..\logs\web.err"

REM Wait for backend to come up.
echo Waiting for backend to be ready ...
set /a TRIES=0
:wait
set /a TRIES+=1
if %TRIES% GTR 30 (
    echo [warn] backend did not respond in 15s; check Cadence\logs\api.err
    goto :ready
)
"Cadence\.venv\Scripts\python.exe" -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/status', timeout=1).status == 200 else 1)" 2>nul
if not errorlevel 1 goto :ready
ping -n 1 127.0.0.1 >nul
goto :wait

:ready
echo.
echo Cadence is up.  Press Ctrl+C in this window to stop.
echo.
echo Try:
echo   curl http://127.0.0.1:8000/api/status
echo   open http://127.0.0.1:3000 in your browser
echo.

REM If you want a seed journey for the demo, uncomment the next line:
"Cadence\.venv\Scripts\python.exe" Cadence\scripts\seed.py

REM Keep this window alive; closing it kills both children.
pause
goto :eof

:fail
echo.
echo [error] setup failed; see output above.
exit /b 1
