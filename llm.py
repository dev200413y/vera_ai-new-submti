"""
llm.py — Mistral API client.

One function: call_mistral(system, user) → str
Uses only Python stdlib (urllib) — no pip install needed for this file.
"""

import json
import urllib.request
import urllib.error

from config import MISTRAL_API_KEY, MISTRAL_MODEL, MISTRAL_URL, MISTRAL_TIMEOUT


def call_mistral(system: str, user: str, max_tokens: int = 400) -> str:
    """
    Call Mistral chat completion API.

    Args:
        system:     System prompt (role instructions).
        user:       User prompt (the actual task / context).
        max_tokens: How many tokens to generate (default 400).

    Returns:
        Model response as a plain string.
        Returns an error string starting with "[ERROR" if the call fails.
    """
    if not MISTRAL_API_KEY:
        return "[ERROR: MISTRAL_API_KEY not set — export MISTRAL_API_KEY=your_key]"

    # Build request payload
    payload = json.dumps({
        "model":       MISTRAL_MODEL,
        "temperature": 0.1,       # near-deterministic for consistent scoring
        "max_tokens":  max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    }).encode("utf-8")

    req = urllib.request.Request(
        url=MISTRAL_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=MISTRAL_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return f"[ERROR: HTTP {e.code} from Mistral — {body[:300]}]"

    except urllib.error.URLError as e:
        return f"[ERROR: Network error — {e.reason}]"

    except Exception as e:
        return f"[ERROR: {type(e).__name__}: {e}]"
