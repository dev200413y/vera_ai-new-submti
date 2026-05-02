"""
bot.py — FastAPI server exposing all 5 required endpoints.

This file is intentionally thin — it only handles HTTP.
All business logic lives in separate modules:
    composer.py     — compose() function (4-context → message)
    conversation.py — ConversationState + handle_reply()
    detection.py    — is_auto_reply(), is_commitment(), is_exit()
    prompts.py      — all LLM system prompts + kind guidance
    llm.py          — Mistral API client
    config.py       — configuration constants

Run:
    uvicorn bot:app --host 0.0.0.0 --port 8080

GCP Cloud Run:
    gcloud run deploy vera-bot --source . --port 8080 \\
        --set-env-vars MISTRAL_API_KEY=your_key --allow-unauthenticated
"""

import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel

# Import our modules
from config import TEAM_NAME, TEAM_MEMBERS, CONTACT_EMAIL, BOT_VERSION, MAX_ACTIONS_PER_TICK
from composer import compose                                # 4-context composer
from conversation import ConversationState, handle_reply   # reply state machine


# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Vera Challenger Bot", version=BOT_VERSION)
START_TIME = time.time()


# ── In-memory stores ──────────────────────────────────────────────────────────
# These reset on restart — that's fine for a 60-minute test window.

contexts:      dict[tuple, dict] = {}   # (scope, context_id) → {version, payload}
conversations: dict[str, dict]   = {}   # conv_id → ConversationState.to_dict()
suppressions:  set[str]          = set()  # suppression keys already sent


# ── Context helpers ───────────────────────────────────────────────────────────

def _ctx(scope: str, cid: str) -> Optional[dict]:
    """Retrieve a stored context payload by scope + id."""
    entry = contexts.get((scope, cid))
    return entry["payload"] if entry else None

def _get_merchant(mid: str) -> Optional[dict]:
    return _ctx("merchant", mid)

def _get_category(slug: str) -> Optional[dict]:
    return _ctx("category", slug) if slug else None

def _get_customer(cid: str) -> Optional[dict]:
    return _ctx("customer", cid) if cid else None

def _get_conv(conv_id: str) -> ConversationState:
    """Get or create a ConversationState for a conversation_id."""
    if conv_id not in conversations:
        conversations[conv_id] = ConversationState("", None).to_dict()
    return ConversationState.from_dict(conversations[conv_id])

def _save_conv(conv_id: str, state: ConversationState):
    conversations[conv_id] = state.to_dict()


# ══════════════════════════════════════════════════════════════
# ENDPOINT 1 — POST /v1/context
# Receive context pushes from the judge (category / merchant / customer / trigger).
# ══════════════════════════════════════════════════════════════

class ContextPayload(BaseModel):
    scope:        str            # "category" | "merchant" | "customer" | "trigger"
    context_id:   str            # e.g. "dentists", "m_001_drmeera", "c_001_priya", "trg_001"
    version:      int            # monotonically increasing
    payload:      dict[str, Any] # the full context object
    delivered_at: str            # ISO timestamp


@app.post("/v1/context")
async def push_context(body: ContextPayload):
    """
    Store or update a context. Idempotent by (scope, context_id, version).
    A higher version replaces the old one atomically.
    """
    VALID_SCOPES = {"category", "merchant", "customer", "trigger"}

    if body.scope not in VALID_SCOPES:
        return {
            "accepted": False,
            "reason":   "invalid_scope",
            "details":  f"scope must be one of {VALID_SCOPES}",
        }

    key     = (body.scope, body.context_id)
    current = contexts.get(key)

    # Reject stale versions
    if current and current["version"] >= body.version:
        return {
            "accepted":        False,
            "reason":          "stale_version",
            "current_version": current["version"],
        }

    # Store
    contexts[key] = {"version": body.version, "payload": body.payload}

    return {
        "accepted":  True,
        "ack_id":    f"ack_{body.context_id}_v{body.version}",
        "stored_at": datetime.now(timezone.utc).isoformat(),
    }


# ══════════════════════════════════════════════════════════════
# ENDPOINT 2 — POST /v1/tick
# Judge wakes the bot every N simulated minutes.
# Bot inspects its context state and decides what to send.
# ══════════════════════════════════════════════════════════════

class TickPayload(BaseModel):
    now:                str        # simulated current time (ISO)
    available_triggers: list[str]  # trigger context_ids active right now


