"""Read the base resume, tailor it to a job (truthfully), score it for ATS keywords, render an ATS-safe one-page PDF
that fills the page."""
import functools
import io
import json
import os
import re
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, HRFlowable
from . import llm
from config import telegram_apply as cfg

OUT_DIR = "telegram_apply/output"
MIN_FILL = 0.86      # a resume must fill at least this share of the page (at the largest allowed type size)
HARD_MIN_FILL = 0.75  # below this after retries the job is NOT applied to
KMAX = 1.12          # largest type scale used to fill a page
KMIN = 0.95          # smallest type scale we like (body text about 8.6pt)
KFLOOR = 0.90        # absolute floor for the PDF so a long resume still fits on one page
ACCENT = colors.HexColor("#1f3b63")


def read_base_resume() -> str:
    if not os.path.exists(cfg.base_resume_pdf):
        raise FileNotFoundError(f"Put your resume PDF at {cfg.base_resume_pdf}")
    return "\n".join(p.extract_text() or "" for p in PdfReader(cfg.base_resume_pdf).pages)


@functools.lru_cache(maxsize=1)
def base_links() -> dict:
    """LinkedIn / GitHub / Portfolio URLs from the hyperlinks embedded in the base resume PDF."""
    found = {}
    for page in PdfReader(cfg.base_resume_pdf).pages:
        for a in page.get("/Annots") or []:
            uri = str((a.get_object().get("/A") or {}).get("/URI") or "")
            host_path = re.sub(r"^https?://(www\.)?", "", uri)
            if not uri.startswith("http"):
                continue
            if host_path.startswith("linkedin.com/in/"):
                found.setdefault("LinkedIn", uri)
            elif re.fullmatch(r"github\.com/[^/]+/?", host_path):
                found.setdefault("GitHub", uri)
            elif "github.io" in host_path or host_path.count("/") <= 1 and "drive.google" not in host_path \
                    and "github.com" not in host_path and "linkedin" not in host_path:
                found.setdefault("Portfolio", uri)
    return found


BOOST_RULE = (" ADDITIONAL RULE (the candidate opted in and will learn these before interviews): add EVERY job keyword "
              "you could not support from the resume to the skills list as plain skill names. Skills section ONLY - never "
              "mention them in experience bullets, projects, summary or certifications, and never invent employers, "
              "metrics or dates. Return them in 'added_keywords'.")


def resume_ok(r: dict, base_text: str = "") -> bool:
    """A usable resume is complete: summary, skills, experience, education and about as much content as the original."""
    enough = len(resume_to_text(r)) >= 0.62 * len(base_text) if base_text else len(resume_to_text(r)) > 1500
    return (bool(r.get("summary")) and len(r.get("skills") or []) >= 4 and len(r.get("experience") or []) >= 1
            and len(r.get("education") or []) >= 1 and enough)


def tailor(resume_text: str, job: dict, feedback: str = "") -> dict:
    """Tailored resume, validated: an empty/partial model answer is retried (new prompt = not served from the cache)."""
    for attempt in range(3):
        note = "" if attempt == 0 else (" Your previous answer was incomplete or too short. Return the FULL resume: every "
                                         f"experience entry with all bullets, all projects, education, achievements. Attempt {attempt + 1}.")
        r = _tailor_once(resume_text, job, feedback + note, temperature=0.3 + 0.2 * attempt)
        if resume_ok(r, resume_text):
            return r
    raise RuntimeError("the AI could not produce a complete resume for this job")


