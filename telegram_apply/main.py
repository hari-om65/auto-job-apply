"""Live mode: react to new channel posts as they arrive (the daily scheduled mode is in web.py).

Run from the repo root:  python -m telegram_apply.main
"""
import asyncio
from telethon import TelegramClient, events
from config import telegram_apply as cfg
from . import settings_store
from .pipeline import _load_state, process_post


async def run() -> None:
    s = settings_store.apply_to_config()
    state = _load_state()
    client = TelegramClient(cfg.tg_session, cfg.tg_api_id, cfg.tg_api_hash)
    await client.start()  # first run asks for phone number + login code

    wanted = {str(c).lstrip("@").lower() for c in s["channels"]}
    chats = []
    async for dlg in client.iter_dialogs():
        if wanted & {(dlg.name or "").lower(), str(getattr(dlg.entity, "username", "")).lower(), str(dlg.id)}:
            chats.append(dlg.entity)
    if not chats:
        raise SystemExit(f"None of {s['channels']} found in your Telegram chats")
    print("Watching:", [getattr(c, "title", c) for c in chats], "| DRY RUN" if cfg.dry_run else "| LIVE")

    loop = asyncio.get_running_loop()

    @client.on(events.NewMessage(chats=chats))
    async def _(ev):
        if ev.message.text:
            recs = await loop.run_in_executor(None, process_post, ev.message.text,
                                              f"{ev.chat_id}:{ev.message.id}", state, int(s["min_ats_score"]))
            for rec in recs:
                print(rec["job"], "->", rec["status"])

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(run())