@app.post("/v1/tick")
async def tick(body: TickPayload):
    """
    Decide which proactive messages to send this tick.

    Strategy:
      1. Sort triggers by urgency (highest first)
      2. Skip: expired, already suppressed, no merchant/category loaded
      3. One message per merchant per tick (no spam)
      4. Compose with 4-context framework
      5. Track conversation + suppression
    """
    actions:         list[dict] = []
    seen_merchants:  set[str]   = set()  # one message per merchant this tick

    # ── Sort triggers by urgency ──
    trg_queue: list[tuple] = []
    for tid in body.available_triggers:
        trg = _ctx("trigger", tid)
        if not trg:
            continue

        # Skip if suppression key already used
        sup_key = trg.get("suppression_key", "")
        if sup_key and sup_key in suppressions:
            continue

        # Skip if expired
        expires = trg.get("expires_at", "")
        if expires:
            try:
                exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                if exp_dt < datetime.now(timezone.utc):
                    continue
            except Exception:
                pass

        trg_queue.append((trg.get("urgency", 1), tid, trg))

    trg_queue.sort(key=lambda x: -x[0])  # highest urgency first

    # ── Process each trigger ──
    for _, tid, trg in trg_queue:
        if len(actions) >= MAX_ACTIONS_PER_TICK:
            break

        merchant_id = trg.get("merchant_id") or trg.get("payload", {}).get("merchant_id")
        customer_id = trg.get("customer_id")

        # Skip if no merchant or already messaged this merchant this tick
        if not merchant_id or merchant_id in seen_merchants:
            continue

        # Load contexts
        merchant = _get_merchant(merchant_id)
        if not merchant:
            continue

        category = _get_category(merchant.get("category_slug", ""))
        if not category:
            continue

        customer = _get_customer(customer_id) if customer_id else None

        # ── Compose the message ──
        try:
            result = compose(category, merchant, trg, customer)
        except Exception:
            continue

        msg_body = result.get("body", "").strip()
        if not msg_body or msg_body.startswith("[ERROR"):
            continue

        # ── Register conversation ──
        conv_id = f"conv_{merchant_id}_{tid}_{int(time.time())}"
        state   = ConversationState(merchant_id, customer_id)
        state.add_vera_message(msg_body)
        _save_conv(conv_id, state)

        # ── Register suppression ──
        sup_key = result.get("suppression_key", "")
        if sup_key:
            suppressions.add(sup_key)
        seen_merchants.add(merchant_id)

        # ── Add to actions list ──
        mname = merchant.get("identity", {}).get("name", merchant_id)
        actions.append({
            "conversation_id": conv_id,
            "merchant_id":     merchant_id,
            "customer_id":     customer_id,
            "send_as":         result.get("send_as", "vera"),
            "trigger_id":      tid,
            "template_name":   f"vera_{trg.get('kind', 'generic')}_v1",
            "template_params": [mname, trg.get("kind", ""), msg_body[:50]],
            "body":            msg_body,
            "cta":             result.get("cta", "open_ended"),
            "suppression_key": sup_key,
            "rationale":       result.get("rationale", ""),
        })

    return {"actions": actions}


# ══════════════════════════════════════════════════════════════
# ENDPOINT 3 — POST /v1/reply
# Judge sends a merchant/customer reply. Bot must respond.
# ══════════════════════════════════════════════════════════════

class ReplyPayload(BaseModel):
    conversation_id: str
    merchant_id:     Optional[str] = None
    customer_id:     Optional[str] = None
    from_role:       str   # "merchant" | "customer"
    message:         str
    received_at:     str
    turn_number:     int


@app.post("/v1/reply")
async def reply(body: ReplyPayload):
    """
    Receive a reply and decide what to do next.

    The reply FSM (in conversation.py) handles:
      - Exit signals → end
      - Auto-reply detection → human appeal, then end
      - Commitment signals → switch to action mode
      - 4+ Vera turns → graceful wind-down
      - Normal replies → LLM continuation
    """
    conv_id = body.conversation_id

    # Get or create conversation state
    state = _get_conv(conv_id)

    # Fill in merchant_id if this is a new conversation
    if not state.merchant_id:
        state.merchant_id = body.merchant_id or ""
    if not state.customer_id:
        state.customer_id = body.customer_id

    # Load merchant + category for the reply handler
    mid      = body.merchant_id or state.merchant_id
    merchant = _get_merchant(mid) if mid else None
    category = _get_category(merchant.get("category_slug", "")) if merchant else None

    # Run the FSM
    result = handle_reply(state, body.message, merchant, category)

    # Persist updated state
    _save_conv(conv_id, state)

    return result


# ══════════════════════════════════════════════════════════════
# ENDPOINT 4 — GET /v1/healthz
# Liveness probe — judge polls every 60s.
# ══════════════════════════════════════════════════════════════

@app.get("/v1/healthz")
async def healthz():
    """Return bot status and how many contexts are loaded."""
    counts: dict[str, int] = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _) in contexts:
        if scope in counts:
            counts[scope] += 1

    return {
        "status":          "ok",
        "uptime_seconds":  int(time.time() - START_TIME),
        "contexts_loaded": counts,
    }


# ══════════════════════════════════════════════════════════════
# ENDPOINT 5 — GET /v1/metadata
# Bot identity — read once by judge at warmup.
# ══════════════════════════════════════════════════════════════

@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name":    TEAM_NAME,
        "team_members": TEAM_MEMBERS,
        "model":        "mistral/mistral-small-latest (free tier)",
        "approach": (
            "4-context LLM composer (Mistral) with 27 trigger-kind-specific prompt templates. "
            "Category voice matching per vertical. "
            "Auto-reply detection (9 patterns + repeat tracking). "
            "Commitment routing → instant action mode. "
            "Graceful exit on hostility / 4+ turns without commitment."
        ),
        "contact_email": CONTACT_EMAIL,
        "version":       BOT_VERSION,
        "submitted_at":  "2026-04-29T00:00:00Z",
    }


# ══════════════════════════════════════════════════════════════
# OPTIONAL — POST /v1/teardown
# Judge calls this at end of test to signal cleanup.
# ══════════════════════════════════════════════════════════════

@app.post("/v1/teardown")
async def teardown():
    """Wipe all in-memory state."""
    contexts.clear()
    conversations.clear()
    suppressions.clear()
    return {"status": "wiped"}
