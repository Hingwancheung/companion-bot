"""
Model provider orchestration.

- Reads all configuration from environment variables (.env)
- Supports multiple providers with failover and cooldown
- Injects recent chat log and long-term memory into a single prompt
- Exposes:
    - ask_ai(prompt: str) -> str
    - LLMProvider.chat(messages: list[dict]) -> str (async API for bot.py)
"""

import os
import time
import random
import requests
from memory import load_memory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def read_recent_chat(path: str, max_chars: int = 1800, max_lines: int = 40) -> str:
    """
    Read the tail of today's chat log as short-term context.
    """
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    if not lines:
        return ""
    recent = lines[-max_lines:]
    joined = "\n".join(recent)
    if len(joined) <= max_chars:
        return joined
    return joined[-max_chars:]


# Debug toggle: controlled via .env (DEBUG_MODE=true/1/on/yes)
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() in ("1", "true", "yes", "on")


def _dbg(*args):
    """
    Centralized debug output. Prints only when DEBUG_MODE is enabled.
    """
    if DEBUG_MODE:
        print("[DBG]", *args)


# --- Utility helpers ---

def _now() -> float:
    return time.time()


def _get_env_list(name: str):
    v = os.getenv(name, "")
    if not v:
        return []
    return [x.strip() for x in v.split(",") if x.strip()]


# --- Provider-level scheduling configuration ---

PROVIDER_COOLDOWN_MIN = int(os.getenv("PROVIDER_COOLDOWN_MIN", "1"))  # minutes
PROVIDER_FAILS_BEFORE_SWITCH = int(os.getenv("PROVIDER_FAILS_BEFORE_SWITCH", "2"))
PROVIDER_STICKY_SEC = int(os.getenv("PROVIDER_STICKY_SEC", "600"))

_COOLDOWN: dict[str, float] = {}
_COOLDOWN_SECONDS = max(5, PROVIDER_COOLDOWN_MIN * 60)  # min 5s

_LAST_PROVIDER: str | None = None
_LAST_PROVIDER_TS: float = 0.0
_FAIL_COUNTS: dict[str, int] = {}


def _is_cooling(key: str) -> bool:
    t = _COOLDOWN.get(key)
    return False if not t else (_now() - t < _COOLDOWN_SECONDS)


def _mark_bad(key: str):
    _COOLDOWN[key] = _now()


# --- Env-driven configuration ---

ORDER = [
    x.strip()
    for x in os.getenv("PROVIDER_ORDER", "gemini,openrouter").split(",")
    if x.strip()
]

# API keys
GEMINI_KEYS = _get_env_list("GEMINI_API_KEYS")
OPENROUTER_KEYS = _get_env_list("OPENROUTER_API_KEYS")
EDENAI_KEY = os.getenv("EDENAI_API_KEY", "").strip()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()

# Models / endpoints
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/auto")
EDENAI_PROVIDER = os.getenv("EDENAI_PROVIDER", "google")
EDENAI_MODEL = os.getenv("EDENAI_MODEL", "gemini-1.5-flash")
GEMINI_API_BASE = os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# Generation params
GEMINI_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.55"))
GEMINI_MAX_TOKENS = int(os.getenv("GEMINI_MAX_TOKENS", "800"))

OPENROUTER_TEMPERATURE = float(os.getenv("OPENROUTER_TEMPERATURE", "0.5"))
OPENROUTER_MAX_TOKENS = int(os.getenv("OPENROUTER_MAX_TOKENS", "700"))

EDENAI_TEMPERATURE = float(os.getenv("EDENAI_TEMPERATURE", "0.5"))
EDENAI_MAX_TOKENS = int(os.getenv("EDENAI_MAX_TOKENS", "700"))

DEEPSEEK_TEMPERATURE = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.8"))
DEEPSEEK_MAX_TOKENS = int(os.getenv("DEEPSEEK_MAX_TOKENS", "800"))

# Advanced sampling (currently only used for Deepseek; others commented out)
DEEPSEEK_TOP_P = float(os.getenv("DEEPSEEK_TOP_P", "1.0"))
DEEPSEEK_PRESENCE_PENALTY = float(os.getenv("DEEPSEEK_PRESENCE_PENALTY", "0.0"))
DEEPSEEK_FREQUENCY_PENALTY = float(os.getenv("DEEPSEEK_FREQUENCY_PENALTY", "0.0"))

# Timeouts
GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "45"))


# --- Provider implementations ---

