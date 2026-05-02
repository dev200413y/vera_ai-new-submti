"""
conversation.py — Multi-turn conversation state machine.

Tracks state for each active conversation and decides the next action
when a merchant/customer sends a reply.

State machine phases:
    pitch        → bot is still trying to get commitment
    action       → merchant committed, bot is executing / confirming
    winding_down → too many turns, gracefully exiting
    ended        → conversation closed (exit signal or auto-reply saturation)
"""

from typing import Optional
from detection import is_auto_reply, is_commitment, is_exit, first_name
from llm import call_mistral
# Reply prompt — inline (no separate prompts.py needed)
REPLY_SYSTEM = """You are Vera, magicpin's WhatsApp AI assistant mid-conversation.
Continue naturally. Rules:
- ≤ 200 chars
- No URLs
- Match merchant's language (Hinglish if they use Hindi)
- ONE clear next step or question
- If merchant committed → confirm action immediately, don't re-qualify
- Never repeat the previous Vera message verbatim
- If merchant asked a question → answer it specifically first
Return ONLY the message text. No JSON. No quotes. No markdown."""
from config import MAX_VERA_TURNS, MAX_AUTO_REPLIES, MAX_BODY_CHARS
import json, re


# ── Conversation state ────────────────────────────────────────────────────────

