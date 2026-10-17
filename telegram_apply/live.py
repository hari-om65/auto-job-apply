"""Put the dashboard on a public https link from this PC.  Run: python -m telegram_apply.live

Starts the dashboard and a free Cloudflare quick tunnel (cloudflared, downloaded once from Cloudflare's official GitHub
releases). Each time the tunnel (re)starts, the new public link is printed, saved to telegram_apply/live_url.txt and
emailed to you (needs the smtp_* settings), so you can always open the dashboard from anywhere.

- The page asks for a login (user: admin, password: telegram_apply/dashboard_password.txt).
- The link changes whenever the tunnel restarts; a stable link needs a Cloudflare account + domain.
- The PC must stay on. While this runs it asks Windows not to go to sleep.
- If the tunnel drops it is restarted automatically.
"""
import ctypes
import os
import re
import smtplib
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from email.message import EmailMessage
from config import telegram_apply as cfg
from . import web

BIN_DIR = "telegram_apply/bin"
EXE = os.path.join(BIN_DIR, "cloudflared.exe" if sys.platform == "win32" else "cloudflared")
URL = ("https://github.com/cloudflare/cloudflared/releases/latest/download/"
       + ("cloudflared-windows-amd64.exe" if sys.platform == "win32" else "cloudflared-linux-amd64"))
PORT = 5055


def ensure_cloudflared() -> str:
    if not os.path.exists(EXE):
        os.makedirs(BIN_DIR, exist_ok=True)
        print("Downloading cloudflared (one time)...", flush=True)
        urllib.request.urlretrieve(URL, EXE)
        os.chmod(EXE, 0o755)
    return EXE


def keep_awake() -> None:
    """Ask Windows not to sleep while the dashboard runs (released automatically when this process exits)."""
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED


def email_link(public: str) -> None:
    if not (cfg.smtp_user and cfg.smtp_password):
        return
    try:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = cfg.smtp_user, cfg.smtp_user, "Job dashboard link"
        msg.set_content(f"Your job dashboard is live at:\n{public}\n\nLogin: admin / (your dashboard password)\n"
                        "The link changes whenever the dashboard restarts; you get a new email each time.")
        with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port) as s:
            s.login(cfg.smtp_user, cfg.smtp_password)
            s.send_message(msg)
        print("Link emailed to", cfg.smtp_user, flush=True)
    except Exception as e:
        print("Could not email the link:", type(e).__name__, flush=True)


def watchdog(proc: subprocess.Popen, public: str) -> None:
    """Free quick tunnels sometimes die silently. If the public link stops answering, kill the tunnel so it restarts."""
    time.sleep(90)  # a new link needs a moment before it resolves
    bad = 0
    while proc.poll() is None:
        try:
            urllib.request.urlopen(public, timeout=20)
            bad = 0
        except urllib.error.HTTPError as e:
            bad = bad + 1 if e.code in (502, 503, 504, 530) else 0   # 401 = the login page = healthy
        except Exception:
            bad += 1
        if bad >= 3:
            print("Public link stopped answering, restarting the tunnel...", flush=True)
            proc.kill()
            return
        time.sleep(60)


def run_tunnel(password: str) -> None:
    proc = subprocess.Popen([ensure_cloudflared(), "tunnel", "--url", f"http://127.0.0.1:{PORT}", "--no-autoupdate"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    announced = False
    for line in proc.stdout:
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
        if m and not announced:
            announced = True
            public = m.group(0)
            with open("telegram_apply/live_url.txt", "w") as f:
                f.write(public)
            print("\n" + "=" * 60 + f"\nLIVE DASHBOARD: {public}\nlogin: admin   password: {password}\n" + "=" * 60, flush=True)
            threading.Thread(target=email_link, args=(public,), daemon=True).start()
            threading.Thread(target=watchdog, args=(proc, public), daemon=True).start()
    proc.wait()


def main() -> None:
    keep_awake()
    password = web.dashboard_password()
    threading.Thread(target=web.scheduler, daemon=True).start()
    threading.Thread(target=lambda: web.app.run(host="127.0.0.1", port=PORT, threaded=True), daemon=True).start()
    time.sleep(2)
    while True:  # restart the tunnel whenever it drops
        run_tunnel(password)
        print("Tunnel stopped, restarting in 5s...", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("stopped")