def _call_gemini(prompt: str) -> str | None:
    if not GEMINI_KEYS:
        return None

    candidates = [k for k in GEMINI_KEYS if not _is_cooling(f"gemini:{k}")]
    if not candidates:
        return None

    key = random.choice(candidates)

    url = f"{GEMINI_API_BASE}/v1/models/{GEMINI_MODEL}:generateContent?key={key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": GEMINI_TEMPERATURE,
            "maxOutputTokens": GEMINI_MAX_TOKENS,
        },
    }

    try:
        r = requests.post(url, json=payload, timeout=GEMINI_TIMEOUT)
        _dbg("GEMINI", r.status_code, r.text[:300])

        if r.status_code == 200:
            j = r.json()

            txt = None
            try:
                cands = j.get("candidates", [])
                if cands:
                    content = cands[0].get("content")
                    if isinstance(content, dict):
                        for p in content.get("parts") or []:
                            if p.get("text"):
                                txt = p["text"]
                                break
                    elif isinstance(content, list):
                        for p in content:
                            if isinstance(p, dict) and p.get("text"):
                                txt = p["text"]
                                break
            except Exception as e:
                _dbg("GEMINI PARSE_EXC", repr(e))

            if txt:
                return txt

            # 200 OK but no text – treat as a soft failure and return a neutral message
            _dbg("GEMINI NO_TEXT", j)
            return (
                "The model responded without any usable text.\n"
                "You can try sending your message again or rephrasing it."
            )

        # Authentication / quota / rate limit → cool down this key
        if r.status_code in (401, 403, 429):
            _mark_bad(f"gemini:{key}")
            return None

        # Other HTTP errors (e.g. 5xx)
        return "__TEMP_FAIL__"

    except Exception as e:
        _dbg("GEMINI EXC", repr(e))
        return "__TEMP_FAIL__"


def _call_openrouter(prompt: str) -> str | None:
    if not OPENROUTER_KEYS:
        return None

    candidates = [k for k in OPENROUTER_KEYS if not _is_cooling(f"openrouter:{k}")]
    if not candidates:
        return None

    key = random.choice(candidates)

    url = "https://openrouter.ai/api/v1/chat/completions"
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": OPENROUTER_TEMPERATURE,
        "max_tokens": OPENROUTER_MAX_TOKENS,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://example.com",
        "X-Title": "telegram-bot",
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=45)
        _dbg("OPENROUTER", r.status_code, r.text[:300])

        if r.status_code == 200:
            j = r.json()
            return j["choices"][0]["message"]["content"]

        if r.status_code in (401, 403, 429):
            _mark_bad(f"openrouter:{key}")
            return None

        return "__TEMP_FAIL__"

    except Exception as e:
        _dbg("OPENROUTER EXC", repr(e))
        return "__TEMP_FAIL__"


def _call_edenai(prompt: str) -> str | None:
    if not EDENAI_KEY:
        return None

    # If recently cooled down due to errors, skip temporarily
    if _is_cooling("edenai"):
        return None

    url = "https://api.edenai.run/v2/text/chat"
    headers = {"Authorization": f"Bearer {EDENAI_KEY}"}
    payload = {
        "providers": EDENAI_PROVIDER,
        "text": prompt,
        "model": EDENAI_MODEL,
        "temperature": EDENAI_TEMPERATURE,
        "max_tokens": EDENAI_MAX_TOKENS,
        "chat_history": [],
        "response_as_dict": True,
        "attributes_as_list": False,
        "show_original_response": False,
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=45)
        _dbg("EDENAI", r.status_code, r.text[:300])

        if r.status_code == 200:
            j = r.json()
            return j.get(EDENAI_PROVIDER, {}).get("generated_text")

        if r.status_code in (401, 403, 429):
            _mark_bad("edenai")
            return None

        return "__TEMP_FAIL__"

    except Exception as e:
        _dbg("EDENAI EXC", repr(e))
        return "__TEMP_FAIL__"


def _call_deepseek(prompt: str) -> str | None:
    if not DEEPSEEK_API_KEY:
        return None

    if _is_cooling("deepseek"):
        return None

    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": DEEPSEEK_TEMPERATURE,
        "max_tokens": DEEPSEEK_MAX_TOKENS,
        # Advanced params are read from env but not required here:
        # "top_p": DEEPSEEK_TOP_P,
        # "presence_penalty": DEEPSEEK_PRESENCE_PENALTY,
        # "frequency_penalty": DEEPSEEK_FREQUENCY_PENALTY,
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=45)
        _dbg("DEEPSEEK", r.status_code, r.text[:300])

        if r.status_code == 200:
            try:
                j = r.json()
                return j["choices"][0]["message"]["content"]
            except Exception as e:
                _dbg("DEEPSEEK NO_TEXT", repr(e))
                return "__TEMP_FAIL__"

        # 401 / 403 / 429 / 402 (e.g. insufficient credit) → cool down temporarily
        if r.status_code in (401, 403, 429, 402):
            _mark_bad("deepseek")
            return None

        return "__TEMP_FAIL__"

    except Exception as e:
        _dbg("DEEPSEEK EXC", repr(e))
        return "__TEMP_FAIL__"


