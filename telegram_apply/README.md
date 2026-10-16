# Telegram auto-apply + AI resume tailoring

Watches Telegram job channels, picks the jobs that fit you, writes a tailored one-page resume for each, and applies
(email to the recruiter, Google Forms, or any company career page). Runs daily from a small web control panel.

## Setup
1. `pip install -r requirements.txt`
2. Copy `config/telegram_apply.example.py` to `config/telegram_apply.py` and fill in:
   - Telegram `api_id` / `api_hash` (https://my.telegram.org -> API development tools)
   - an AI key (Groq, Gemini or OpenAI) - the chain in `ai_chain` falls back to the next model when one is rate-limited
   - `candidate_facts` (location, experience, relocation...), your Gmail + App Password for sending email
3. Put your current resume at `telegram_apply/base_resume.pdf`.
4. Log in once: `python -m telegram_apply.login` (Telegram) and `python -m telegram_apply.google_login` (Google, for Google Forms).

## Run
- Control panel (daily schedule, time window, dry-run toggle, results): `python -m telegram_apply.web` -> http://localhost:5055
- Live mode (react to new posts instantly): `python -m telegram_apply.main`

Dry run is ON by default: everything is prepared but nothing is sent or submitted. Check the tailored PDFs in
`telegram_apply/output/` and the screenshots in `telegram_apply/output/proof/` before turning it off.

## Notes
- Experience, projects, summary and certifications only use facts from your real resume and `candidate_facts`.
  Skills you do not have are added only to the Skills line, and only when `add_missing_keywords` is on.
- Only jobs open to your graduation batch (`required_batch`) are applied to.
- CAPTCHAs and login walls on company sites are not bypassed; those jobs are marked "manual" in the results.
- Use responsibly and within each site's terms; you are responsible for what is submitted in your name.

## Resume uploads and Drive links
- When a form has a file-upload question for your resume/CV, that job's tailored PDF is attached.
- When a form asks for a Google Drive link to your resume, the tailored PDF is uploaded to your Drive, shared as
  "Anyone with the link" (viewer) and that link is used. It is always the resume made for that job; if the link cannot
  be created the job is marked "blocked" instead of using another resume.
- The Drive upload types the file path into Windows' file-open dialog (Windows only, uses `pyautogui`): do not use the
  mouse/keyboard for the few seconds while a Chrome window is uploading.
- Application emails are 120-150 words about you, then your name, email, phone, LinkedIn and GitHub, with the PDF attached.
- Optional setting `add_missing_keywords` adds job keywords you do not have to the Skills section only (never to
  experience); the results table lists them so you know what to learn before interviews.
