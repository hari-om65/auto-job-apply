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


def _drive_file_id(d, stem: str, timeout: int = 40) -> str | None:
    """Find the uploaded file's id through Drive search (the main list is lazy-loaded and sorted by name)."""
    from urllib.parse import quote
    d.get(f"https://drive.google.com/drive/search?q={quote(stem)}")
    end = time.time() + timeout
    while time.time() < end:
        for r in d.find_elements(By.CSS_SELECTOR, "[data-id]"):
            if stem in (r.text or "") and r.get_attribute("data-id"):
                return r.get_attribute("data-id")
        time.sleep(1.5)
    return None


def upload_to_drive(d, pdf_path: str) -> str | None:
    """Upload exactly this job's PDF to Drive in a new tab, share it as 'Anyone with the link' (viewer), and return
    the link. Returns None if any step fails - the caller must NOT substitute another resume silently."""
    import pyautogui  # Drive's "File upload" opens a native Windows dialog; we type the path into it

    pdf_abs = os.path.abspath(pdf_path)
    stem = os.path.splitext(os.path.basename(pdf_abs))[0]
    main = d.current_window_handle
    d.switch_to.new_window("tab")
    try:
        d.maximize_window()
        d.get("https://drive.google.com/drive/my-drive")
        time.sleep(4)
        if "accounts.google.com" in d.current_url:
            return None
        if not _click_xpath(d, "//button[@aria-label='New' or normalize-space()='New']", 8):
            return None
        time.sleep(1)
        if not _click_xpath(d, "//*[@role='menuitem'][starts-with(normalize-space(.), 'File upload')]", 6):
            return None
        time.sleep(2.5)                          # the native "Open" dialog appears with the filename box focused
        pyautogui.write(pdf_abs, interval=0.01)
        pyautogui.press("enter")
        end = time.time() + 60                   # wait for Drive's "upload complete" toast
        while time.time() < end:
            if "upload complete" in d.find_element(By.TAG_NAME, "body").text.lower():
                break
            time.sleep(1)
        else:
            return None

        file_id = _drive_file_id(d, stem)
        if not file_id:
            return None

        # open the file and share it with "Anyone with the link" (viewer)
        d.get(f"https://drive.google.com/file/d/{file_id}/view")
        time.sleep(3)
        if not _click_xpath(d, "//*[@role='button' and (contains(@aria-label,'Share') or normalize-space()='Share')]", 10):
            return None
        frame, end = None, time.time() + 15
        while time.time() < end and frame is None:   # the dialog lives in a drivesharing iframe
            frame = next((f for f in d.find_elements(By.TAG_NAME, "iframe")
                          if "drivesharing/dialog/share" in (f.get_attribute("src") or "")), None)
            time.sleep(0.5)
        if frame is None:
            return None
        d.switch_to.frame(frame)
        time.sleep(1.5)
        if not _click_xpath(d, "//button[contains(@aria-label,'change general access')]", 10):
            d.switch_to.default_content()
            return None
        time.sleep(1)
        picked = d.execute_script(
            "const e=[...document.querySelectorAll('[role=menuitemradio],[role=menuitem],[role=option]')]"
            ".find(x=>(x.textContent||'').includes('Anyone with the link'));if(e){e.click();return true}return false")
        time.sleep(1.5)
        label = d.find_element(By.XPATH, "//button[contains(@aria-label,'general access')]").get_attribute("aria-label") or ""
        shared = bool(picked) and "Anyone with the link" in label     # confirm the setting really changed
        _click_xpath(d, "//button[normalize-space()='Done']", 4)
        d.switch_to.default_content()
        return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing" if shared else None
    except Exception:
        return None
    finally:
        try:
            d.close()
        finally:
            d.switch_to.window(main)


def get_resume_link(d, pdf_path: str, notes: list) -> str | None:
    """Shareable 'anyone with the link' Drive link of THIS job's tailored resume (uploaded once, then cached).
    Retries once. Returns None on failure - the base resume is never substituted."""
    if pdf_path in _cache:
        return _cache[pdf_path]
    for _ in range(2):
        link = upload_to_drive(d, pdf_path) if pdf_path else None
        if link:
            _cache[pdf_path] = link
            return link
    notes.append("could not create the Drive link for this job's resume")
    return None


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
