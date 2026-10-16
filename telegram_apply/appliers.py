"""Ways to submit an application: email to recruiter, Google Form, LinkedIn queue."""
import csv
import json
import os
import re
import smtplib
import time
from email.message import EmailMessage
from . import drive, llm

FILL_RULES = 'Fill EVERY question - never leave one blank. First use the FACTS (use them verbatim: current location, relocation, years of experience, etc.). Otherwise answer as the candidate using the resume and give the most sensible, professional best answer (e.g. notice period: Immediately available / 15 days; expected salary: as per company standards / negotiable; why join: a short tailored reason; strengths, projects, skills: from the resume). For choice questions pick the best option exactly as written. The only thing you may leave empty is an identity number or date of birth that is not in the facts.'
from config import telegram_apply as cfg


def write_email_body(job: dict, resume_text: str) -> dict:
    return llm.chat_json(
        "Write a short, professional job-application email (under 120 words) from the candidate to a recruiter. "
        "Only use facts from the resume. Reply JSON: subject, body (plain text, sign off with the candidate's name).",
        json.dumps({"job": {k: job.get(k) for k in ("company", "role")}, "resume": resume_text[:5000]}),
    )


def send_email(to: str, subject: str, body: str, pdf_path: str) -> None:
    msg = EmailMessage()
    msg["From"] = f"{cfg.sender_name} <{cfg.smtp_user}>" if cfg.sender_name else cfg.smtp_user
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    with open(pdf_path, "rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=os.path.basename(pdf_path))
    with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port) as s:
        s.login(cfg.smtp_user, cfg.smtp_password)
        s.send_message(msg)


