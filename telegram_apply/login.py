"""One-time Telegram login (asks for phone + code). Run: python -m telegram_apply.login"""
from telethon.sync import TelegramClient
from config import telegram_apply as cfg

with TelegramClient(cfg.tg_session, cfg.tg_api_id, cfg.tg_api_hash) as client:
    me = client.get_me()
    print(f"Logged in as {me.first_name}. You can now start the web UI: python -m telegram_apply.web")
