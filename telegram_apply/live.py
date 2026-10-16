"""Put the dashboard on a public https link from this PC.  Run: python -m telegram_apply.live

Starts the dashboard and a free Cloudflare quick tunnel (cloudflared, downloaded once from Cloudflare's official GitHub
releases) and prints the public URL. The page asks for a login (user: admin, password: telegram_apply/dashboard_password.txt).
The link changes every time this is started. The PC must stay on and awake for the dashboard and its schedules to run.
"""
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from . import web

BIN_DIR = "telegram_apply/bin"
EXE = os.path.join(BIN_DIR, "cloudflared.exe" if sys.platform == "win32" else "cloudflared")
URL = ("https://github.com/cloudflare/cloudflared/releases/latest/download/"
       + ("cloudflared-windows-amd64.exe" if sys.platform == "win32" else "cloudflared-linux-amd64"))
PORT = 5055


def ensure_cloudflared() -> str:
    if not os.path.exists(EXE):
        os.makedirs(BIN_DIR, exist_ok=True)
        print("Downloading cloudflared (one time)...")
        urllib.request.urlretrieve(URL, EXE)
        os.chmod(EXE, 0o755)
    return EXE


def main() -> None:
    password = web.dashboard_password()
    threading.Thread(target=web.scheduler, daemon=True).start()
    threading.Thread(target=lambda: web.app.run(host="127.0.0.1", port=PORT, threaded=True), daemon=True).start()
    time.sleep(2)
    proc = subprocess.Popen([ensure_cloudflared(), "tunnel", "--url", f"http://127.0.0.1:{PORT}", "--no-autoupdate"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    public = None
    for line in proc.stdout:
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
        if m and not public:
            public = m.group(0)
            with open("telegram_apply/live_url.txt", "w") as f:
                f.write(public)
            print("\n" + "=" * 60)
            print(f"LIVE DASHBOARD: {public}")
            print(f"login: admin   password: {password}")
            print("=" * 60 + "\nKeep this window open. Press Ctrl+C to stop.\n", flush=True)
    proc.wait()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("stopped")
