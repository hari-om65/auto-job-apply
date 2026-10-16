"""COPY THIS FILE to config/telegram_apply.py and fill in your own values.
config/telegram_apply.py is git-ignored so your keys never get committed.
"""

# --- Telegram (get api_id / api_hash at https://my.telegram.org -> API development tools) ---
tg_api_id = 0
tg_api_hash = ""
tg_session = "telegram_apply/tg_session"        # login session file (created on first run)
tg_channels = ["Premium Membership"]            # channel titles, @usernames or numeric ids to watch
tg_backfill_last = 0                            # also process the last N old messages on start (0 = new only)

# --- OpenAI (ChatGPT API) ---
openai_api_key = ""
openai_model = "gpt-4o-mini"

# Which AI to use: "groq", "gemini" or "openai"
ai_provider = "groq"
gemini_api_key = ""
gemini_model = "gemini-2.5-flash"
groq_api_key = ""
groq_model = "openai/gpt-oss-120b"

# Models tried in order. When one hits its rate limit, the next is used. (Entries without a key are skipped.)
ai_chain = [
    ("groq", "openai/gpt-oss-120b"),
    ("groq", "qwen/qwen3.8-27b"),
    ("groq", "openai/gpt-oss-20b"),
    ("gemini", "gemini-3.5-flash-lite"),
    ("gemini", "gemini-3.5-flash"),
    ("openai", "gpt-4o-mini"),
]

# --- Your resume + profile ---
base_resume_pdf = "telegram_apply/base_resume.pdf"   # put your current resume here
candidate_profile = {
    "target_roles": ["Software Engineer", "Backend Developer"],
    "graduation_batch": 2027,
    "locations": ["Remote", "Bangalore"],
    "min_monthly_stipend_inr": 0,
    "notes": "Describe yourself in one line.",
}
add_missing_keywords = True   # add job keywords you do not have yet to the Skills section (never to experience/projects)
required_batch = "2027"    # only apply to jobs open to this graduation year ("" = no filter)
min_match_score = 60        # skip jobs the AI scores below this (0-100)
target_ats_score = 85       # keyword coverage the resume should reach (0-100)

# --- Applying ---
dry_run = True              # True = prepare everything but DON'T send/submit. Set False when you trust it.
max_applications_per_day = 25

# Email to recruiters (Gmail: use an App Password, not your normal password)
smtp_host = "smtp.gmail.com"
smtp_port = 465
smtp_user = ""
smtp_password = ""
sender_name = ""

# Fixed facts about you. Forms, emails and resumes use these exactly (add more, e.g. "notice_period": "Immediately").
candidate_facts = {
    "current_location": "City, State, Country",
    "willing_to_relocate": "Yes",
    "total_experience": "1 year",
    # Skills you REALLY have that are not obvious from your resume (e.g. "Excel", "n8n", "Zapier"). The resume writer may use them as keywords.
    "extra_skills": [],
}

# Google Forms (Selenium). Chrome profile where you are logged into Google (needed for file-upload questions)
chrome_user_data_dir = "telegram_apply/chrome_profile"   # sign in once with: python -m telegram_apply.google_login   # e.g. r"C:\Users\you\AppData\Local\Google\Chrome\User Data\SeleniumProfile"

# --- LinkedIn jobs (run from the dashboard through the Easy Apply bot) ---
candidate_identity = {            # used for the LinkedIn / company application forms
    "first_name": "FIRST", "middle_name": "", "last_name": "LAST", "phone_number": "0000000000",
    "city": "City", "state": "State", "zipcode": "", "country": "India",
}
linkedin_answers = {              # answers to common Easy Apply questions (edit freely)
    "years_of_experience": "1", "require_visa": "No", "legally_authorized": "Yes",
    "desired_salary": 400000, "current_ctc": 0, "notice_period": 0,
}
linkedin_username = ""            # optional; otherwise sign in once: python -m telegram_apply.google_login linkedin
linkedin_password = ""