# --- Unified entrypoint ---

def ask_ai(prompt: str) -> str:
    """
    Synchronous dispatcher over all configured providers.

    Behaviour:
    - Tries providers in ORDER (from env).
    - Treats "__TEMP_FAIL__" as a transient failure (5xx / timeout / parse error).
    - Treats None as a hard failure (auth / quota / invalid key → provider is cooled down).
    - Recent successful provider is preferred for PROVIDER_STICKY_SEC seconds.
    - If a provider hits PROVIDER_FAILS_BEFORE_SWITCH transient failures in a row,
      it is no longer treated as "sticky".
    """
    global _LAST_PROVIDER, _LAST_PROVIDER_TS, _FAIL_COUNTS

    had_temp_fail = False

    providers_order = [p.strip().lower() for p in ORDER if p.strip()]
    now = _now()

    # Prefer the most recently successful provider within sticky window
    if _LAST_PROVIDER and (now - _LAST_PROVIDER_TS) < PROVIDER_STICKY_SEC:
        if _LAST_PROVIDER in providers_order:
            providers_order.remove(_LAST_PROVIDER)
            providers_order.insert(0, _LAST_PROVIDER)

    for provider in providers_order:
        p = provider.lower()

        if p == "gemini":
            res = _call_gemini(prompt)
        elif p == "openrouter":
            res = _call_openrouter(prompt)
        elif p == "edenai":
            res = _call_edenai(prompt)
        elif p == "deepseek":
            res = _call_deepseek(prompt)
        else:
            res = None

        # Transient error: keep track but continue to next provider
        if res == "__TEMP_FAIL__":
            had_temp_fail = True
            _FAIL_COUNTS[p] = _FAIL_COUNTS.get(p, 0) + 1

            if _FAIL_COUNTS[p] >= PROVIDER_FAILS_BEFORE_SWITCH:
                if _LAST_PROVIDER == p:
                    _LAST_PROVIDER = None
            continue

        # Hard failure: auth / quota / configuration
        if res is None:
            _FAIL_COUNTS[p] = 0
            if _LAST_PROVIDER == p:
                _LAST_PROVIDER = None
            continue

        # Successful response
        if isinstance(res, str) and res.strip():
            _FAIL_COUNTS[p] = 0
            _LAST_PROVIDER = p
            _LAST_PROVIDER_TS = now
            return res

        # Any other unexpected case – try next provider
        continue

    # All providers failed
    if had_temp_fail:
        # CUSTOMIZE: end-user message for temporary connectivity issues
        return (
            "I’m having trouble reaching the language model services right now.\n"
            "This is likely a temporary issue—please try again in a moment."
        )
    else:
        # CUSTOMIZE: end-user message for configuration / key problems
        return (
            "No language model providers are currently available.\n"
            "Please check your API keys, quotas, and configuration."
        )


# --- Async wrapper for bot.py ---

class LLMProvider:
    """
    Async interface used by bot.py.

    Responsibilities:
    - Merge system messages into a single user-facing prompt string.
    - Attach recent chat context and long-term memory summaries.
    - Delegate to ask_ai().
    """

    def __init__(self):
        default_chat_today = os.path.join(BASE_DIR, "data", "chat_today.txt")
        self.chat_today_path = os.getenv("CHAT_TODAY_PATH", default_chat_today)
        # Max number of characters of long-term memory to inject each time
        self.long_mem_chars = int(os.getenv("LONG_MEMORY_CHARS", "1500"))

    async def chat(self, messages: list[dict]) -> str:
        # 1) Merge the message contents into a single string
        parts = [m["content"] for m in messages if m.get("content")]
        user_prompt = "\n".join(parts)

        # 2) Short-term context: recent chat for today
        recent_chat = read_recent_chat(self.chat_today_path, max_chars=2000, max_lines=50)
        recent_block = ""
        if recent_chat:
            recent_block = (
                "RECENT_CHAT_CONTEXT (do not repeat verbatim; use for continuity):\n"
                f"{recent_chat}\n\n"
            )

        # 3) Long-term memory: summaries across days
        long_mem = load_memory()
        long_block = ""
        if long_mem:
            long_block = (
                "LONG_TERM_MEMORY (high-level summaries; apply gently, not verbatim):\n"
                f"{long_mem[-self.long_mem_chars:]}\n\n"
            )

        # 4) Final prompt: long-term → short-term → current turn
        final_prompt = f"{long_block}{recent_block}{user_prompt}"

        return ask_ai(final_prompt)