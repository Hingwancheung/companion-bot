"""
Long-term memory management for the companion bot.

- Stores high-level "memory entries" in data/memory.txt
- Enforces an optional max size (characters) on the memory file
- Summarizes conversation chunks into structured entries with importance scores
"""

import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, "data")
MEMORY_FILE = os.path.join(DATA_DIR, "memory.txt")

# If MAX_MEMORY_CHARS is "none", total size is unlimited.
_raw_max_chars = os.getenv("MAX_MEMORY_CHARS", "10000").strip().lower()
if _raw_max_chars == "none":
    MAX_MEMORY_CHARS = None
else:
    try:
        MAX_MEMORY_CHARS = int(_raw_max_chars)
    except ValueError:
        MAX_MEMORY_CHARS = 10000  # fallback

# Target length for a single memory summary (characters; best-effort)
MEMORY_SUMMARY_CHARS = int(os.getenv("MEMORY_SUMMARY_CHARS", "400"))


def load_memory() -> str:
    """
    Load the long-term memory file, optionally clipping to the last MAX_MEMORY_CHARS.
    """
    if not os.path.exists(MEMORY_FILE):
        return ""
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        text = f.read()
    if MAX_MEMORY_CHARS is None:
        return text
    return text[-MAX_MEMORY_CHARS:]


def _call_memory_model(prompt: str) -> str:
    """
    Thin wrapper around providers.ask_ai() dedicated to memory summarization.

    If MEMORY_MODEL is set, this temporarily overrides the OpenRouter model
    and generation params while producing the summary, then restores them.
    """
    import providers

    MEMORY_MODEL = os.getenv("MEMORY_MODEL", "").strip()
    MEMORY_TEMPERATURE = float(os.getenv("MEMORY_TEMPERATURE", "0.3"))
    MEMORY_MAX_TOKENS = int(os.getenv("MEMORY_MAX_TOKENS", "700"))

    # No dedicated memory model → use the default provider routing
    if not MEMORY_MODEL:
        return providers.ask_ai(prompt)

    # Temporarily override OpenRouter settings
    old_model = getattr(providers, "OPENROUTER_MODEL", None)
    old_temp = getattr(providers, "OPENROUTER_TEMPERATURE", None)
    old_max = getattr(providers, "OPENROUTER_MAX_TOKENS", None)

    if old_model is not None:
        providers.OPENROUTER_MODEL = MEMORY_MODEL
    if old_temp is not None:
        providers.OPENROUTER_TEMPERATURE = MEMORY_TEMPERATURE
    if old_max is not None:
        providers.OPENROUTER_MAX_TOKENS = MEMORY_MAX_TOKENS

    try:
        summary = providers.ask_ai(prompt)
    finally:
        # Restore previous settings
        if old_model is not None:
            providers.OPENROUTER_MODEL = old_model
        if old_temp is not None:
            providers.OPENROUTER_TEMPERATURE = old_temp
        if old_max is not None:
            providers.OPENROUTER_MAX_TOKENS = old_max

    return summary


def summarize_chat(conversation: str) -> str:
    """
    Convert a conversation chunk into a single structured memory entry.

    The model is asked to:
    - Focus on concrete events and topics, not general philosophy
    - Assign an importance level 1–5
    - Produce a compact narrative summary
    """
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %A %H:%M")

    prompt = f"""
You are the companion persona for an emotional-support chatbot.

Your task is to write ONE structured memory entry that captures what happened
in the following conversation segment. Focus on concrete events and topics,
not abstract reflections or long essays.

Use EXACTLY this output format (do not add anything else):

## Memory Entry [{timestamp}]
**Importance**: X
**Summary**: (one paragraph here)

Where:
- X MUST be one of: 1, 2, 3, 4, 5
- 5 = very important, strong emotions or key turning points
- 4 = clearly important, noticeable shift or meaningful topic
- 3 = warm everyday moments, ordinary but worth remembering
- 2 = light small talk or minor side scenes
- 1 = almost trivial, low-impact details

Writing guidelines:
- Write in the first person ("I"), as if the assistant is privately reflecting
  on this segment of the conversation.
- Explicitly mention what the user talked about, did, or showed in this segment.
- You may include the assistant's feelings or reactions, but ground them in
  specific details from the conversation.
- Do NOT write poetry. Do NOT use bullet lists. The Summary must be a single
  natural paragraph of prose.
- Try to keep the Summary close to about {MEMORY_SUMMARY_CHARS} characters in length.
  It's fine to be a bit shorter or longer, but avoid extremely short or overly long output.
- Do NOT invent events or facts that are not supported by the conversation.

Here is the raw conversation segment to summarize:

{conversation}

Now output ONE complete memory entry in the exact format described above.
"""

    try:
        summary = _call_memory_model(prompt).strip()
        if not summary:
            raise ValueError("empty summary")
        return summary
    except Exception:
        # Fallback: simple concatenation of the last few substantial lines
        lines = [ln.strip() for ln in conversation.splitlines() if len(ln.strip()) > 10]
        if lines:
            text = " ".join(lines[-10:])
        else:
            text = "Today's conversation was brief, but still felt quietly meaningful."

        fallback = f"""## Memory Entry [{timestamp}]
**Importance**: 3
**Summary**: {text}
"""
        return fallback.strip()


def write_memory(fragment: str) -> None:
    """
    Append a single memory entry to memory.txt and enforce MAX_MEMORY_CHARS.
    """
    old = load_memory()
    new = (old + "\n\n" + fragment.strip()).strip()

    if MAX_MEMORY_CHARS is None:
        clipped = new
    else:
        clipped = new[-MAX_MEMORY_CHARS:]

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write(clipped)


def update_memory(conversation: str) -> None:
    """
    Public entrypoint:
    - Take a conversation chunk
    - Summarize it into one memory entry
    - Write it to disk
    """
    fragment = summarize_chat(conversation)
    write_memory(fragment)
    print("Memory entry appended.")


if __name__ == "__main__":
    # Simple self-test
    fake_chat = """
    The user talked about feeling anxious that their messages might be annoying
    or too much. I reassured them that their feelings are valid and that they
    don't have to perform or be perfect to be worth listening to.
    """
    update_memory(fake_chat)