def queue_linkedin(job: dict, links: list[str]) -> None:
    os.makedirs("all excels", exist_ok=True)
    with open("all excels/telegram_linkedin_queue.csv", "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for l in links:
            w.writerow([job.get("company"), job.get("role"), l])


def _driver():
    """Chrome using the dedicated profile where you signed in to Google (google_login.py)."""
    from selenium import webdriver
    opts = webdriver.ChromeOptions()
    if cfg.chrome_user_data_dir:
        opts.add_argument(f"--user-data-dir={os.path.abspath(cfg.chrome_user_data_dir)}")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    return webdriver.Chrome(options=opts)


GOOGLE_LOGIN_FAILED = False  # set after one timed-out sign-in so the rest of the run does not wait again


def _needs_signin(d) -> bool:
    from selenium.webdriver.common.by import By
    if "accounts.google.com" in d.current_url:
        return True
    return any(e.is_displayed() for e in d.find_elements(By.XPATH, "//*[contains(text(),'must be signed in')]"))


def _ensure_google_signin(d, wait_s: int = 240) -> bool:
    """If the form shows 'Sign in to continue', click Sign in and wait for you to log in in that window.
    The login is stored in the Chrome profile, so this is needed only once."""
    global GOOGLE_LOGIN_FAILED
    from selenium.webdriver.common.by import By
    if not _needs_signin(d):
        return True
    if GOOGLE_LOGIN_FAILED:
        return False
    try:
        for el in d.find_elements(By.XPATH, "//*[self::a or self::button or @role='button']"
                                  "[contains(translate(normalize-space(.),'SIGN','sign'),'sign in')]"):
            if el.is_displayed():
                el.click()
                break
    except Exception:
        pass
    print("Google sign-in needed: sign in in the Chrome window that is open (waiting up to 4 minutes)...", flush=True)
    deadline = time.time() + wait_s
    while time.time() < deadline:
        time.sleep(3)
        try:
            if not _needs_signin(d):
                return True
        except Exception:
            break
    GOOGLE_LOGIN_FAILED = True
    return False


def _dropdown_options(d, item) -> list[str]:
    """Open a Google Forms dropdown, read its options, close it again."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    box = item.find_element(By.CSS_SELECTOR, "div[role='listbox']")
    box.click()
    time.sleep(0.3)
    opts = [o.get_attribute("data-value") for o in d.find_elements(By.CSS_SELECTOR, "div[role='option']")
            if o.is_displayed() and o.get_attribute("data-value")]
    box.send_keys(Keys.ESCAPE)
    return opts


def fill_google_form(url: str, job: dict, resume_text: str, submit: bool, pdf_path: str = "") -> str:
    """Best-effort Google Form filler. Returns a status string. File-upload questions are flagged, not guessed."""
    from selenium.webdriver.common.by import By
    d = _driver()
    notes = []
    try:
        d.get(url)
        from selenium.webdriver.support.ui import WebDriverWait
        try:
            WebDriverWait(d, 20).until(lambda x: x.find_elements(By.CSS_SELECTOR, "div[role='listitem']")
                                       or "accounts.google.com" in x.current_url)
        except Exception:
            return "form did not load (closed or removed?) - open the link manually"
        if not _ensure_google_signin(d):
            return "blocked: form needs Google sign-in - sign in once when the Chrome window asks (login is then saved)"
        time.sleep(1)
        for _page in range(10):
            items = d.find_elements(By.CSS_SELECTOR, "div[role='listitem']")
            questions = []
            for i, it in enumerate(items):
                try:
                    title = it.find_element(By.CSS_SELECTOR, "div[role='heading']").text
                except Exception:
                    continue
                kind, options = None, []
                if it.find_elements(By.CSS_SELECTOR, "input[type='file']") or \
                        it.find_elements(By.XPATH, ".//div[@role='button'][contains(., 'Add file')]"):
                    if pdf_path and re.search(r"resume|cv|curriculum", title, re.I):
                        drive.upload_in_google_form(d, it, pdf_path, notes, title)  # attach the tailored resume
                    else:
                        notes.append(f"file upload needed: {title}")
                    continue
                if it.find_elements(By.CSS_SELECTOR, "div[role='radio']"):
                    kind = "radio"
                    options = [e.get_attribute("data-value") for e in it.find_elements(By.CSS_SELECTOR, "div[role='radio']")]
                elif it.find_elements(By.CSS_SELECTOR, "div[role='checkbox']"):
                    kind = "checkbox"
                    options = [e.get_attribute("data-answer-value") for e in it.find_elements(By.CSS_SELECTOR, "div[role='checkbox']")]
                elif it.find_elements(By.CSS_SELECTOR, "div[role='listbox']"):
                    kind = "dropdown"
                    options = _dropdown_options(d, it)
                elif it.find_elements(By.CSS_SELECTOR, "textarea"):
                    kind = "paragraph"
                elif it.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='email'], input[type='tel'], input[type='url'], input[type='number']"):
                    kind = "text"
                if kind:
                    questions.append((i, title, kind, options))
            if questions and drive.asks_for_resume_link([q[1] for q in questions]):
                link = drive.get_resume_link(d, pdf_path, notes)  # a question wants a Drive link to the resume
                if link:
                    resume_text += f"\nResume link (Google Drive, anyone with the link can view): {link}\n"
            if questions:
                answers = llm.chat_json(
                    "Answer job-application form questions as the candidate. " + FILL_RULES + " "
                    "Reply JSON {\"answers\": {\"<index>\": <string, or list of strings for checkbox>}}. For radio/checkbox "
                    "choose from the options exactly.",
                    json.dumps({"job": {k: job.get(k) for k in ("company", "role")}, "resume": resume_text[:5000],
                                "questions": [{"index": i, "question": t, "type": k, "options": o} for i, t, k, o in questions]}),
                    temperature=0,
                ).get("answers", {})
                for i, title, kind, options in questions:
                    ans = answers.get(str(i))
                    if not ans:
                        notes.append(f"left blank: {title}")
                        continue
                    it = items[i]
                    if kind in ("text", "paragraph"):
                        el = it.find_element(By.CSS_SELECTOR, "textarea" if kind == "paragraph" else "input:not([type='hidden'])")
                        el.clear()
                        el.send_keys(str(ans))
                    elif kind == "dropdown":
                        it.find_element(By.CSS_SELECTOR, "div[role='listbox']").click()
                        time.sleep(0.3)
                        for o in d.find_elements(By.CSS_SELECTOR, "div[role='option']"):
                            if o.is_displayed() and o.get_attribute("data-value") == str(ans):
                                o.click()
                                break
                    else:
                        wanted = ans if isinstance(ans, list) else [ans]
                        css = "div[role='radio']" if kind == "radio" else "div[role='checkbox']"
                        attr = "data-value" if kind == "radio" else "data-answer-value"
                        for el in it.find_elements(By.CSS_SELECTOR, css):
                            if el.get_attribute(attr) in wanted:
                                el.click()
            btns = d.find_elements(By.XPATH, "//div[@role='button']//span[text()='Next' or text()='Submit']")
            if not btns:
                break
            if btns[0].text == "Submit":
                if not submit:
                    return "dry-run: form filled, not submitted; " + "; ".join(notes)
                btns[0].click()
                time.sleep(2)
                return "submitted; " + "; ".join(notes)
            btns[0].click()
            time.sleep(1)
        return "stopped before submit; " + "; ".join(notes)
    finally:
        d.quit()
