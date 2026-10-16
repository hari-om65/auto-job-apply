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
- The resume only uses facts from your real resume and `candidate_facts`; skills you do not have are never added.
- Only jobs open to your graduation batch (`required_batch`) are applied to.
- CAPTCHAs and login walls on company sites are not bypassed; those jobs are marked "manual" in the results.
- Use responsibly and within each site's terms; you are responsible for what is submitted in your name.
