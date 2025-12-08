"""
Telegram emotional-support / companion-style bot.

Features:
- Handles /start and /ping
- Routes text to LLMProvider
- Tracks last user activity and sends proactive nudges after inactivity
- Quiet hours with configurable time window
- Streams daily chat to a log file and periodically summarizes to long-term memory
- Supports backslash "\"-separated multi-part responses
- Supports photo messages via an external vision provider
"""

import os
import json
import asyncio
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from providers import LLMProvider
from memory import update_memory
from vision_provider import describe_image

# --- Basic config & paths ---

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID", "0"))

SPLIT_DELAY = int(os.getenv("SPLIT_DELAY", "2"))
NUDGE_DELAY_MIN = int(os.getenv("NUDGE_DELAY_MIN", "150"))         # default: 2.5h
NUDGE_COOLDOWN_MIN = int(os.getenv("NUDGE_COOLDOWN_MIN", "120"))

QUIET_TZ = os.getenv("QUIET_TZ", "Asia/Shanghai")
QUIET_START = os.getenv("QUIET_START", "23:00")
QUIET_END = os.getenv("QUIET_END", "09:00")

CHAT_WINDOW_LINES = int(os.getenv("CHAT_WINDOW_LINES", "150"))
CHAT_BUFFER_MAX_LINES = int(os.getenv("CHAT_BUFFER_MAX_LINES", "300"))

STATE_FILE = os.path.join(BASE_DIR, "state.json")
DAILY_LOG = os.path.join(BASE_DIR, "data", "chat_today.txt")


# --- Helpers: prompt files ---

