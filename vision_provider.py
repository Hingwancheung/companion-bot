"""
Vision provider wrapper.

- Sends image bytes to an OpenAI-compatible vision endpoint
- Returns a plain-text description of the image
- Uses environment variables for all configuration
"""

import os
import base64
import requests

# Keep debug behaviour aligned with providers.py
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() in ("1", "true", "yes", "on")


def _dbg(*args):
    """
    Debug print for this module. No output when DEBUG_MODE is false.
    """
    if DEBUG_MODE:
        print("[DBG][VISION]", *args)


# --- Configuration (from environment) ---

# CUSTOMIZE: set this to your own OpenAI-compatible vision endpoint
VISION_API_BASE = os.getenv("VISION_API_BASE", "https://vg.v1api.cc")
VISION_API_KEY = os.getenv("VISION_API_KEY", "")
VISION_MODEL = os.getenv("VISION_MODEL", "gpt-4o-mini")
VISION_TIMEOUT = int(os.getenv("VISION_TIMEOUT", "60"))


def describe_image(image_bytes: bytes, extra_prompt: str = "") -> str:
    """
    Call an OpenAI-compatible vision endpoint to describe an image.

    Args:
        image_bytes: Raw image bytes.
        extra_prompt: Optional additional instruction for the model.

    Returns:
        A text description from the model, or a string starting with
        a diagnostic prefix (e.g. "[vision-http-...]" or "[vision-exception]") on error.
    """
    _dbg("VISION_DESCRIBE_CALLED")
    _dbg("VISION_KEY_PRESENT:", bool(VISION_API_KEY))

    if not VISION_API_KEY:
        return "Vision API key is missing."

    # 1) Encode image as base64
    b64 = base64.b64encode(image_bytes).decode("ascii")

    # 2) Build request payload
    url = f"{VISION_API_BASE}/chat/completions"
    user_text = extra_prompt or "Please describe this image in detail."

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}"
                        },
                    },
                ],
            }
        ],
        "max_tokens": 400,
    }

    headers = {
        "Authorization": f"Bearer {VISION_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=VISION_TIMEOUT,
        )
        _dbg("VISION_HTTP_STATUS", resp.status_code)

        if resp.status_code != 200:
            _dbg("VISION_HTTP_ERROR_BODY", resp.text[:300])
            return f"[vision-http-{resp.status_code}] {resp.text[:200]}"

        data = resp.json()
        _dbg("VISION_RESP_KEYS", list(data.keys()))

        # OpenAI-style: choices[0].message.content
        try:
            content = data["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001
            _dbg("VISION_PARSE_ERROR", repr(e), data)
            return "[vision-parse-error] Unable to read model response."

        # Some providers return a plain string
        if isinstance(content, str):
            return content.strip()

        # Some providers return a list of parts
        if isinstance(content, list):
            texts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    texts.append(part.get("text", ""))
            joined = "\n".join(t for t in texts if t)
            if joined.strip():
                return joined.strip()

        return "[vision-empty] Model returned no text."

    except Exception as e:  # noqa: BLE001
        _dbg("VISION_EXCEPTION", repr(e))
        return f"[vision-exception] {e!r}"