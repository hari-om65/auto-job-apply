"""The daily pipeline: read channel posts in a time window -> pick matching jobs -> tailor resume -> apply."""
import asyncio
import csv
import json
import os
from datetime import date, datetime, timedelta
from telethon import TelegramClient
from config import telegram_apply as cfg
from . import appliers, jobs, resume, settings_store, site_apply

STATE = "telegram_apply/state.json"
RESULTS = "telegram_apply/results.jsonl"
LOG = "all excels/telegram_applications.csv"


def _load_state() -> dict:
    if os.path.exists(STATE):
        with open(STATE) as f:
            return json.load(f)
    return {"seen": [], "day": "", "count": 0}


def _save_state(s: dict) -> None:
    with open(STATE, "w") as f:
        json.dump(s, f)


def record(rec: dict) -> None:
    rec = {"time": datetime.now().isoformat(timespec="seconds"), **rec}
    with open(RESULTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.makedirs("all excels", exist_ok=True)
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([rec["time"], rec.get("job"), rec.get("fit"), rec.get("ats"),
                                rec.get("pdf"), rec.get("status"), ", ".join(rec.get("missing") or [])])


def process_post(text: str, key: str, state: dict, min_ats: int = 0) -> list[dict]:
    """Handle one channel post (it may contain several jobs). Returns one result record per job found."""
    if key in state["seen"]:
        return []
    text = text.replace("**", "").replace("__", "").replace("`", "")  # Telegram bold/italic markup breaks URLs/emails
    state["seen"] = (state["seen"] + [key])[-5000:]
    if state["day"] != str(date.today()):
        state["day"], state["count"] = str(date.today()), 0
    recs = []
    try:
        for job in jobs.extract_jobs(text):
            try:
                recs.append(_process_job(job, state, min_ats))
            except Exception as e:  # one bad job must not stop the others
                rec = {"job": f"{job.get('company')} - {job.get('role')}", "status": f"error: {e!r}"[:220]}
                record(rec)
                recs.append(rec)
    except Exception as e:
        rec = {"job": text[:60].replace("\n", " "), "status": f"error: {e!r}"[:220]}
        record(rec)
        recs.append(rec)
    finally:
        _save_state(state)
    return recs


def _process_job(job: dict, state: dict, min_ats: int) -> dict:
    label = f"{job.get('company')} - {job.get('role')}"
    batch = job.get("batch") or "not stated"

    def skip(reason: str, **extra) -> dict:
        rec = {"job": label, "batch": batch, "status": f"skipped: {reason}", **extra}
        record(rec)
        return rec

    if not jobs.batch_ok(job, cfg.required_batch):
        return skip(f"batch is {batch}, not {cfg.required_batch}")
    routes = job["emails"] or job["google_forms"] or job["linkedin_links"] or job["other_links"]
    if not routes:
        return skip("no apply email or link for this job")
    base = resume.read_base_resume()
    fit = jobs.score_match(job, base)
    score = fit.get("score", 0)
    if not fit.get("eligible", True) or score < cfg.min_match_score:
        return skip("not a good fit", fit=score, note="; ".join(fit.get("reasons", [])[:2]))
    if state["count"] >= cfg.max_applications_per_day:
        return skip("daily limit reached", fit=score)

    tailored, ats, missing = resume.build_tailored_resume(job, base)
    if ats < min_ats:
        return skip(f"resume covers only {ats}% of job keywords", fit=score, ats=ats, missing=missing)
    pdf = resume.render_pdf(tailored, f"{resume.OUT_DIR}/{resume.safe_name(job.get('company'), job.get('role'))}.pdf")
    text_resume = resume.profile_text(tailored)
    send = not cfg.dry_run
    status, manual_links = [], []

    for to in job["emails"][:1]:
        mail = appliers.compose_email(job, resume.email_profile(base), resume.signature_block(tailored))
        if send:
            appliers.send_email(to, mail["subject"], mail["body"], pdf)
        status.append(("emailed " if send else "dry-run: would email ") + to)
    for url in job["google_forms"][:1]:
        status.append("form: " + appliers.fill_google_form(url, job, text_resume, send, pdf))
    if job["linkedin_links"]:
        appliers.queue_linkedin(job, job["linkedin_links"])
        manual_links += job["linkedin_links"]
        status.append("LinkedIn link queued - apply manually")
    if not (job["emails"] or job["google_forms"] or job["linkedin_links"]):
        for url in job["other_links"][:1]:
            try:
                res = site_apply.apply_to_site(url, job, text_resume, pdf, send)
            except Exception as e:
                res = f"error: {type(e).__name__}: {str(e)[:120]}"
            status.append("site: " + res)
            if "manual" in res or res.startswith("error"):
                manual_links.append(url)

    state["count"] += 1
    rec = {"job": label, "batch": batch, "fit": score, "ats": ats, "missing": missing, "pdf": pdf,
           "added_keywords": resume.keywords_added(job, base, tailored),
           "base_resume": os.path.basename(cfg.base_resume_pdf), "status": "; ".join(status),
           "manual_links": manual_links}
    record(rec)
    return rec


def compute_window(s: dict, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Local-time (start, end) of the posts to check, from the window_start/window_end settings."""
    now = now or datetime.now()

    def at(hhmm: str, day: datetime) -> datetime:
        h, m = map(int, hhmm.split(":"))
        return day.replace(hour=h, minute=m, second=0, microsecond=0)

    if s.get("window_start_date") or s.get("window_end_date"):  # explicit dates chosen on the page
        parse = lambda d: datetime.strptime(d, "%Y-%m-%d")
        end_day = parse(s["window_end_date"]) if s.get("window_end_date") else now
        start_day = parse(s["window_start_date"]) if s.get("window_start_date") else end_day
        return at(s["window_start"], start_day), min(at(s["window_end"], end_day), now)
    end = min(at(s["window_end"], now), now)
    start = at(s["window_start"], end)
    if start >= end:
        start -= timedelta(days=1)
    return start, end


async def _run_async(s: dict, log, reprocess: bool = False) -> None:
    client = TelegramClient(cfg.tg_session, cfg.tg_api_id, cfg.tg_api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram is not logged in yet. Run once in a terminal: python -m telegram_apply.login")
        start, end = compute_window(s)
        log(f"Checking posts from {start:%d %b %H:%M} to {end:%d %b %H:%M}")
        wanted = {str(c).lstrip("@").lower() for c in s["channels"]}
        chats = []
        async for dlg in client.iter_dialogs():
            if wanted & {(dlg.name or "").lower(), str(getattr(dlg.entity, "username", "")).lower(), str(dlg.id)}:
                chats.append(dlg.entity)
        if not chats:
            raise RuntimeError(f"Channel(s) {s['channels']} not found in your Telegram chats")

        state = _load_state()
        if reprocess:
            state["seen"] = []  # look at posts again even if they were processed before
        start_u, end_u = start.astimezone(), end.astimezone()
        for chat in chats:
            posts = []
            async for m in client.iter_messages(chat, offset_date=end_u):
                if m.date < start_u:
                    break
                if m.text:
                    posts.append(m)
            log(f"{getattr(chat, 'title', chat)}: {len(posts)} posts in window")
            for m in reversed(posts):
                recs = await asyncio.get_running_loop().run_in_executor(
                    None, process_post, m.text, f"{chat.id}:{m.id}", state, int(s["min_ats_score"]))
                for rec in recs:
                    log(f"{rec['job']} -> {rec['status']}")
    finally:
        await client.disconnect()


def run_once(log=print, reprocess: bool = False) -> None:
    """Run the whole pipeline once with the current UI settings."""
    appliers.GOOGLE_LOGIN_FAILED = False
    s = settings_store.apply_to_config()
    log("Pipeline started" + (" (DRY RUN - nothing will be sent)" if s["dry_run"] else " (LIVE)"))
    asyncio.run(_run_async(s, log, reprocess))
    log("Pipeline finished")
