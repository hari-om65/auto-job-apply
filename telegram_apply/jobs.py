"""Turn a raw Telegram post into a structured job, and score it against the candidate."""
import json
import re
from . import llm
from config import telegram_apply as cfg

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_RE = re.compile(r"https?://[^\s<>\"')]+")


def extract_jobs(text: str) -> list[dict]:
    """A post may list several jobs (1), 2), 3)...). Return one dict per job listing; [] if none."""
    data = llm.chat_json(
        "You parse job posts from a Telegram channel. ONE post may contain MANY job listings (numbered or separated); "
        "return every listing separately. Reply JSON {\"jobs\": [ ... ]} where each job has keys: company, role, "
        "batch (graduation years eligible, e.g. '2026/2027', copied from the listing or from a post-wide header), "
        "location, stipend_or_salary, experience, skills (required skills/tools as SHORT keywords of 1-3 words, e.g. 'SQL', 'Power BI', 'REST APIs' - never sentences), "
        "responsibilities (list), summary (1-2 sentences), apply_emails (emails to send the resume to FOR THAT LISTING), "
        "apply_links (URLs to apply FOR THAT LISTING; if the post has one shared email/link, put it on every job). "
        "Skip non-job content (ads, greetings, tips). Use null / [] for unknown. Return {\"jobs\": []} if there are none.",
        text[:14000],
        temperature=0,
    )
    out = []
    for j in data.get("jobs") or []:
        if not isinstance(j, dict) or not (j.get("role") or j.get("company")):
            continue
        # keep only contacts that really appear in the post (guards against invented ones)
        emails = [e.strip().rstrip(".,*_`") for e in (j.get("apply_emails") or []) if isinstance(e, str)]
        emails = [e for e in emails if e in text and EMAIL_RE.fullmatch(e)]
        post_urls = [u.rstrip(".,)") for u in URL_RE.findall(text)]
        urls = [u.strip().rstrip(".,)*_`>]") for u in (j.get("apply_links") or []) if isinstance(u, str)]
        urls = [u for u in urls if u in post_urls or u in text]
        j["emails"] = emails
        j["google_forms"] = [u for u in urls if "docs.google.com/forms" in u or "forms.gle" in u]
        j["linkedin_links"] = [u for u in urls if "linkedin.com/" in u]
        j["other_links"] = [u for u in urls if u not in j["google_forms"] + j["linkedin_links"]]
        j["skills"] = j.get("skills") or []
        j["raw"] = text
        out.append(j)
    return out


def batch_ok(job: dict, year: str) -> bool:
    """True if the job is open to the required graduation year (empty year = no filter)."""
    if not year:
        return True
    batch = str(job.get("batch") or "")
    if batch.strip():
        return year in batch
    return year in job.get("raw", "")  # batch not stated for this listing: accept only if the post mentions the year


def score_match(job: dict, resume_text: str) -> dict:
    """AI fit score of this resume/profile for this job."""
    return llm.chat_json(
        "You screen candidates. Given the candidate profile, resume and job, reply JSON: "
        "score (0-100 fit based on skills, projects and role relevance), eligible (bool), reasons (list of short strings). "
        "The candidate is willing to relocate ANYWHERE and has no minimum pay: NEVER mark a job ineligible or lower the "
        "score because of its city, remote/on-site mode or stipend. Set eligible=false only if the role is clearly "
        "unrelated to the candidate's field (e.g. sales, HR, design) .",
        json.dumps({"profile": {k: v for k, v in cfg.candidate_profile.items() if k not in ("locations", "min_monthly_stipend_inr")},
                    "facts": cfg.candidate_facts, "resume": resume_text[:8000],
                    "job": {k: job.get(k) for k in ("company", "role", "batch", "location",
                                                     "stipend_or_salary", "experience", "skills")}}),
        temperature=0,
    )
