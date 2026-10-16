"""OpenAI-compatible client returning parsed JSON, with a model fallback chain and an on-disk answer cache.

- Each (provider, model) in cfg.ai_chain is tried in order. When one hits its rate limit (per-minute: wait and retry;
  per-day: skip it for a while) the next one is used.
- Identical requests are answered from telegram_apply/llm_cache.jsonl, so re-processing the same posts is free.
"""
import hashlib
import json
import os
import re
import time
from openai import APIStatusError, OpenAI, RateLimitError
from config import telegram_apply as cfg

CACHE = "telegram_apply/llm_cache.jsonl"
_BASE_URLS = {"groq": "https://api.groq.com/openai/v1",
              "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/"}
_clients: dict = {}
_dead_until: dict = {}   # (provider, model) -> unix time it may be tried again
_cache: dict | None = None


def _key_for(provider: str) -> str:
    return {"groq": cfg.groq_api_key, "gemini": cfg.gemini_api_key, "openai": cfg.openai_api_key}.get(provider, "")


def _client(provider: str) -> OpenAI:
    if provider not in _clients:
        _clients[provider] = OpenAI(api_key=_key_for(provider), base_url=_BASE_URLS.get(provider))
    return _clients[provider]


def _chain() -> list[tuple[str, str]]:
    return [(p, m) for p, m in cfg.ai_chain if _key_for(p)]


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        _cache = {}
        if os.path.exists(CACHE):
            with open(CACHE, encoding="utf-8") as f:
                for line in f:
                    try:
                        k, v = json.loads(line)
                        _cache[k] = v
                    except ValueError:
                        pass
    return _cache


def _wait_seconds(err: Exception) -> float:
    m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", str(err))
    if not m or not any(m.groups()):
        return 20
    return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3) or 0)


def _call(system: str, user: str, temperature: float):
    """One completion via the first usable model in the chain."""
    errors = []
    for provider, model in _chain():
        if _dead_until.get((provider, model), 0) > time.time():
            continue
        for attempt in range(4):
            try:
                return _client(provider).chat.completions.create(
                    model=model, temperature=temperature, response_format={"type": "json_object"},
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
            except RateLimitError as e:
                wait = 3600 if re.search(r"insufficient_quota|no credits|billing", str(e), re.I) else _wait_seconds(e)
                if wait > 90 or attempt == 3:  # daily quota (or hopeless): park this model, use the next
                    _dead_until[(provider, model)] = time.time() + min(wait, 3600)
                    errors.append(f"{provider}/{model}: rate limit")
                    break
                time.sleep(wait + 1)
            except APIStatusError as e:
                if e.status_code in (401, 403, 404):  # model missing / key not allowed: skip it for a while
                    _dead_until[(provider, model)] = time.time() + 1800
                errors.append(f"{provider}/{model}: {e.status_code} {str(e)[:80]}")  # a 400 only skips THIS request
                break
    raise RuntimeError("All AI models are rate-limited or unavailable (" + "; ".join(errors) + "). "
                       "Wait for the quota to reset or add credit / another key in config/telegram_apply.py")


def chat_json(system: str, user: str, temperature: float = 0.2) -> dict:
    cache = _load_cache()
    key = hashlib.sha256(json.dumps([system, user, temperature]).encode("utf-8")).hexdigest()
    if key in cache:
        return cache[key]
    for attempt in range(2):  # the model occasionally returns malformed JSON; retry once
        resp = _call(system, user, temperature)
        try:
            data = json.loads(resp.choices[0].message.content)
            break
        except (json.JSONDecodeError, TypeError):
            if attempt:
                raise
    cache[key] = data
    with open(CACHE, "a", encoding="utf-8") as f:
        f.write(json.dumps([key, data], ensure_ascii=False) + "\n")
    return data
