"""
detection.py — Signal detection for merchant/customer replies.

Three functions:
    is_auto_reply(text)  → True if WhatsApp Business canned auto-reply
    is_commitment(text)  → True if merchant said yes / agreed to proceed
    is_exit(text)        → True if merchant wants to stop

All functions are pure (no I/O, no state) — easy to unit-test.
"""

import re


# ── Auto-reply patterns ───────────────────────────────────────────────────────
# These cover the most common WhatsApp Business auto-reply formats in English + Hindi.
# Two detection layers in bot.py:
#   1. Pattern match (this list)
#   2. Verbatim repeat — same message appears 2+ times in conversation (handled in state.py)

_AUTO_PATTERNS = [
    r"thank.?you for (contacting|reaching|messaging)",
    r"automated (message|assistant|response|reply)",
    r"our team will (get back|reach out|contact|revert)",
    r"currently (unavailable|away|offline|closed|out of office)",
    r"jaankari ke liye.*shukriya",          # common Hindi auto-reply phrase
    r"madad ke liye shukriya.*automated",
    r"main ek automated",                   # "I am an automated assistant"
    r"yeh ek automated",
    r"will be (addressed|handled|responded to) shortly",
    r"away from (office|desk|my phone)",
    r"business hours.*respond",
    r"received your message.*get back",
]

# ── Commitment patterns ───────────────────────────────────────────────────────
# Merchant has said yes / agreed to proceed → switch from pitch mode to action mode.

_COMMIT_PATTERNS = [
    r"\byes\b",
    r"\bha(an|n)?\b",                       # haan / han / ha
    r"\bhaan\b",
    r"let'?s (do it|go|proceed|start)",
    r"\bgo ahead\b",
    r"\bproceed\b",
    r"\bconfirm\b",
    r"\bkaro\b",
    r"\bchaliye\b",
    r"\bchalo\b",
    r"\btheek hai\b",
    r"sign me up",
    r"please do",
    r"\bdo it\b",
    r"send (it|me|kar|karo|kar do)",
    r"share (kar|karo|kijiye|it)",
    r"mujhe chahiye",
    r"main ready",
    r"\bbilkul\b",
    r"\bagree\b",
    r"sounds good",
    r"\bokay\b",
    r"\bok\b",
    r"ji (haan|ha|bilkul|zaroor)",
]

# ── Exit / not-interested patterns ────────────────────────────────────────────

_EXIT_PATTERNS = [
    r"\bstop\b",
    r"not interested",
    r"no thanks",
    r"nahi chahiye",
    r"mat bhejo",
    r"\bspam\b",
    r"remove me",
    r"unsubscribe",
    r"don.?t (message|contact|call|send|disturb)",
    r"\buseless\b",
    r"\bbekaar\b",
    r"band karo",
    r"mujhe nahi",
    r"please stop",
    r"bekar",
]


def is_auto_reply(text: str) -> bool:
    """Return True if the text looks like a WhatsApp Business canned auto-reply."""
    t = text.lower().strip()
    return any(re.search(p, t) for p in _AUTO_PATTERNS)


def is_commitment(text: str) -> bool:
    """Return True if the merchant has agreed / committed to proceed."""
    t = text.lower().strip()
    return any(re.search(p, t) for p in _COMMIT_PATTERNS)


def is_exit(text: str) -> bool:
    """Return True if the merchant wants to stop the conversation."""
    t = text.lower().strip()
    return any(re.search(p, t) for p in _EXIT_PATTERNS)


def first_name(full_name: str) -> str:
    """
    Extract first usable name token from a full name string.
    Skips honorifics like Dr., Mr., Mrs., M/s.
    Returns 'Ji' as a safe fallback.
    """
    if not full_name:
        return "Ji"
    skip = {"Dr.", "Dr", "M/s", "Mr.", "Mrs.", "Ms.", "Prof.", "Prof"}
    for part in full_name.split():
        if part not in skip and part:
            return part
    return "Ji"
