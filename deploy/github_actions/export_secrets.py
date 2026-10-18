"""Run on YOUR PC (never in the cloud). Walks you through creating the GitHub secrets, one at a time:
it copies each value to the clipboard, you paste it as a secret on GitHub.
    python deploy/github_actions/export_secrets.py <you>/<private-runner-repo>
"""
import base64
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import webbrowser

sys.path.insert(0, os.getcwd())
from telegram_apply import resume  # noqa: E402

REPO = sys.argv[1] if len(sys.argv) > 1 else input("Your PRIVATE runner repo (e.g. hari-om65/auto-job-apply-runner): ").strip()
SESSION = "telegram_apply/tg_runner.session"


def compact_session(path: str) -> bytes:
    """Telegram session with only the login (auth key) kept: the cached chat list can make it 10x bigger."""
    out = os.path.join(tempfile.mkdtemp(), "s.session")
    src, dst = sqlite3.connect(path), sqlite3.connect(out)
    for name, ddl in src.execute("select name, sql from sqlite_master where type='table' and sql is not null").fetchall():
        dst.execute(ddl)
        if name in ("version", "sessions"):
            rows = src.execute(f"select * from {name}").fetchall()
            if rows:
                dst.executemany(f"insert into {name} values ({','.join('?' * len(rows[0]))})", rows)
    dst.commit()
    dst.execute("vacuum")
    dst.close()
    src.close()
    return open(out, "rb").read()


def clip(text: str) -> None:
    subprocess.run(["clip"], input=text.encode("utf-16"), check=True)


values = {
    "CONFIG_PY": open("config/telegram_apply.py", encoding="utf-8-sig").read(),
    "BASE_RESUME_JSON": json.dumps({"text": resume.read_base_resume(), "links": resume.base_links()}, ensure_ascii=False),
}
if os.path.exists(SESSION):
    values["TG_RUNNER_SESSION_B64"] = base64.b64encode(compact_session(SESSION)).decode()
else:
    print(f"- {SESSION} not found: run  python -m telegram_apply.login runner  first (a separate Telegram login for the cloud).")
if os.path.exists("telegram_apply/ui_settings.json"):
    values["UI_SETTINGS_JSON"] = open("telegram_apply/ui_settings.json", encoding="utf-8-sig").read()

webbrowser.open(f"https://github.com/{REPO}/settings/secrets/actions/new")
for name, value in values.items():
    if len(value) > 48000:
        raise SystemExit(f"{name} is {len(value)} characters; GitHub secrets allow 48,000.")
    clip(value)
    input(f"\n[{name}] copied to the clipboard ({len(value)} chars).\n"
          f"  On GitHub: 'New repository secret' -> Name: {name} -> paste the value -> Add secret.\n  Press Enter for the next one... ")
print("\nDone. Next: Actions tab -> 'Daily job run' -> Run workflow. Keep these values private.")
