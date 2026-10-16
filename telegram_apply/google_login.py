"""One-time Google sign-in for the pipeline's Chrome profile.  Run: python -m telegram_apply.google_login

1. A normal Chrome window opens with a dedicated profile. Sign in to your Google account in it.
2. Close that Chrome window, come back to this terminal and press Enter.
3. The script then checks that the login was really saved.
"""
import os
import shutil
import subprocess
import time
from config import telegram_apply as cfg

CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def signed_in(profile: str) -> bool:
    """Open the profile headless and see whether Google treats it as signed in."""
    from selenium import webdriver
    opts = webdriver.ChromeOptions()
    opts.add_argument(f"--user-data-dir={profile}")
    opts.add_argument("--headless=new")
    d = webdriver.Chrome(options=opts)
    try:
        d.get("https://myaccount.google.com/")
        time.sleep(4)
        return "accounts.google.com" not in d.current_url and "Sign in" not in d.title
    finally:
        d.quit()


chrome = next((p for p in CANDIDATES if os.path.exists(p)), None) or shutil.which("chrome")
if not chrome:
    raise SystemExit("Could not find chrome.exe")
profile = os.path.abspath(cfg.chrome_user_data_dir)
os.makedirs(profile, exist_ok=True)

print(f"Opening Chrome (profile: {profile})")
print("-> Sign in to your Google account in that window.")
print("   If Google offers a passkey / Windows Hello prompt, click 'Try another way' and use your password.")
subprocess.Popen([chrome, f"--user-data-dir={profile}", "--no-first-run", "https://accounts.google.com/"])
input("\nWhen you are fully signed in, CLOSE the Chrome window, then press Enter here... ")

time.sleep(2)
if signed_in(profile):
    print("SUCCESS: Google login saved. The pipeline can now open Google Forms.")
else:
    print("NOT signed in yet. Run this again and finish the sign-in (check the 2-step prompt on your phone), "
          "then close Chrome and press Enter.")
