"""Settings edited from the web UI. Saved to ui_settings.json and applied on top of config/telegram_apply.py."""
import json
import os
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
    "required_batch": cfg.required_batch,   # only apply to jobs open to this graduation year ("" = any)
    "min_match_score": cfg.min_match_score,
    "min_ats_score": 40,       # don't apply when the tailored resume covers less than this % of job keywords
    "max_per_day": cfg.max_applications_per_day,
    "last_run_date": "",
}


def load() -> dict:
    s = dict(DEFAULTS)
    if os.path.exists(PATH):
        with open(PATH, encoding="utf-8") as f:
            s.update(json.load(f))
    return s


def save(s: dict) -> dict:
    s = {**load(), **{k: v for k, v in s.items() if k in DEFAULTS}}
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    return s


def apply_to_config(s: dict | None = None) -> dict:
    """Push the UI settings into the config module the pipeline reads."""
    s = s or load()
    cfg.dry_run = bool(s["dry_run"])
    cfg.tg_channels = list(s["channels"])
    cfg.required_batch = str(s["required_batch"]).strip()
    cfg.min_match_score = int(s["min_match_score"])
    cfg.max_applications_per_day = int(s["max_per_day"])
    return s
