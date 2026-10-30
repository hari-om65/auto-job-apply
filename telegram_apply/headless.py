"""One-shot run for the cloud (GitHub Actions) or any machine without the dashboard.

    python -m telegram_apply.headless

Reads the Telegram posts since the previous run, tailors a resume per matching job, applies (email / Google Form without
sign-in / company sites) and emails YOU a summary, including links of anything you still have to do by hand.

Environment (all optional):
  TG_SESSION_PATH  Telegram session file (default telegram_apply/tg_runner)
  DRY_RUN          "1"/"true" = prepare only, "0"/"false" = really send (default: the dry_run in ui_settings.json)
  SINCE_HOURS      how far back the very first run looks (default 26)
  JOB_TEXT / JOB_LINK  apply to this one job instead of reading the channels (FORCE=false keeps the batch/fit filters)
Only counts are printed to the log; the details go to your email so a public log never shows job names.
"""
import json
import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.message import EmailMessage
from config import telegram_apply as cfg
from . import pipeline, settings_store

STATE = "telegram_apply/runner_state.json"


def _summary(recs: list[dict], dry: bool, window) -> tuple[str, str]:
    def has(rec, *words):
        return any(w in (rec.get("status") or "") for w in words)

    sent = [r for r in recs if has(r, "emailed ", "form: submitted", "submitted")]
    prepared = [r for r in recs if has(r, "dry-run")]
    manual = [r for r in recs if r.get("manual_links")]
    errors = [r for r in recs if (r.get("status") or "").startswith("error")]
    skipped = [r for r in recs if (r.get("status") or "").startswith("skipped")]
    what = f"Posts window: {window[0]:%d %b %H:%M} -> {window[1]:%d %b %H:%M}" if window else "The job you added"
    lines = [f"{what}   |   mode: {'DRY RUN (nothing was sent)' if dry else 'LIVE'}", ""]

    def block(title, rows, extra=lambda r: ""):
        if rows:
            lines.append(f"{title} ({len(rows)})")
            lines.extend(f"  - {r['job']}: {(r.get('status') or '')[:110]}{extra(r)}" for r in rows)
            lines.append("")

    block("APPLIED / SENT", sent)
    block("PREPARED ONLY (dry run)", prepared)
    block("YOU STILL HAVE TO DO THESE (open the link)", manual, lambda r: "\n      " + "\n      ".join(r["manual_links"]))
    block("ERRORS", errors)
    lines.append(f"Skipped (wrong batch / poor fit / no apply route): {len(skipped)}")
    subject = f"[Job runner] {len(sent)} sent, {len(prepared)} prepared, {len(manual)} need you" + (" (dry run)" if dry else "")
    return subject, "\n".join(lines)


def _email(subject: str, body: str) -> None:
    if not (cfg.smtp_user and cfg.smtp_password):
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg.smtp_user, cfg.smtp_user, subject
    msg.set_content(body)
    with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port) as s:
        s.login(cfg.smtp_user, cfg.smtp_password)
        s.send_message(msg)


def apply_job(s: dict) -> int:
    """Apply to the one job given in JOB_TEXT / JOB_LINK (the "Run workflow" form on GitHub), then email the result."""
    force = os.environ.get("FORCE", "true").strip().lower() in ("1", "true", "yes")
    try:
        recs = pipeline.apply_one(os.environ.get("JOB_TEXT", ""), os.environ.get("JOB_LINK", ""), force, log=lambda msg: None)
    except Exception as e:
        print(f"APPLY FAILED: {type(e).__name__}: {str(e)[:200]}")
        try:
            _email("[Job runner] Could not apply to the job you added", f"{type(e).__name__}: {e}")
        except Exception:
            pass
        return 1
    subject, body = _summary(recs, bool(s["dry_run"]), None)
    try:
        _email(subject, body)
    except Exception as e:
        print("could not email the result:", type(e).__name__)
    print(f"done: {len(recs)} job(s) | {subject}")
    return 0


def main() -> int:
    os.environ.setdefault("JA_HEADLESS", "1")
    s = settings_store.load()          # honours the DRY_RUN environment variable without writing it to disk
    if os.environ.get("JOB_TEXT", "").strip() or os.environ.get("JOB_LINK", "").strip():
        return apply_job(s)
    cfg.tg_session = os.environ.get("TG_SESSION_PATH", "telegram_apply/tg_runner")
    os.makedirs("all excels", exist_ok=True)

    now = datetime.now()
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    since = datetime.fromisoformat(state["last_end"]) if state.get("last_end") else now - timedelta(hours=float(os.environ.get("SINCE_HOURS", 26)))
    window = (since, now)

    first_new = 0
    if os.path.exists(pipeline.RESULTS):
        first_new = sum(1 for _ in open(pipeline.RESULTS, encoding="utf-8"))
    quiet = lambda msg: None
    try:
        pipeline.run_once(quiet, window=window)
    except Exception as e:
        print(f"RUN FAILED: {type(e).__name__}: {str(e)[:200]}")
        try:
            _email("[Job runner] RUN FAILED", f"The scheduled run failed:\n{type(e).__name__}: {e}\n\nNothing was marked as processed; the next run retries the same window.")
        except Exception:
            pass
        return 1

    with open(STATE, "w") as f:
        json.dump({"last_end": now.isoformat(timespec="seconds")}, f)
    recs = []
    if os.path.exists(pipeline.RESULTS):
        recs = [json.loads(l) for i, l in enumerate(open(pipeline.RESULTS, encoding="utf-8")) if i >= first_new and l.strip()]
    subject, body = _summary(recs, bool(s["dry_run"]), window)
    try:
        _email(subject, body)
    except Exception as e:
        print("could not email the summary:", type(e).__name__)
    print(f"done: {len(recs)} jobs looked at | {subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
