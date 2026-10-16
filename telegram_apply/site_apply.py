"""Apply on any company career page: open it, fill the form with AI answers, upload the tailored resume, submit."""
import json
import os
import time
from . import drive, llm, resume
from .appliers import FILL_RULES
from config import telegram_apply as cfg

# Tag every visible form control with data-ja-id and describe it (label, type, options).
_SCAN_JS = """
const els=[...document.querySelectorAll('input,textarea,select')].filter(e=>{
  const t=(e.type||'').toLowerCase();
  if(['hidden','submit','button','image','reset'].includes(t)) return false;
  return e.offsetParent!==null || t==='file';});
const lab=e=>{let l='';
  if(e.id){const x=document.querySelector('label[for="'+CSS.escape(e.id)+'"]'); if(x) l=x.innerText;}
  if(!l){const x=e.closest('label'); if(x) l=x.innerText;}
  if(!l) l=e.getAttribute('aria-label')||e.placeholder||'';
  if(!l){const p=e.closest('fieldset,div,li'); if(p) l=(p.innerText||'').slice(0,120);}
  return l.trim().slice(0,160);};
return els.map((e,i)=>{e.setAttribute('data-ja-id',i);
  return {id:i,tag:e.tagName.toLowerCase(),type:(e.type||'').toLowerCase(),label:lab(e),name:e.name||'',
    required:!!e.required,value:e.value||'',checked:!!e.checked,
    options:e.tagName==='SELECT'?[...e.options].map(o=>o.text.trim()).filter(Boolean):[]};});
"""

_BLOCKER_JS = """
if(document.querySelector('iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="turnstile"],.g-recaptcha,.h-captcha')) return 'captcha';
const pw=document.querySelector('input[type=password]'); if(pw && pw.offsetParent!==null) return 'login';
return '';
"""


def _click_text(d, texts: list[str]) -> str | None:
    """Click the first visible button/link whose text matches one of `texts` (in priority order). Returns the text."""
    from selenium.webdriver.common.by import By
    for t in texts:
        xp = (f"//*[self::button or self::a or @role='button' or (self::input and (@type='submit' or @type='button'))]"
              f"[contains(translate(normalize-space(string(.)),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'{t}')"
              f" or contains(translate(@value,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'{t}')]")
        for el in d.find_elements(By.XPATH, xp):
            try:
                if el.is_displayed() and el.is_enabled():
                    d.execute_script("arguments[0].scrollIntoView({block:'center'})", el)
                    el.click()
                    return t
            except Exception:
                continue
    return None


def _group_fields(fields: list[dict]) -> list[dict]:
    """Collapse radio buttons with the same name into one question with options."""
    out, radios = [], {}
    for f in fields:
        if f["type"] == "radio" and f["name"]:
            g = radios.setdefault(f["name"], {"id": f["id"], "type": "radio", "tag": "input", "name": f["name"],
                                              "label": "", "required": f["required"], "options": [], "ids": []})
            g["options"].append(f["label"]); g["ids"].append(f["id"])
            if not g["label"]:
                g["label"] = f["name"]
            if g not in out:
                out.append(g)
        else:
            out.append(f)
    return out


def _fill_field(d, f: dict, ans, notes: list) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select
    try:
        if f["type"] == "radio":
            for rid, opt in zip(f["ids"], f["options"]):
                if str(ans).lower() in opt.lower() or opt.lower() in str(ans).lower():
                    d.execute_script("document.querySelector(`[data-ja-id='${arguments[0]}']`).click()", rid)
                    break
            return
        el = d.find_element(By.CSS_SELECTOR, f"[data-ja-id='{f['id']}']")
        if f["tag"] == "select":
            match = next((o for o in f["options"] if o.lower() == str(ans).lower()), None) or                 next((o for o in f["options"] if str(ans).lower() in o.lower()), None)
            if match:
                Select(el).select_by_visible_text(match)
        elif f["type"] == "checkbox":
            if str(ans).lower().startswith("y") != el.is_selected():
                d.execute_script("arguments[0].click()", el)
        elif not f["value"]:  # don't overwrite prefilled values
            el.clear()
            el.send_keys(str(ans))
    except Exception as e:
        notes.append(f"could not fill {f['label'][:30]}: {type(e).__name__}")


