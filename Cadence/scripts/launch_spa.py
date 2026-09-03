"""Launch the SPA dev server detached and poll until it serves the
home page, then print the index HTML so we can see what the SPA
ships and what URLs the user should visit."""
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

OUT = r"C:\Cadence\Cadence\frontend\spa.out"
ERR = r"C:\Cadence\Cadence\frontend\spa.err"

# Kill any existing vite
subprocess.run(
    ["powershell", "-NoProfile", "-Command",
     "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | "
     "Where-Object { $_.CommandLine -like '*vite*' } | "
     "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
    capture_output=True,
)
time.sleep(1)

# Launch detached
with open(OUT, "wb") as out, open(ERR, "wb") as err:
    subprocess.Popen(
        ["cmd", "/c", "cd /d", r"C:\Cadence\Cadence\frontend", "&&", "npm", "run", "dev"],
        stdout=out, stderr=err,
        creationflags=0x00000008,  # DETACHED_PROCESS
    )

# Poll
print("Polling http://127.0.0.1:3000 ...")
ok = False
for i in range(30):
    try:
        with urllib.request.urlopen("http://127.0.0.1:3000", timeout=2) as r:
            body = r.read().decode("utf-8", errors="replace")
            print(f"  hit on attempt {i+1}: status={r.status} len={len(body)}")
            ok = True
            break
    except (urllib.error.URLError, ConnectionError, OSError):
        time.sleep(1)

if not ok:
    print("SPA did not come up in 30s. tail of spa.err:")
    try:
        with open(ERR, "rb") as f:
            print(f.read().decode("utf-8", errors="replace")[-2000:])
    except Exception as e:
        print(f"  could not read err: {e}")
    sys.exit(1)

# Print what we got
print("\n--- index.html (first 500 chars) ---")
print(body[:500])
print("\n--- vite log (spa.out) ---")
try:
    with open(OUT, "rb") as f:
        print(f.read().decode("utf-8", errors="replace")[-1500:])
except Exception:
    pass
