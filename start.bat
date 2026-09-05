@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM Cadence / Cadence - start backend + frontend
REM ============================================================
echo.

echo ============================================================
echo   Cadence - starting backend + frontend
echo ============================================================
echo.

REM --- 1. kill stale processes -------------------------------------
echo [1/4] killing any stale backend / vite processes...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*uvicorn*cadence.api*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | Where-Object { $_.CommandLine -like '*vite*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
ping 127.0.0.1 -n 3 >nul

REM --- 2. start backend -------------------------------------------
echo [2/4] starting FastAPI backend on port 8000...
cd /d C:\Cadence\Cadence
if exist api.out del api.out >nul 2>&1
if exist api.err del api.err >nul 2>&1
start "Cadence Backend" /MIN "C:\Cadence\Cadence\.venv\Scripts\python.exe" -m uvicorn cadence.api.app:app --host 127.0.0.1 --port 8000 --app-dir "C:\Cadence\Cadence" > api.out 2> api.err
echo       waiting for backend to respond on :8000 (max 30s)...
set /a tries=0
:wait_backend
set /a tries+=1
powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/status' -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue).StatusCode } catch { 0 }" >nul 2>&1
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/status' -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue; exit ($r.StatusCode -ne 200) } catch { exit 1 }" 1>nul 2>nul
if not errorlevel 1 goto backend_done
ping 127.0.0.1 -n 2 >nul
if !tries! lss 30 goto wait_backend
echo       backend did not respond after 30s. Check api.err.
:backend_done
echo       backend ready.
echo.

REM --- 3. start frontend ------------------------------------------
echo [3/4] starting Vite dev server on port 3000...
cd /d C:\Cadence\Cadence\frontend
if exist spa.out del spa.out >nul 2>&1
if exist spa.err del spa.err >nul 2>&1
start "Cadence Frontend" /MIN "C:\Program Files\nodejs\node.exe" "C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js" run dev > spa.out 2> spa.err
echo       waiting for frontend to respond on :3000 (max 30s)...
set /a tries=0
:wait_frontend
set /a tries+=1
powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri 'http://127.0.0.1:3000' -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue).StatusCode } catch { 0 }" >nul 2>&1
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:3000' -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue; exit ($r.StatusCode -ne 200) } catch { exit 1 }" 1>nul 2>nul
if not errorlevel 1 goto frontend_done
ping 127.0.0.1 -n 2 >nul
if !tries! lss 30 goto wait_frontend
echo       frontend did not respond after 30s. Check spa.err.
:frontend_done
echo       frontend ready.
echo.

REM --- 4. open browser --------------------------------------------
echo [4/4] opening demo tabs in browser...
start "" "http://127.0.0.1:3000/#testlab"
ping 127.0.0.1 -n 2 >nul
start "" "https://dashboard.razorpay.com/app/payment-links"
ping 127.0.0.1 -n 1 >nul
start "" "https://web.whatsapp.com"
ping 127.0.0.1 -n 1 >nul
start "" "https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn"
ping 127.0.0.1 -n 1 >nul
start "" "https://supabase.com/dashboard/project/vzrasadomyrycafbzdwg/editor"
ping 127.0.0.1 -n 1 >nul
start "" "https://partners.shopify.com"
ping 127.0.0.1 -n 1 >nul
start "" "https://mail.google.com"

echo.
echo ============================================================
echo   Cadence is live.
echo.
echo     1. Cadence App      : http://127.0.0.1:3000/#testlab
echo     2. Razorpay Live    : https://dashboard.razorpay.com/app/payment-links
echo     3. WhatsApp Web     : https://web.whatsapp.com
echo     4. Twilio Sandbox   : https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn
echo     5. Supabase Studio  : https://supabase.com/dashboard/project/vzrasadomyrycafbzdwg/editor
echo     6. Shopify Partners : https://partners.shopify.com
echo     7. Gmail Invoices   : https://mail.google.com
echo.
echo   Presentation Guide: Open script.pdf or script.md on your phone!
echo   To stop everything, run exit.bat in the same folder.
echo ============================================================
echo.

endlocal
