"""Recreate the private, git-ignored files on the runner from GitHub Actions secrets (run by the workflow)."""
import base64
import os

os.makedirs("config", exist_ok=True)
os.makedirs("telegram_apply", exist_ok=True)


def write(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)
    print(f"restored {path} ({len(data)} bytes)")


need = {"CONFIG_PY": "config/telegram_apply.py", "BASE_RESUME_JSON": "telegram_apply/base_resume.json",
        "TG_RUNNER_SESSION_B64": "telegram_apply/tg_runner.session"}
missing = [k for k in need if not os.environ.get(k)]
if missing:
    raise SystemExit("Missing GitHub secrets: " + ", ".join(missing))
write(need["CONFIG_PY"], os.environ["CONFIG_PY"].encode("utf-8"))
write(need["BASE_RESUME_JSON"], os.environ["BASE_RESUME_JSON"].encode("utf-8"))
write(need["TG_RUNNER_SESSION_B64"], base64.b64decode(os.environ["TG_RUNNER_SESSION_B64"]))
if os.environ.get("UI_SETTINGS_JSON"):
    write("telegram_apply/ui_settings.json", os.environ["UI_SETTINGS_JSON"].encode("utf-8"))
