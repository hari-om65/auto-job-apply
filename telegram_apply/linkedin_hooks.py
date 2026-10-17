"""Hooks the LinkedIn Easy Apply bot (runAiBot.py) calls in dashboard mode: role-fit check and per-job tailored resume."""
import os
from . import jobs, resume
from config import telegram_apply as cfg

_fit_cache: dict = {}
_pdf_cache: dict = {}
_base: str | None = None


def _base_text() -> str:
    global _base
    if _base is None:
        _base = resume.read_base_resume()
    return _base


def _job(title: str, company: str, description: str) -> dict:
    """Structured job (skills, responsibilities...) from a LinkedIn posting."""
    found = jobs.extract_jobs(f"Company - {company}\nRole - {title}\n\n{description}"[:12000])
    job = dict(found[0]) if found else {}
    job.update({"company": company, "role": title, "skills": job.get("skills") or [], "raw": description})
    return job


def fit_ok(title: str, company: str, description: str) -> tuple[bool, str]:
    """Is this LinkedIn job aligned with your target roles? Used to skip the rest before applying."""
    key = (title, company)
    if key not in _fit_cache:
        try:
            job = _job(title, company, description)
            fit = jobs.score_match(job, _base_text())
            ok = bool(fit.get("eligible", True)) and int(fit.get("score", 0)) >= cfg.min_match_score
            why = f"fit {fit.get('score')}: " + "; ".join(fit.get("reasons", [])[:2])
            _fit_cache[key] = (ok, why)
        except Exception as e:  # an AI hiccup must not make the bot apply blindly or crash
            _fit_cache[key] = (False, f"could not assess fit ({type(e).__name__})")
    return _fit_cache[key]


def tailored_pdf(title: str, company: str, description: str) -> str | None:
    """Resume PDF written for exactly this job (cached per job). None if it could not be built."""
    key = (title, company)
    if key not in _pdf_cache:
        try:
            job = _job(title, company, description)
            tailored, _ats, _missing = resume.build_tailored_resume(job, _base_text())
            path = resume.cv_pdf_path(tailored, "LinkedIn", company, title)
            _pdf_cache[key] = os.path.abspath(resume.render_pdf(tailored, path))
        except Exception:
            _pdf_cache[key] = None
    return _pdf_cache[key]
