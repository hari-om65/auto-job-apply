"""LinkedIn jobs from the dashboard.

Runs the project's Easy Apply bot (runAiBot.py) with YOUR settings, restricted to jobs posted in the last 24 hours that
match your roles, uploading a resume tailored to each job. External-site jobs are then applied to with the site applier.
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from config import telegram_apply as cfg
from . import resume, settings_store

USER_CONFIG = "user_config.json"
APPLIED_CSV = "all excels/all_applied_applications_history.csv"
FAILED_CSV = "all excels/all_failed_applications_history.csv"
STATE = "telegram_apply/linkedin_state.json"

_proc: subprocess.Popen | None = None
_lock = threading.Lock()


def _identity() -> dict:
    return cfg.candidate_identity


def build_overrides(s: dict) -> dict:
    """user_config.json sections for the bot: your identity, answers, search filters and AI settings."""
    ident, ans = _identity(), cfg.linkedin_answers
    base = resume.read_base_resume()
    facts = "".join(f"{k.replace('_', ' ')}: {v}\n" for k, v in cfg.candidate_facts.items() if v)
    links = resume.base_links()
    roles = [r.strip() for r in s["linkedin_roles"] if r.strip()]
    # the bot's AI layer speaks the OpenAI API: point it at the first configured provider of the model chain
    provider, model = next(((p, m) for p, m in cfg.ai_chain if {"groq": cfg.groq_api_key, "gemini": cfg.gemini_api_key,
                                                                 "openai": cfg.openai_api_key}.get(p)), ("openai", "gpt-4o-mini"))
    ai = {"groq": ("https://api.groq.com/openai/v1", cfg.groq_api_key),
          "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", cfg.gemini_api_key),
          "openai": ("https://api.openai.com/v1/", cfg.openai_api_key)}[provider]
    return {
        "personals": {
            "first_name": ident["first_name"], "middle_name": ident["middle_name"], "last_name": ident["last_name"],
            "phone_number": ident["phone_number"], "current_city": ident["city"], "street": ident.get("street", ""),
            "state": ident["state"], "zipcode": ident["zipcode"], "country": ident["country"],
        },
        "questions": {
            "default_resume_path": "all resumes/default/resume.pdf",
            "years_of_experience": str(ans["years_of_experience"]), "require_visa": ans["require_visa"],
            "legally_authorized": ans["legally_authorized"], "website": links.get("Portfolio", links.get("GitHub", "")),
            "linkedIn": links.get("LinkedIn", ""), "us_citizenship": "Non-citizen allowed to work for any employer",
            "desired_salary": ans["desired_salary"], "current_ctc": ans["current_ctc"], "notice_period": ans["notice_period"],
            "linkedin_headline": "AI Software Engineer | Python, FastAPI, LLM and agentic AI workflows",
            "user_information_all": f"{base}\nFACTS:\n{facts}",
            "recent_employer": "Sorsiri",
            "pause_before_submit": False, "pause_at_failed_question": False,
        },
        "search": {
            "search_terms": roles, "search_location": s["linkedin_location"], "date_posted": "Past 24 hours",
            "sort_by": "Most recent", "easy_apply_only": not s["linkedin_external"],
            "experience_level": ["Internship", "Entry level"], "switch_number": int(s["linkedin_per_search"]),
            "bad_words": [], "about_company_bad_words": [], "current_experience": 1, "did_masters": False,
            "pause_after_filters": False,
        },
        "settings": {
            "cycle_date_posted": False, "alternate_sortby": False, "run_in_background": False,
            "stop_before_submit": bool(s["dry_run"]), "safe_mode": False,
        },
        "secrets": {
            "use_AI": True, "ai_provider": "openai", "llm_model": model, "llm_api_key": ai[1], "llm_api_url": ai[0],
            **({"username": cfg.linkedin_username, "password": cfg.linkedin_password} if cfg.linkedin_username else {}),
        },
    }


def _write_overrides(s: dict) -> None:
    with open(USER_CONFIG, "w", encoding="utf-8") as f:
        json.dump(build_overrides(s), f, indent=2, ensure_ascii=False)
    os.makedirs("all resumes/default", exist_ok=True)
    shutil.copy(cfg.base_resume_pdf, "all resumes/default/resume.pdf")  # the bot's own fallback file must exist


def is_running() -> bool:
    return _proc is not None and _proc.poll() is None


def stop() -> None:
    if is_running():
        _proc.terminate()


def run_once(log=print) -> None:
    """Run the Easy Apply bot, then the external-site jobs it collected."""
    global _proc
    if not _lock.acquire(blocking=False):
        log("LinkedIn run already in progress")
        return
    try:
        s = settings_store.apply_to_config()
        _write_overrides(s)
        log("LinkedIn bot started" + (" (DRY RUN - applications are filled but not submitted)" if s["dry_run"] else " (LIVE)"))
        env = {**os.environ, "JA_TAILOR": "1", "PYTHONIOENCODING": "utf-8",
               "JA_CHROME_PROFILE": os.path.abspath(cfg.chrome_user_data_dir)}
        _proc = subprocess.Popen([sys.executable, "-W", "ignore", "runAiBot.py"], cwd=os.getcwd(), env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 encoding="utf-8", errors="replace")
        for line in _proc.stdout:
            line = line.strip()
            if line:
                log(line[:300])
        code = _proc.wait()
        log(f"LinkedIn bot finished (exit code {code})")
        if s["linkedin_external"]:
            _apply_external(s, log)
    except Exception as e:
        log(f"LinkedIn error: {type(e).__name__}: {e}")
    finally:
        _lock.release()


def _rows(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _apply_external(s: dict, log) -> None:
    """Jobs without Easy Apply: open the company's page and apply with this job's tailored resume."""
    from . import jobs, pipeline, site_apply
    done = set(json.load(open(STATE))["external_done"]) if os.path.exists(STATE) else set()
    today = datetime.now().strftime("%Y-%m-%d")
    todo = [r for r in _rows(APPLIED_CSV)
            if r.get("External Job link", "").startswith("http") and r["Job ID"] not in done
            and (r.get("Date Posted") or "").startswith(today[:7])]
    log(f"{len(todo)} external-site LinkedIn job(s) to apply to")
    base = resume.read_base_resume()
    for r in todo:
        label = f"{r['Company']} - {r['Title']}"
        try:
            job = {"company": r["Company"], "role": r["Title"], "raw": r["About Job"]}
            found = jobs.extract_jobs(f"Company - {r['Company']}\nRole - {r['Title']}\n\n{r['About Job']}"[:12000])
            if found:
                job.update({k: found[0].get(k) for k in ("skills", "responsibilities", "summary")})
            tailored, ats, missing = resume.build_tailored_resume(job, base)
            pdf = resume.render_pdf(tailored, resume.cv_pdf_path(tailored, 'LinkedIn', r['Company'], r['Title']))
            status = site_apply.apply_to_site(r["External Job link"], job, resume.profile_text(tailored), pdf, not s["dry_run"])
            rec = {"job": label, "source": "LinkedIn external", "ats": ats, "pdf": pdf, "status": "site: " + status,
                   "manual_links": [r["External Job link"]] if "manual" in status else [],
                   "added_keywords": resume.keywords_added(job, base, tailored)}
        except Exception as e:
            rec = {"job": label, "source": "LinkedIn external", "status": f"error: {type(e).__name__}: {str(e)[:150]}"}
        pipeline.record(rec)
        log(f"{label} -> {rec['status'][:120]}")
        done.add(r["Job ID"])
        with open(STATE, "w") as f:
            json.dump({"external_done": sorted(done)}, f)


def recent(limit: int = 60) -> list[dict]:
    """Latest LinkedIn applications and skips for the dashboard table (newest first)."""
    out = []
    for r in _rows(APPLIED_CSV):
        easy = r.get("External Job link") == "Easy Applied"
        out.append({"time": (r.get("Date Applied") or r.get("Date Posted") or "")[:16], "title": r["Title"], "company": r["Company"],
                    "status": ("Easy Applied" if easy and r.get("Date Applied", "Pending") != "Pending"
                               else "external site" if not easy else "not submitted (dry run / failed)"),
                    "resume": r.get("Resume", ""), "link": r.get("Job Link", ""), "posted": (r.get("Date Posted") or "")[:16]})
    for r in _rows(FAILED_CSV):
        out.append({"time": (r.get("Date Posted") or "")[:16], "title": "", "company": "", "status": "skipped: " + (r.get("Reason") or r.get("Failed At") or "")[:80],
                    "resume": "", "link": r.get("Job Link", ""), "posted": (r.get("Date Posted") or "")[:16]})
    return out[::-1][:limit]