def _answer_and_fill(d, job: dict, profile_text: str, questions: list, notes: list, strict: bool = False) -> None:
    extra = (" These required fields are still EMPTY: you MUST give a concrete value for every one." if strict else "")
    answers = llm.chat_json(
        "You fill a job-application web form as the candidate. " + FILL_RULES + extra + " "
        "Reply JSON {\"answers\": {\"<id>\": <value>}}. text/textarea -> string; select/radio -> one of the "
        "options exactly; checkbox -> \"yes\" or \"no\" (yes for privacy/terms consent, no for marketing). "
        "type=number or numeric-looking fields (notice period in days, CTC, salary, years): digits only, no words "
        "(a fresher: current CTC 0, notice period 0-15, expected CTC a realistic INR figure such as 400000 per year "
        "unless the label says per month/lakhs). Keep answers short and professional.",
        json.dumps({"job": {k: job.get(k) for k in ("company", "role")}, "candidate": profile_text[:6000],
                    "fields": [{k: f.get(k) for k in ("id", "label", "type", "options", "required")}
                               for f in questions]}),
        temperature=0,
    ).get("answers", {})
    for f in questions:
        ans = answers.get(str(f["id"]))
        if ans in (None, ""):
            if f.get("required"):
                notes.append(f"left blank: {f['label'][:40]}")
            continue
        _fill_field(d, f, ans, notes)


def apply_to_site(url: str, job: dict, profile_text: str, pdf_path: str, submit: bool) -> str:
    """Visit `url` and apply. Returns a status string. Stops (and says why) on captcha / login walls."""
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    from .appliers import _driver
    d = _driver()
    notes, proof = [], None
    pdf_abs = os.path.abspath(pdf_path)
    label = resume.safe_name(job.get("company"), job.get("role"))
    try:
        d.get(url)
        time.sleep(4)
        for _step in range(8):
            blocker = d.execute_script(_BLOCKER_JS)
            if blocker:
                return f"blocked: {blocker} on the site - apply manually"
            fields = d.execute_script(_SCAN_JS)
            if not fields:  # landing page: look for an Apply button
                if _click_text(d, ["apply now", "apply for this", "apply"]):
                    time.sleep(3)
                    if len(d.window_handles) > 1:
                        d.switch_to.window(d.window_handles[-1])
                    continue
                return "no application form found - apply manually"

            questions = [f for f in _group_fields(fields) if f["type"] != "file"]
            if drive.asks_for_resume_link([f["label"] for f in questions]):  # a field wants a Drive link to the resume
                link = drive.get_resume_link(d, pdf_path, notes)
                if not link:  # never submit with a wrong/missing resume link
                    return "blocked: could not create a Drive link for this job's resume - apply manually"
                profile_text += f"\nResume link (Google Drive, anyone with the link can view): {link}\n"
            _answer_and_fill(d, job, profile_text, questions, notes)

            # second pass: anything required that is still empty gets a firmer prompt
            time.sleep(0.5)
            empty = [f for f in _group_fields(d.execute_script(_SCAN_JS))
                     if f["type"] not in ("file", "checkbox", "radio") and f.get("required") and not f["value"]]
            if empty:
                _answer_and_fill(d, job, profile_text, empty, notes, strict=True)

            files = [f for f in fields if f["type"] == "file"]
            for f in files:  # upload the tailored resume
                try:
                    d.find_element(By.CSS_SELECTOR, f"[data-ja-id='{f['id']}']").send_keys(pdf_abs)
                    time.sleep(2)
                except Exception:
                    notes.append("resume upload failed")

            proof = os.path.join(resume.OUT_DIR, "proof", f"{label}.png")
            os.makedirs(os.path.dirname(proof), exist_ok=True)
            d.save_screenshot(proof)
            tail = ("; " + "; ".join(notes)) if notes else ""

            if not submit:
                return f"dry-run: form filled, not submitted (screenshot {proof}){tail}"
            if _click_text(d, ["submit application", "submit", "send application", "apply"]):
                time.sleep(4)
                d.save_screenshot(proof)
                return f"submitted (check screenshot {proof}){tail}"
            if _click_text(d, ["next", "continue", "save and continue"]):
                time.sleep(3)
                continue
            return f"filled but found no submit button - apply manually{tail}"
        return "stopped after too many steps - apply manually"
    finally:
        d.quit()