def _tailor_once(resume_text: str, job: dict, feedback: str = "", temperature: float = 0.3) -> dict:
    """Rewrite the resume for the job. Never invents experience: keywords are only used if the resume supports them."""
    return llm.chat_json(
        ("You are a senior resume writer producing professional, ATS-friendly resumes. Rewrite the candidate's resume for "
         "the target job. RULES: (1) Use ONLY facts present in the original resume - never invent employers, degrees, "
         "metrics, tools or dates. (2) Work the job's keywords in naturally (summary, skills, bullets) wherever the "
         "candidate's real experience supports them; list any job keywords you could NOT support in "
         "'unsupported_keywords'. (3) Strong action-verb bullets, quantified only if the original has numbers. "
         "(3b) Treat candidate_facts as true (including extra_skills: skills the candidate really has - use them freely "
         "as keywords): put the current location in contact.location and reflect the total experience accurately. "
         "(4) The resume MUST FILL one full A4 page. Never shorten it: keep EVERY experience entry with ALL of its "
         "bullets (rewritten and reordered for this job, but none dropped), ALL projects with their bullets, ALL "
         "education entries, ALL certifications, achievements and activities from the original, and keep the total length "
         "about the same as the original resume (no more than 4200 characters of body text in total). Each experience entry "
         "should have 3-5 substantial bullets and each project 1-3 when the original has them. "
         "(5) Skills: keep all of the candidate's real skills, grouped into category lines such as "
         "'Languages: Python, SQL' or 'AI / ML: PyTorch, LLMs', most job-relevant skills and categories FIRST. "
         "(6) Contact links: only include real http(s) URLs. Reply JSON: name, contact {email, phone, location, "
         "links[]}, summary (3-4 lines), skills (list of category lines), experience [{title, company, dates, "
         "bullets[]}], projects [{name, bullets[]}], education [{degree, institution, dates, details}], "
         "certifications [strings], achievements [strings], activities [strings], "
         "unsupported_keywords [strings], added_keywords [strings]."
         + (BOOST_RULE if cfg.add_missing_keywords else "")),
        json.dumps({"original_resume": resume_text[:9000],
                    "job": {k: job.get(k) for k in ("company", "role", "skills", "responsibilities", "summary")},
                    "candidate_facts": cfg.candidate_facts, "fix_these": feedback}),
        temperature=temperature,
    )


_ASCII = {"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
          " ": " ", " ": " ", " ": " ", "​": "", "‘": "'", "’": "'",
          "“": '"', "”": '"', "→": "->", "←": "<-", "≥": ">=", "≤": "<=",
          "≈": "~", "×": "x", "…": "...", "●": "-", "▪": "-"}


def pdf_safe(text) -> str:
    """Replace characters the standard PDF font cannot draw (they show as black boxes)."""
    t = "".join(_ASCII.get(c, c) for c in str(text or ""))
    t = "".join(" " if c.isspace() else c for c in t)  # any odd space character (nbsp, thin space...) -> plain space
    return t.encode("cp1252", "ignore").decode("cp1252")


def signature_block(r: dict) -> str:
    """Name, email, phone, LinkedIn and GitHub - the end of every application email."""
    c, links = r.get("contact", {}), base_links()
    lines = [str(r.get("name") or ""), f"Email: {c.get('email') or cfg.smtp_user}", f"Phone: {c.get('phone') or ''}"]
    for k in ("LinkedIn", "GitHub"):
        if links.get(k):
            lines.append(f"{k}: {links[k]}")
    return "\n".join(l for l in lines if l.strip())


def email_profile(base_text: str) -> str:
    """Facts for application emails: the ORIGINAL resume (not the keyword-boosted one) plus your fixed facts."""
    facts = "".join(f"{k.replace('_', ' ')}: {v}\n" for k, v in cfg.candidate_facts.items() if v)
    return f"{base_text}\nFACTS:\n{facts}"


def profile_text(r: dict) -> str:
    """Contact details + resume content, used to answer web forms."""
    c = r.get("contact", {})
    head = (f"Name: {r.get('name') or ''}\nEmail: {c.get('email') or ''}\nPhone: {c.get('phone') or ''}\n"
            f"Location: {c.get('location') or ''}\n")
    head += "".join(f"{k}: {v}\n" for k, v in base_links().items())
    head += "FACTS:\n" + "".join(f"{k.replace('_', ' ')}: {v}\n" for k, v in cfg.candidate_facts.items())
    return head + resume_to_text(r, lower=False)


def resume_to_text(r: dict, lower: bool = True) -> str:
    parts = [r.get("summary", ""), " ".join(r.get("skills", []))]
    for e in r.get("experience", []):
        parts += [e.get("title", ""), e.get("company", "")] + e.get("bullets", [])
    for p in r.get("projects", []):
        parts += [p.get("name", "")] + p.get("bullets", [])
    parts += [f"{e.get('degree','')} {e.get('details','')}" for e in r.get("education", [])]
    parts += (r.get("certifications") or []) + (r.get("achievements") or []) + (r.get("activities") or [])
    text = "\n".join(str(x) for x in parts)
    return text.lower() if lower else text


