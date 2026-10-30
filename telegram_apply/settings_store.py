"""Settings edited from the web UI. Saved to ui_settings.json and applied on top of config/telegram_apply.py."""
import json
import os
import threading
from config import telegram_apply as cfg

PATH = "telegram_apply/ui_settings.json"

DEFAULTS = {
    "enabled": False,          # run automatically every day
    "run_time": "09:00",       # when the daily run starts (24h, local time)
    "window_start_date": "",   # optional YYYY-MM-DD for the start of the window ("" = automatic)
    "window_end_date": "",     # optional YYYY-MM-DD for the end of the window ("" = automatic)
    "window_start": "18:00",   # check posts from this time ...
    "window_end": "09:00",     # ... until this time (if start > end the window starts the previous day)
    "dry_run": True,           # True = prepare everything, send nothing
    "channels": list(cfg.tg_channels),
    "add_missing_keywords": cfg.add_missing_keywords,   # put missing job keywords in the Skills section
    "required_batch": cfg.required_batch,   # only apply to jobs open to this graduation year ("" = any)
    "min_match_score": cfg.min_match_score,
    "min_ats_score": 0,          # don't apply when the tailored resume covers less than this % of job keywords
    "max_per_day": cfg.max_applications_per_day,
    # LinkedIn: jobs posted in the last 24 hours that match these roles
    "linkedin_enabled": False,                       # run automatically every day
    "linkedin_run_time": "10:00",
    "linkedin_roles": list(cfg.candidate_profile["target_roles"]),
    "linkedin_location": "India",
    "linkedin_external": True,                       # also apply on company sites for non-Easy-Apply jobs
    "linkedin_per_search": 15,                       # max jobs per role per run
    "linkedin_last_run_date": "",
    "last_run_date": "",
    # watch mode: check the channels every few minutes and apply to new posts (no restart, no daily wait)
    "watch_enabled": False,
    "watch_every_min": 15,
    "watch_last_check": "",                          # ISO time up to which posts have been checked
}
_reload_lock = threading.Lock()


def load() -> dict:
    s = dict(DEFAULTS)
    if os.path.exists(PATH):
        with open(PATH, encoding="utf-8-sig") as f:  # tolerate a BOM
            s.update(json.load(f))
    if os.environ.get("DRY_RUN", "").strip():   # cloud runner: a repository variable decides, nothing is saved to disk
        s["dry_run"] = os.environ["DRY_RUN"].strip().lower() in ("1", "true", "yes")
    return s


def save(s: dict) -> dict:
    s = {**load(), **{k: v for k, v in s.items() if k in DEFAULTS}}
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    return s


def _read_config_file() -> dict:
    """Fresh values from config/telegram_apply.py, so edits to it apply on the next run without a restart."""
    ns = {"__name__": cfg.__name__, "__file__": cfg.__file__}
    try:
        with open(cfg.__file__, encoding="utf-8-sig") as f:
            exec(compile(f.read(), cfg.__file__, "exec"), ns)
    except Exception as e:  # a typo in the file must not stop the dashboard: keep the values already loaded
        print(f"config/telegram_apply.py not reloaded ({type(e).__name__}: {e}); using the previous values", flush=True)
        return {}
    return {k: v for k, v in ns.items() if not k.startswith("__")}


def apply_to_config(s: dict | None = None) -> dict:
    """Push the config file and the UI settings into the config module the pipeline reads."""
    s = s or load()
    values = {**_read_config_file(),
              "dry_run": bool(s["dry_run"]),
              "tg_channels": list(s["channels"]),
              "required_batch": str(s["required_batch"]).strip(),
              "add_missing_keywords": bool(s["add_missing_keywords"]),
              "min_match_score": int(s["min_match_score"]),
              "max_applications_per_day": int(s["max_per_day"])}
    if os.environ.get("TG_SESSION_PATH"):  # cloud runner: its own Telegram login, not the file's (the PC's)
        values["tg_session"] = os.environ["TG_SESSION_PATH"]
    with _reload_lock:  # one update: a running job never sees the file's dry_run instead of the UI's
        vars(cfg).update(values)
    return s
