"""Resume uploads: to Google Drive (to answer 'share a Drive link of your resume') and into Google Forms upload questions.

Everything runs in the same Chrome window / profile that is signed in to Google (see google_login.py).
"""
import os
import re
import time
from pypdf import PdfReader
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from config import telegram_apply as cfg

_cache: dict[str, str] = {}   # pdf path -> shareable link (per process)

_LINK_Q = re.compile(r"(drive|link|url).{0,40}(resume|cv|curriculum)|(resume|cv|curriculum).{0,40}(drive|link|url)", re.I)


def asks_for_resume_link(labels: list[str]) -> bool:
    return any(_LINK_Q.search(l or "") for l in labels)


def base_drive_link() -> str | None:
    """The Google Drive link already embedded in your base resume PDF (used as a fallback)."""
    try:
        for page in PdfReader(cfg.base_resume_pdf).pages:
            for a in page.get("/Annots") or []:
                uri = str((a.get_object().get("/A") or {}).get("/URI") or "")
                if "drive.google.com/file/" in uri:
                    return uri
    except Exception:
        pass
    return None


def _click_xpath(d, xpath: str, timeout: float = 8) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        for el in d.find_elements(By.XPATH, xpath):
            try:
                if el.is_displayed():
                    el.click()
                    return True
            except Exception:
                continue
        time.sleep(0.4)
    return False


def upload_to_drive(d, pdf_path: str) -> str | None:
    """Upload the PDF to Drive in a new tab, set 'Anyone with the link', return the link. None on failure."""
    pdf_abs = os.path.abspath(pdf_path)
    name = os.path.basename(pdf_abs)
    stem = os.path.splitext(name)[0]
    main = d.current_window_handle
    d.switch_to.new_window("tab")
    try:
        d.get("https://drive.google.com/drive/my-drive")
        time.sleep(4)
        if "accounts.google.com" in d.current_url:
            return None
        inputs = d.find_elements(By.CSS_SELECTOR, "input[type='file']")
        if not inputs:  # the hidden upload input appears once the New menu is opened
            _click_xpath(d, "//button[@aria-label='New' or .//span[normalize-space()='New']] | //*[@role='button'][normalize-space()='New']", 5)
            time.sleep(1)
            inputs = d.find_elements(By.CSS_SELECTOR, "input[type='file']")
        if not inputs:
            return None
        inputs[0].send_keys(pdf_abs)

        row_xpath = f"//*[@data-id and .//*[contains(normalize-space(text()), '{stem}')]]"
        file_id, end = None, time.time() + 60
        while time.time() < end and not file_id:
            rows = d.find_elements(By.XPATH, row_xpath)
            file_id = next((r.get_attribute("data-id") for r in rows if r.get_attribute("data-id")), None)
            time.sleep(1)
        if not file_id:
            return None

        # open the file's page and share it with "Anyone with the link"
        d.get(f"https://drive.google.com/file/d/{file_id}/view")
        time.sleep(3)
        if not _click_xpath(d, "//*[@role='button' and (contains(@aria-label,'Share') or normalize-space()='Share')]", 10):
            return None
        time.sleep(2)
        for fr in d.find_elements(By.CSS_SELECTOR, "iframe[src*='share'], iframe[src*='sharing']"):
            try:
                d.switch_to.frame(fr)
                break
            except Exception:
                pass
        _click_xpath(d, "//*[normalize-space()='Restricted']/ancestor-or-self::*[@role='combobox' or @role='button'][1]", 6)
        ok = _click_xpath(d, "//*[@role='option' or @role='menuitemradio' or @role='menuitem'][contains(., 'Anyone with the link')]", 6)
        time.sleep(1)
        _click_xpath(d, "//*[@role='button'][normalize-space()='Done'] | //button[normalize-space()='Done']", 4)
        d.switch_to.default_content()
        return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing" if ok else None
    except Exception:
        return None
    finally:
        try:
            d.close()
        finally:
            d.switch_to.window(main)


def get_resume_link(d, pdf_path: str, notes: list) -> str | None:
    """Shareable link for this job's tailored resume; falls back to the Drive link inside your base resume."""
    if pdf_path in _cache:
        return _cache[pdf_path]
    link = upload_to_drive(d, pdf_path) if pdf_path else None
    if link:
        _cache[pdf_path] = link
        return link
    fallback = base_drive_link()
    notes.append("Drive upload failed - used the Drive link of your base resume" if fallback
                 else "Drive upload failed and no fallback link")
    return fallback


def upload_in_google_form(d, item, pdf_path: str, notes: list, title: str) -> bool:
    """Handle a Google Forms 'file upload' question: Add file -> pick PDF -> Upload."""
    pdf_abs = os.path.abspath(pdf_path)
    try:
        btn = next(b for b in item.find_elements(By.CSS_SELECTOR, "div[role='button']")
                   if "add file" in (b.text + (b.get_attribute("aria-label") or "")).lower())
        btn.click()
        end, frame = time.time() + 12, None
        while time.time() < end and frame is None:
            frame = next((f for f in d.find_elements(By.TAG_NAME, "iframe")
                          if "picker" in (f.get_attribute("src") or "") or "upload" in (f.get_attribute("src") or "")), None)
            time.sleep(0.5)
        if frame is None:
            raise RuntimeError("upload dialog did not open")
        d.switch_to.frame(frame)
        inp = None
        for _ in range(2):
            found = d.find_elements(By.CSS_SELECTOR, "input[type='file']")
            if found:
                inp = found[0]
                break
            _click_xpath(d, "//*[normalize-space()='Browse']", 3)
        if inp is None:
            raise RuntimeError("no file input in the upload dialog")
        inp.send_keys(pdf_abs)
        time.sleep(1)
        _click_xpath(d, "//*[@role='button' or self::button][normalize-space()='Upload' or normalize-space()='Insert']", 4)
        time.sleep(3)
        d.switch_to.default_content()
        return True
    except Exception as e:
        try:
            d.switch_to.default_content()
            d.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        except Exception:
            pass
        notes.append(f"resume upload failed for '{title[:30]}': {e}")
        return False