class ConversationState:
    """
    Holds the full state of one Vera ↔ Merchant conversation.
    Stored in the conversations{} dict in bot.py.
    """
    def __init__(self, merchant_id: str, customer_id: Optional[str] = None):
        self.merchant_id      = merchant_id
        self.customer_id      = customer_id
        self.turns:    list   = []    # [{"from": "vera"|"merchant", "msg": "..."}]
        self.sent_bodies: list = []   # dedup — every body Vera has sent this conv
        self.phase:    str    = "pitch"
        self.auto_reply_count: int = 0

    def add_turn(self, from_role: str, msg: str):
        self.turns.append({"from": from_role, "msg": msg})

    def add_vera_message(self, body: str):
        """Track a message Vera sent — used for dedup and wind-down counting."""
        self.turns.append({"from": "vera", "msg": body})
        if body not in self.sent_bodies:
            self.sent_bodies.append(body)

    @property
    def vera_turn_count(self) -> int:
        return sum(1 for t in self.turns if t["from"] == "vera")

    def to_dict(self) -> dict:
        return {
            "merchant_id":      self.merchant_id,
            "customer_id":      self.customer_id,
            "turns":            self.turns,
            "sent_bodies":      self.sent_bodies,
            "phase":            self.phase,
            "auto_reply_count": self.auto_reply_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConversationState":
        s = cls(d["merchant_id"], d.get("customer_id"))
        s.turns             = d.get("turns", [])
        s.sent_bodies       = d.get("sent_bodies", [])
        s.phase             = d.get("phase", "pitch")
        s.auto_reply_count  = d.get("auto_reply_count", 0)
        return s


# ── Reply handler ─────────────────────────────────────────────────────────────

def handle_reply(
    state:        ConversationState,
    message:      str,
    merchant:     Optional[dict],
    category:     Optional[dict] = None,
) -> dict:
    """
    Given a merchant reply + current conversation state, decide the next action.

    Returns a dict with:
        action  — "send" | "wait" | "end"
        body    — (only if action == "send")
        cta     — (only if action == "send")
        rationale
    """
    # Record the incoming message
    state.add_turn("merchant", message)

    # ── 1. EXIT SIGNAL ────────────────────────────────────────────────────────
    if is_exit(message):
        state.phase = "ended"
        return {
            "action":    "end",
            "rationale": "Merchant signaled disinterest. Exiting respectfully.",
        }

    # ── 2. AUTO-REPLY DETECTION ───────────────────────────────────────────────
    if is_auto_reply(message):
        state.auto_reply_count += 1

        if state.auto_reply_count >= MAX_AUTO_REPLIES:
            # Seen too many auto-replies — stop wasting turns
            state.phase = "ended"
            return {
                "action":    "end",
                "rationale": f"Auto-reply detected {state.auto_reply_count}× in this conversation. "
                             "Exiting to avoid burning turns on a bot.",
            }

        # First auto-reply → try one direct human appeal
        fname = _owner_first_name(merchant)
        body  = (
            f"{fname}, kya aap personally 2 min le sakte hain? "
            f"Aapke account ke baare mein kuch specific share karna tha. 🙏"
        )
        body = body[:MAX_BODY_CHARS]
        state.add_vera_message(body)
        return {
            "action":    "send",
            "body":      body,
            "cta":       "open_ended",
            "rationale": "Auto-reply detected (first time). "
                         "One human-direct appeal before potential exit.",
        }

    # ── 3. COMMITMENT → ACTION MODE ───────────────────────────────────────────
    if is_commitment(message) and state.phase == "pitch":
        state.phase = "action"

        # Build an action confirmation — what are we doing right now?
        body = _build_action_confirmation(merchant)
        state.add_vera_message(body)
        return {
            "action":    "send",
            "body":      body,
            "cta":       "open_ended",
            "rationale": "Merchant committed. Switched to action mode immediately — "
                         "no re-qualification question.",
        }

    # ── 4. GRACEFUL WIND-DOWN ─────────────────────────────────────────────────
    if state.vera_turn_count >= MAX_VERA_TURNS and state.phase == "pitch":
        state.phase = "ended"
        fname = _owner_first_name(merchant)
        cat   = category.get("slug", "").rstrip("s") if category else ""
        body  = (
            f"Koi baat nahi {fname}! "
            f"Jab bhi zaroorat ho bataiye. "
            f"{'Aapka ' + cat + ' accha chal raha hai — ' if cat else ''}"
            f"Best of luck! 🙂"
        )
        if len(body) > MAX_BODY_CHARS:
            body = "Koi baat nahi! Jab zaroorat ho bataiye. Best of luck! 🙂"
        return {
            "action":    "send",
            "body":      body,
            "cta":       "none",
            "rationale": f"{MAX_VERA_TURNS}+ Vera turns with no commitment. Gracefully winding down.",
        }

    # ── 5. NORMAL CONTINUATION — ask LLM ─────────────────────────────────────
    body = _llm_continuation(state, message, merchant, category)

    if not body or body.startswith("[ERROR"):
        # LLM unavailable — back off briefly rather than sending garbage
        return {
            "action":       "wait",
            "wait_seconds": 300,
            "rationale":    "LLM temporarily unavailable. Brief backoff before retry.",
        }

    body = re.sub(r"https?://\S+|www\.\S+", "", body).strip()[:MAX_BODY_CHARS]
    state.add_vera_message(body)
    return {
        "action":    "send",
        "body":      body,
        "cta":       "open_ended",
        "rationale": "Natural conversation continuation based on merchant's reply.",
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _owner_first_name(merchant: Optional[dict]) -> str:
    """Get salutation-ready first name from merchant dict."""
    if not merchant:
        return "Ji"
    full = (
        merchant.get("identity", {}).get("owner_first_name", "")
        or merchant.get("identity", {}).get("name", "")
    )
    return first_name(full)


def _build_action_confirmation(merchant: Optional[dict]) -> str:
    """
    Build a quick action confirmation after merchant commits.
    Tries to mention the active offer for specificity.
    """
    lang = (merchant or {}).get("identity", {}).get("languages", ["en"])
    active_offers = [
        o.get("title", "") for o in (merchant or {}).get("offers", [])
        if o.get("status") == "active"
    ]
    offer_str = f" ({active_offers[0]})" if active_offers else ""

    if "hi" in lang:
        return f"Done{offer_str}! Abhi set kar rahi hoon — 2 minute mein confirm aayega. ✅"
    else:
        return f"Done{offer_str}! Setting it up right now — confirmation in 2 minutes. ✅"


def _llm_continuation(
    state:    ConversationState,
    message:  str,
    merchant: Optional[dict],
    category: Optional[dict],
) -> str:
    """Use the LLM to compose a natural continuation reply."""
    lang      = (merchant or {}).get("identity", {}).get("languages", ["en"])
    lang_hint = "Hinglish" if "hi" in lang else "English"
    mname     = (merchant or {}).get("identity", {}).get("name", "")
    cat_slug  = (category or {}).get("slug", "")

    # Give LLM the last 4 turns + merchant's latest message
    recent_turns = state.turns[-4:]

    user_prompt = f"""Merchant: {mname} | Category: {cat_slug} | Language: {lang_hint}
Recent conversation turns:
{json.dumps(recent_turns, ensure_ascii=False)}

Merchant just said: "{message}"
Previous Vera messages already sent (DO NOT repeat): {json.dumps(state.sent_bodies[-2:], ensure_ascii=False)}

Write the next Vera message (≤200 chars, no URLs, {lang_hint})."""

    return call_mistral(REPLY_SYSTEM, user_prompt, max_tokens=200)