def read_txt(name: str, default: str = "") -> str:
    path = os.path.join(BASE_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return default


# CUSTOMIZE: persona / style prompts are loaded from these files
CHAR_PROMPT = read_txt("character.txt", "")
STYLE_PROMPT = read_txt("style.txt", "")


# --- Persistent state (last activity / last nudge) ---

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_user_ts": None, "last_nudge_ts": None}


def save_state(st: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f)


state = load_state()


# --- Time helpers / quiet hours ---

def now_tz() -> datetime:
    return datetime.now(ZoneInfo(QUIET_TZ))


def parse_hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(hour=int(hh), minute=int(mm))


def is_quiet(dt: datetime) -> bool:
    """
    Return True if dt is within the configured quiet-hours window.
    Handles windows that cross midnight (e.g. 23:00–09:00).
    """
    start_t = parse_hhmm(QUIET_START)
    end_t = parse_hhmm(QUIET_END)
    t = dt.time()

    if start_t > end_t:  # crosses midnight
        return (t >= start_t) or (t < end_t)
    return start_t <= t < end_t


# --- LLM message builder ---

def build_messages(user_text: str):
    """
    Build a message list for the LLM, injecting persona/style and current time.
    """
    now_local = now_tz()
    current_time = now_local.strftime("%Y-%m-%d %H:%M")

    system_prompt = (
        f"{CHAR_PROMPT}\n\n"
        f"{STYLE_PROMPT}\n\n"
        f"Current local time is {current_time}.\n"
        "Do not explicitly mention the time or reveal the exact timestamp.\n"
        "When you need to send multiple messages, separate them with a backslash '\\'."
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]


# --- Chat logging and memory windowing ---

CHAT_LOG = []
MAX_LOG_LINES = 100


def load_daily_log() -> str:
    if os.path.exists(DAILY_LOG):
        with open(DAILY_LOG, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def clear_daily_log():
    global CHAT_LOG
    CHAT_LOG.clear()
    with open(DAILY_LOG, "w", encoding="utf-8") as f:
        f.write("")


def maybe_summarize_chatlog():
    """
    Sliding window:
    - If chat_today.txt exceeds CHAT_BUFFER_MAX_LINES,
      summarize the oldest CHAT_WINDOW_LINES lines into long-term memory,
      keep only the remaining lines in the log.
    """
    global CHAT_LOG

    text = load_daily_log()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) <= CHAT_BUFFER_MAX_LINES:
        return

    window_size = min(CHAT_WINDOW_LINES, len(lines))
    chunk_lines = lines[:window_size]
    remain_lines = lines[window_size:]

    chunk_text = "\n".join(chunk_lines)
    remain_text = "\n".join(remain_lines)

    try:
        if chunk_text.strip():
            update_memory(chunk_text)
    except Exception:
        # Intentionally swallow errors: memory failure should not crash the bot
        pass

    with open(DAILY_LOG, "w", encoding="utf-8") as f:
        if remain_text:
            f.write(remain_text + "\n")
        else:
            f.write("")

    CHAT_LOG = remain_lines[-MAX_LOG_LINES:]


def log_append(line: str):
    CHAT_LOG.append(line)
    if len(CHAT_LOG) > MAX_LOG_LINES:
        del CHAT_LOG[0]

    os.makedirs(os.path.dirname(DAILY_LOG), exist_ok=True)
    with open(DAILY_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    maybe_summarize_chatlog()


# --- Multi-part sending ---

async def send_split_to_chat(bot, chat_id: int, text: str):
    """
    Support backslash-separated segments and chunking into <= 3500-char messages.
    """
    parts = [p.strip() for p in text.split("\\") if p.strip()]
    if not parts:
        parts = [text]

    for part in parts:
        chunks = [part[i:i + 3500] for i in range(0, len(part), 3500)]
        for c in chunks:
            await asyncio.sleep(SPLIT_DELAY)
            await bot.send_message(
                chat_id=chat_id,
                text=c,
                parse_mode=ParseMode.HTML,
            )


# --- Auto-nudge loop ---

async def nudge_loop(app):
    """
    Background task that periodically checks for inactivity.
    If:
      - user has spoken at least once,
      - last message is older than NUDGE_DELAY_MIN,
      - last nudge is older than NUDGE_COOLDOWN_MIN,
      - and current time is outside quiet hours,
    the bot sends a proactive message.
    """
    while True:
        await asyncio.sleep(15)
        try:
            if OWNER_CHAT_ID == 0:
                continue

            now = now_tz()
            if is_quiet(now):
                continue

            last_user_ts = state.get("last_user_ts")
            if not last_user_ts:
                continue

            last_user = datetime.fromisoformat(last_user_ts).astimezone(ZoneInfo(QUIET_TZ))
            due_time = last_user + timedelta(minutes=NUDGE_DELAY_MIN)

            last_nudge_ts = state.get("last_nudge_ts")
            if last_nudge_ts:
                last_nudge = datetime.fromisoformat(last_nudge_ts).astimezone(ZoneInfo(QUIET_TZ))
                if (now - last_nudge) < timedelta(minutes=NUDGE_COOLDOWN_MIN):
                    continue

            if now >= due_time:
                # CUSTOMIZE: how the model should phrase proactive check-ins
                nudge_user_text = (
                    f"The user has been silent for {NUDGE_DELAY_MIN} minutes.\n"
                    "As an emotional-support assistant, send a brief, proactive check-in.\n"
                    "- Keep the tone gentle and non-intrusive.\n"
                    "- You may express that you noticed their silence, or offer a small topic or question.\n"
                    "- Use backslashes '\\' to split into several shorter messages."
                )
                msgs = build_messages(nudge_user_text)
                reply = await llm.chat(msgs)

                await send_split_to_chat(app.bot, OWNER_CHAT_ID, reply)
                state["last_nudge_ts"] = now.isoformat()
                save_state(state)
                log_append(f"BOT: {reply}")

        except Exception:
            # Do not crash the main loop on nudge failures
            pass


# --- Commands ---

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # CUSTOMIZE: /start greeting copy
    await send_split_to_chat(context.bot, chat_id, "Hello. I'm here and listening.")


async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong ✅")


# --- Text messages ---

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global state

    if not update.message:
        return
    text = (update.message.text or "").strip()
    if not text:
        return

    user = update.effective_user.first_name or "User"
    log_append(f"{user}: {text}")

    state["last_user_ts"] = now_tz().isoformat()
    save_state(state)

    msgs = build_messages(text)
    reply = await llm.chat(msgs)

    chat_id = update.effective_chat.id
    await send_split_to_chat(context.bot, chat_id, reply)
    log_append(f"BOT: {reply}")


# --- Photo messages ---

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Photo flow:
      1) Download the image.
      2) Convert it to a textual description via describe_image().
      3) Ask the LLM to reply based on that description.
    """
    global state

    if not update.message or not update.message.photo:
        return

    chat_id = update.effective_chat.id

    user = update.effective_user.first_name or "User"
    log_append(f"{user}: [photo sent]")

    state["last_user_ts"] = now_tz().isoformat()
    save_state(state)

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    img_bytes = await file.download_as_bytearray()

    raw_desc = describe_image(bytes(img_bytes), "Please describe this image in detail.")
    if not raw_desc or "error" in raw_desc.lower():
        # CUSTOMIZE: fallback wording on vision failure
        fallback = (
            "Something went wrong while processing the picture.\n"
            "If you’d like, you can tell me what’s in it instead."
        )
        await update.message.reply_text(fallback)
        return

    # CUSTOMIZE: instruction for image-based replies
    user_text = (
        "You received a new photo from the user.\n"
        "The vision model has converted the image into this description:\n"
        "-------- IMAGE DESCRIPTION START --------\n"
        f"{raw_desc.strip()}\n"
        "-------- IMAGE DESCRIPTION END --------\n\n"
        "Reply in character as the assistant.\n"
        "- React explicitly to details from the description (colors, objects, setting, pose, etc.).\n"
        "- Then continue in your usual conversational style.\n"
        "- Make it clear that you are responding to what is visible in the image."
    )

    msgs = build_messages(user_text)
    reply = await llm.chat(msgs)

    await send_split_to_chat(context.bot, chat_id, reply)
    log_append(f"BOT (photo): {reply}")


# --- Main entrypoint ---

if __name__ == "__main__":
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN missing in .env")

    llm = LLMProvider()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("ping", ping_cmd))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    async def start_nudge(app_):
        app_.create_task(nudge_loop(app_))

    app.post_init = start_nudge

    print("Bot is running...")
    app.run_polling()