def ats_score(resume: dict, job: dict) -> tuple[int, list[str]]:
    """Keyword coverage of the job's required skills in the resume -> (score 0-100, missing keywords)."""
    keywords = [k.strip() for k in (job.get("skills") or []) if k and k.strip()]
    if not keywords:
        return 100, []
    text = resume_to_text(resume)
    missing = [k for k in keywords if k.lower() not in text]
    return round(100 * (len(keywords) - len(missing)) / len(keywords)), missing


def keywords_added(job: dict, base_text: str, tailored: dict) -> list[str]:
    """Job keywords that are NOT in your original resume but are now in the tailored one (your 'to learn' list)."""
    base, new = base_text.lower(), resume_to_text(tailored)
    return [k for k in (job.get("skills") or []) if k and k.lower() not in base and k.lower() in new]


def judge(r: dict) -> tuple[str, float, float]:
    """('ok' | 'short' | 'long', type scale, page fill) of a tailored resume at a readable type size."""
    k, fill, fits = measure(r, KMIN)
    if not fits:
        return "long", k, fill
    return ("short" if (k >= KMAX - 0.001 and fill < MIN_FILL) else "ok"), k, fill


def build_tailored_resume(job: dict, base_text: str, rounds: int = 2) -> tuple[dict, int, list[str]]:
    """Tailor, ATS-test, then make sure the resume fills ONE page at a readable size: too short or too long is rewritten."""
    resume = tailor(base_text, job)
    score, missing = ats_score(resume, job)
    for _ in range(rounds - 1):
        if score >= cfg.target_ats_score:
            break
        resume = tailor(base_text, job, feedback=f"Add these keywords only where truthfully supported: {missing}")
        score, missing = ats_score(resume, job)

    best, (best_state, _k, best_fill) = resume, judge(resume)
    cand = resume
    for attempt in range(3):
        state, _k, fill = judge(cand)
        # keep the best candidate: 'ok' beats everything; otherwise the one closest to a full page
        if state == "ok" or best_state != "ok" and abs(1 - fill) < abs(1 - best_fill):
            best, best_state, best_fill = cand, state, fill
        if best_state == "ok":
            break
        if state == "short":
            msg = (f"The resume fills only {round(fill * 100)}% of a page: too short. Include EVERY bullet of every experience "
                   "entry and project from the original, all grouped skills, all achievements, certifications and activities.")
        else:
            msg = ("The resume does not fit on one page at a normal font size: too long. Keep every section, every entry and "
                   "every project, but make each bullet at most 2 lines, merge similar skills, and keep the summary to 3 lines.")
        cand = tailor(base_text, job, feedback=f"{msg} Attempt {attempt + 2}.")
    if best_state == "short" and best_fill < HARD_MIN_FILL:
        raise RuntimeError(f"resume came out too short ({round(best_fill * 100)}% of a page) - not sent")
    if best_state == "long" and measure(best, KFLOOR)[2] is False:
        raise RuntimeError("resume does not fit on one page even at the smallest allowed font - not sent")
    if best is not resume:
        score, missing = ats_score(best, job)
    return best, score, missing


