"""Resume uploads: to Google Drive (to answer 'share a Drive link of your resume') and into Google Forms upload questions.

Everything runs in the same Chrome window / profile that is signed in to Google (see google_login.py).
"""
import os
import re
import shutil
import tempfile
import time
import uuid
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


def _rename_in_drive(d, current_stem: str, new_name: str) -> bool:
    """Rename the just-uploaded file (found by its unique temporary name) in the Drive list. Best effort."""
    from urllib.parse import quote
    from selenium.webdriver.common.keys import Keys
    try:
        d.get("https://drive.google.com/drive/search?q=" + quote(current_stem))
        end = time.time() + 30
        row = None
        while time.time() < end and row is None:
            row = next((r for r in d.find_elements(By.CSS_SELECTOR, "[data-id]") if current_stem in (r.text or "")), None)
            time.sleep(1)
        if row is None:
            return False
        row.click()
        time.sleep(0.8)
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(d).key_down(Keys.CONTROL).key_down(Keys.ALT).send_keys("e").key_up(Keys.ALT).key_up(Keys.CONTROL).perform()
        time.sleep(1.5)                                   # Rename dialog opens with its text box focused
        box = d.switch_to.active_element
        box.send_keys(Keys.CONTROL, "a")
        box.send_keys(new_name)
        box.send_keys(Keys.ENTER)
        time.sleep(3)
        d.get("https://drive.google.com/drive/search?q=" + quote(current_stem))   # renamed = the temporary name is gone
        time.sleep(5)
        return not any(current_stem in (r.text or "") for r in d.find_elements(By.CSS_SELECTOR, "[data-id]"))
    except Exception:
        return False


def upload_to_drive(d, pdf_path: str) -> str | None:
    """Upload exactly this job's PDF to Drive in a new tab, share it as 'Anyone with the link' (viewer), and return
    the link. Returns None if any step fails - the caller must NOT substitute another resume silently."""
    if os.environ.get("JA_HEADLESS"):   # cloud runner has no screen/file dialog: the caller reports "apply manually"
        return None
    import pyautogui  # Drive's "File upload" opens a native Windows dialog; we type the path into it

    final_name = os.path.basename(os.path.abspath(pdf_path))             # e.g. Hari_Om_Singh_CV.pdf (same for every job)
    token = uuid.uuid4().hex[:8]
    tmp_dir = tempfile.mkdtemp(prefix="cv_upload_")
    pdf_abs = os.path.join(tmp_dir, f"{os.path.splitext(final_name)[0]}__{token}.pdf")
    shutil.copy(os.path.abspath(pdf_path), pdf_abs)                      # unique name: Drive search finds exactly this file
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
        _rename_in_drive(d, stem, final_name)     # recruiters see "<Your_Name>_CV.pdf", not the temporary name

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
    st = os.stat(pdf_path) if pdf_path and os.path.exists(pdf_path) else None
    key = (pdf_path, st.st_mtime_ns, st.st_size) if st else pdf_path     # a re-rendered resume must get a fresh link
    if key in _cache:
        return _cache[key]
    for _ in range(2):
        link = upload_to_drive(d, pdf_path) if pdf_path else None
        if link:
            _cache[key] = link
            return link
    notes.append("could not create the Drive link for this job's resume")
    return None


def _attached(d, title: str, file_name: str) -> bool:
    """True when the form question `title` now lists `file_name` as an attached file."""
    for it in d.find_elements(By.CSS_SELECTOR, "div[role='listitem']"):
        if title in it.text and file_name in it.text:
            return True
    return False


def upload_in_google_form(d, item, pdf_path: str, notes: list, title: str) -> bool:
    """Handle a Google Forms 'file upload' question: Add file -> pick this job's PDF. Only returns True when the file
    name really shows up on the form (the dialog can stay open without attaching anything)."""
    pdf_abs = os.path.abspath(pdf_path)
    file_name = os.path.basename(pdf_abs)
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

        # method 1: hand the file to the dialog's hidden file input
        d.switch_to.frame(frame)
        found = d.find_elements(By.CSS_SELECTOR, "input[type='file']")
        if found:
            found[0].send_keys(pdf_abs)
        d.switch_to.default_content()
        end = time.time() + 12
        while time.time() < end and not _attached(d, title, file_name):
            time.sleep(1)

        # method 2: Browse button -> Windows/GTK file dialog -> type the path (same as the Drive upload)
        if not _attached(d, title, file_name):
            import pyautogui
            frame = next((f for f in d.find_elements(By.TAG_NAME, "iframe") if "picker" in (f.get_attribute("src") or "")), None)
            if frame is not None:
                d.switch_to.frame(frame)
                _click_xpath(d, "//*[normalize-space()='Browse']", 5)
                d.switch_to.default_content()
                time.sleep(2.5)
                pyautogui.write(pdf_abs, interval=0.01)
                pyautogui.press("enter")
                end = time.time() + 40
                while time.time() < end and not _attached(d, title, file_name):
                    time.sleep(1)

        if not _attached(d, title, file_name):
            raise RuntimeError("the file did not attach")
        return True
    except Exception as e:
        try:
            d.switch_to.default_content()
            d.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        except Exception:
            pass
        notes.append(f"resume upload failed for '{title[:30]}': {e}")
        return False
