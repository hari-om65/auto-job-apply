"""Read the base resume, tailor it to a job (truthfully), score it for ATS keywords, render an ATS-safe PDF."""
import functools
import json
import os
import re
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, HRFlowable
from . import llm
from config import telegram_apply as cfg

OUT_DIR = "telegram_apply/output"


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


def tailor(resume_text: str, job: dict, feedback: str = "") -> dict:
    """Rewrite the resume for the job. Never invents experience: keywords are only used if the resume supports them."""
    return llm.chat_json(
        "You are a professional resume writer producing ATS-friendly resumes. Rewrite the candidate's resume for the "
        "target job. RULES: (1) Use ONLY facts present in the original resume - never invent employers, degrees, "
        "metrics, tools or dates. (2) Work the job's keywords in naturally (summary, skills, bullets) wherever the "
        "candidate's real experience supports them; list any job keywords you could NOT support in "
        "'unsupported_keywords'. (3) Strong action-verb bullets, quantified only if the original has numbers. "
        "(3b) Treat candidate_facts as true: put the current location in contact.location and reflect the total experience accurately. (4) One page, simple structure, standard section names. (5) Skills: pick only the skills relevant to this job "
        "(max ~25, most relevant FIRST, plain tool names), drop irrelevant ones; reorder experience/project bullets so the "
        "most job-relevant come first and trim the rest. (6) Contact links: only include real http(s) URLs. Reply JSON: name, contact {email, phone, location, "
        "links[]}, summary, skills (list of strings), experience [{title, company, dates, bullets[]}], projects "
        "[{name, bullets[]}], education [{degree, institution, dates, details}], certifications [strings], "
        "unsupported_keywords [strings].",
        json.dumps({"original_resume": resume_text[:9000],
                    "job": {k: job.get(k) for k in ("company", "role", "skills", "responsibilities", "summary")},
                    "candidate_facts": cfg.candidate_facts, "fix_these": feedback}),
        temperature=0.3,
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
    parts += r.get("certifications", [])
    text = "\n".join(parts)
    return text.lower() if lower else text


def ats_score(resume: dict, job: dict) -> tuple[int, list[str]]:
    """Keyword coverage of the job's required skills in the resume -> (score 0-100, missing keywords)."""
    keywords = [k.strip() for k in (job.get("skills") or []) if k and k.strip()]
    if not keywords:
        return 100, []
    text = resume_to_text(resume)
    missing = [k for k in keywords if k.lower() not in text]
    return round(100 * (len(keywords) - len(missing)) / len(keywords)), missing


def build_tailored_resume(job: dict, base_text: str, rounds: int = 2) -> tuple[dict, int, list[str]]:
    """Tailor, ATS-test, and retry once with feedback if coverage is below target."""
    resume = tailor(base_text, job)
    score, missing = ats_score(resume, job)
    for _ in range(rounds - 1):
        if score >= cfg.target_ats_score:
            break
        resume = tailor(base_text, job, feedback=f"Add these keywords only where truthfully supported: {missing}")
        score, missing = ats_score(resume, job)
    return resume, score, missing


def render_pdf(r: dict, path: str) -> str:
    """Render the resume, shrinking the type slightly until it fits on one page."""
    for k in (1.0, 0.95, 0.9, 0.86, 0.82):
        if _render(r, path, k) == 1:
            break
    return path


def _render(r: dict, path: str, k: float) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    name = ParagraphStyle("n", fontName="Helvetica-Bold", fontSize=18 * k, leading=22 * k)
    small = ParagraphStyle("s", fontName="Helvetica", fontSize=9 * k, leading=12 * k)
    head = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=11 * k, leading=14 * k, spaceBefore=6 * k)
    body = ParagraphStyle("b", fontName="Helvetica", fontSize=9.5 * k, leading=12.5 * k)
    bul = ParagraphStyle("bl", parent=body, leftIndent=10, bulletIndent=0)
    esc = lambda s: pdf_safe(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    c = r.get("contact", {})
    plain = " | ".join(esc(x) for x in [c.get("email"), c.get("phone"), c.get("location")] if x)
    # LinkedIn / GitHub / portfolio come from the real hyperlinks in the base resume: shown as text and clickable
    links = " | ".join(f'<a href="{u}" color="#1a4fa0">{esc(re.sub(r"^https?://(www\.)?", "", u))}</a>'
                       for u in base_links().values())
    story = [Paragraph(esc(r.get("name")), name),
             Paragraph(plain, small)]
    if links:
        story.append(Paragraph(links, small))

    def section(title):
        story.extend([Paragraph(title.upper(), head), HRFlowable(width="100%", thickness=0.6), Spacer(1, 2)])

    if r.get("summary"):
        section("Summary"); story.append(Paragraph(esc(r["summary"]), body))
    if r.get("skills"):
        section("Skills"); story.append(Paragraph(esc(", ".join(r["skills"])), body))
    if r.get("experience"):
        section("Experience")
        for e in r["experience"]:
            story.append(Paragraph(f"<b>{esc(e.get('title'))}</b>, {esc(e.get('company'))} - {esc(e.get('dates'))}", body))
            story += [Paragraph(esc(b), bul, bulletText="•") for b in e.get("bullets", [])]
    if r.get("projects"):
        section("Projects")
        for p in r["projects"]:
            story.append(Paragraph(f"<b>{esc(p.get('name'))}</b>", body))
            story += [Paragraph(esc(b), bul, bulletText="•") for b in p.get("bullets", [])]
    if r.get("education"):
        section("Education")
        for e in r["education"]:
            story.append(Paragraph(f"<b>{esc(e.get('degree'))}</b>, {esc(e.get('institution'))} - {esc(e.get('dates'))}", body))
            if e.get("details"):
                story.append(Paragraph(esc(e["details"]), body))
    if r.get("certifications"):
        section("Certifications"); story += [Paragraph(esc(x), bul, bulletText="•") for x in r["certifications"]]

    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm, title=r.get("name", "Resume"))
    doc.build(story)
    return doc.page


def safe_name(*parts: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", "_".join(p or "" for p in parts)).strip("_")[:80]