def _story(r: dict, k: float):
    """The flowables for the resume at type scale k, plus the document geometry."""
    name = ParagraphStyle("n", fontName="Helvetica-Bold", fontSize=19 * k, leading=22 * k, alignment=TA_CENTER, textColor=ACCENT)
    small = ParagraphStyle("s", fontName="Helvetica", fontSize=8.8 * k, leading=11 * k, alignment=TA_CENTER)
    head = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=10.5 * k, leading=12.5 * k, spaceBefore=5 * k, textColor=ACCENT)
    body = ParagraphStyle("b", fontName="Helvetica", fontSize=9.0 * k, leading=11.3 * k)
    bul = ParagraphStyle("bl", parent=body, leftIndent=10 * k, bulletIndent=0)
    esc = lambda s: pdf_safe(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    c = r.get("contact", {})
    plain = " | ".join(esc(x) for x in [c.get("email"), c.get("phone"), c.get("location")] if x)
    # LinkedIn / GitHub / portfolio come from the real hyperlinks in the base resume: shown as text and clickable
    links = " | ".join(f'<a href="{u}" color="#1a4fa0">{esc(re.sub(r"^https?://(www\.)?", "", u))}</a>'
                       for u in base_links().values())
    story = [Paragraph(esc(r.get("name")), name), Paragraph(plain, small)]
    if links:
        story.append(Paragraph(links, small))

    def section(title):
        story.extend([Paragraph(title.upper(), head), HRFlowable(width="100%", thickness=0.7, color=ACCENT), Spacer(1, 2 * k)])

    def bullets(items):
        story.extend(Paragraph(esc(b), bul, bulletText="•") for b in items or [])

    if r.get("summary"):
        section("Summary"); story.append(Paragraph(esc(r["summary"]), body))
    if r.get("skills"):
        section("Skills")
        for line in r["skills"]:
            label, sep, rest = str(line).partition(":")
            story.append(Paragraph(f"<b>{esc(label)}:</b>{esc(rest)}" if sep else esc(line), body))
    if r.get("experience"):
        section("Experience")
        for e in r["experience"]:
            story.append(Paragraph(f"<b>{esc(e.get('title'))}</b>, {esc(e.get('company'))} - {esc(e.get('dates'))}", body))
            bullets(e.get("bullets"))
    if r.get("projects"):
        section("Projects")
        for p in r["projects"]:
            story.append(Paragraph(f"<b>{esc(p.get('name'))}</b>", body))
            bullets(p.get("bullets"))
    if r.get("education"):
        section("Education")
        for e in r["education"]:
            extra = f" | {esc(e['details'])}" if e.get("details") else ""
            story.append(Paragraph(f"<b>{esc(e.get('degree'))}</b>, {esc(e.get('institution'))} - {esc(e.get('dates'))}{extra}", body))
    extras = (r.get("achievements") or []) + (r.get("certifications") or [])
    if extras:
        section("Achievements & Certifications"); bullets(extras)
    if r.get("activities"):
        section("Activities"); bullets(r["activities"])
    return story


_PAGE_W, _PAGE_H = A4
_MARGIN_X, _MARGIN_Y = 13 * mm, 10 * mm
_AVAIL_W = _PAGE_W - 2 * _MARGIN_X - 12      # frame padding is 6pt each side
_AVAIL_H = _PAGE_H - 2 * _MARGIN_Y - 12


def _fill(story) -> float:
    """Share of the page the story occupies (1.0 = exactly one full page)."""
    total = 0.0
    for f in story:
        _w, h = f.wrap(_AVAIL_W, 100000)
        total += h + f.getSpaceBefore() + f.getSpaceAfter()
    return total / _AVAIL_H


def measure(r: dict, kmin: float = KMIN) -> tuple[float, float, bool]:
    """(type scale k, page fill, fits): the largest scale (k <= KMAX) at which the resume fits on one page.
    If it does not fit even at kmin: (kmin, fill at kmin, False)."""
    k = KMAX
    while k >= kmin - 1e-9:
        fill = _fill(_story(r, k))
        if fill <= 0.985:
            return round(k, 2), round(fill, 3), True
        k -= 0.02
    return round(kmin, 2), round(_fill(_story(r, kmin)), 3), False


def render_pdf(r: dict, path: str) -> str:
    """Render the resume at the largest type size that fits one page, so the page is used in full."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    k, _fill_ratio, _fits = measure(r, KFLOOR)
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=_MARGIN_X, rightMargin=_MARGIN_X,
                            topMargin=_MARGIN_Y, bottomMargin=_MARGIN_Y, title=r.get("name", "Resume"))
    doc.build(_story(r, k))
    return path


def page_fill(r: dict) -> int:
    """Percent of the page the rendered resume uses (for the results table)."""
    return round(measure(r, KFLOOR)[1] * 100)


def cv_pdf_path(r: dict, *job_parts: str) -> str:
    """telegram_apply/output/<job>/<Your_Name>_CV.pdf - what the recruiter sees is always your name, never the job."""
    return f"{OUT_DIR}/{safe_name(*job_parts)}/{safe_name(r.get('name') or 'Resume')}_CV.pdf"


def safe_name(*parts: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", "_".join(p or "" for p in parts)).strip("_")[:80]
