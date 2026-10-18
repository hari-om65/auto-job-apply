"""One-time Telegram login (asks for phone + code).

  python -m telegram_apply.login            -> the session used by the dashboard on this PC
  python -m telegram_apply.login runner     -> a SEPARATE session for the cloud runner (never share one session
                                               between two machines: Telegram logs the older one out)
"""
import sys
from telethon.sync import TelegramClient
from config import telegram_apply as cfg

session = "telegram_apply/tg_runner" if "runner" in sys.argv[1:] else cfg.tg_session
with TelegramClient(session, cfg.tg_api_id, cfg.tg_api_hash) as client:
    me = client.get_me()
    print(f"Logged in as {me.first_name} (session file: {session}.session).")
