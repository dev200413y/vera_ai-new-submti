"""
composer.py — Anchor-first message composition.

THE DIFFERENCE FROM THE OLD APPROACH:

  OLD (LLM wrapper):
    Dump all JSON to LLM → "please write a good message" → hope for the best
    Result: vague messages, LLM ignores specific numbers

  NEW (Anchor-first):
    Step 1 — Extract exact facts deterministically (anchor.py)
    Step 2 — Tell LLM: "wrap THESE facts in natural language"
    Result: specific, verifiable messages with real numbers

The LLM is now a language polisher, not a data miner.
"""

import json
import re
from typing import Optional

from llm import call_mistral
from anchor import build_anchor
from config import MAX_BODY_CHARS, LLM_MAX_TOKENS


SYSTEM = """You are Vera, magicpin's WhatsApp assistant for Indian merchants.
Your job: write ONE WhatsApp message using the ANCHOR FACTS provided.

RULES:
1. USE the anchor facts — numbers, names, dates MUST appear verbatim
2. <= 300 chars — count every character
3. NO URLs
4. Last sentence = ONE CTA only
5. Match language: Hinglish = natural Hindi-English mix; English = English only
6. Category voice: dentists=peer_clinical, salons=warm_practical, restaurants=casual, gyms=motivational, pharmacies=clinical
7. NO fabrication — only use what's in the anchor
8. Start with the KEY FACT — not a greeting
9. For customer messages: start with customer name
10. No "Hi I'm Vera" preamble
11. 0.30 → 30% (decimal to percent)
12. Sirf real numbers use karo
13. Sirf active offers use karo
Return ONLY JSON:
{"body": "...", "cta": "open_ended"|"binary_yes_stop"|"none", "send_as": "vera"|"merchant_on_behalf"}"""


def compose(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None,
) -> dict:
    """
    Compose a WhatsApp message from 4 context dicts.
    Returns: {body, cta, send_as, suppression_key, rationale}
    """
    # Step 1 — Deterministic fact extraction
    anchor = build_anchor(category, merchant, trigger, customer)

    # Step 2 — Tight prompt with anchor facts
    prompt = _build_prompt(anchor, trigger, category, merchant, customer)

    # Step 3 — LLM call
    raw = call_mistral(SYSTEM, prompt, max_tokens=LLM_MAX_TOKENS)

    # Step 4 — Parse + enforce constraints
    return _parse(raw, anchor, trigger, customer)


def _build_prompt(anchor, trigger, category, merchant, customer):
    kind    = trigger.get("kind", "default")
    is_cust = customer is not None

    lines = [
        f"OWNER SALUTATION: {anchor['owner_salutation']}",
        f"KEY FACT (USE THIS VERBATIM): {anchor['key_fact']}",
        f"WHY NOW: {anchor['why_now']}",
        f"SUGGESTED CTA: {anchor['suggested_cta']}",
        f"WRITE IN: {anchor['language']}",
        f"LANGUAGE RULE: Message MUST be written in {anchor['language']}. "
        f"Do NOT default to English if a regional language is specified. "
        f"Natural mix is preferred — not forced or awkward.",
    ]

    if anchor.get("top_offer"):
        lines.append(f"ACTIVE OFFER: {anchor['top_offer']}")
    if anchor.get("cohort_note"):
        lines.append(f"PATIENT COHORT NOTE: {anchor['cohort_note']}")

    if is_cust:
        if anchor.get("customer_name"):
            lines.append(f"CUSTOMER NAME: {anchor['customer_name']}")
        if anchor.get("slot_1"):
            lines.append(f"SLOT 1: {anchor['slot_1']}")
        if anchor.get("slot_2"):
            lines.append(f"SLOT 2: {anchor['slot_2']}")
        if anchor.get("price"):
            lines.append(f"SERVICE + PRICE: {anchor['price']}")
        if anchor.get("months_gap"):
            lines.append(f"MONTHS SINCE LAST VISIT: {anchor['months_gap']}")

    # Explicit competitor facts
    if kind == "competitor_opened":
        p = trigger.get("payload", {})
        if p.get("competitor_name"):
            lines.append(f"COMPETITOR NAME: {p['competitor_name']}")
        if p.get("distance_km"):
            lines.append(f"DISTANCE: {p['distance_km']}km away")
        if p.get("their_offer"):
            lines.append(f"THEIR OFFER: {p['their_offer']}")

    # Explicit performance delta
    if kind in ("perf_spike", "perf_dip"):
        perf  = merchant.get("performance", {})
        delta = perf.get("delta_7d", {})
        if delta:
            vd = int(delta.get("views_pct", 0) * 100)
            cd = int(delta.get("calls_pct", 0) * 100)
            lines.append(f"EXACT DELTA: views {'+' if vd>=0 else ''}{vd}%, calls {'+' if cd>=0 else ''}{cd}%")
            lines.append(f"CURRENT METRICS: views={perf.get('views','?')}, calls={perf.get('calls','?')}")

    cat_voice = {
        "dentists":    "peer-clinical, use 'Dr.' prefix, technical vocab OK",
        "salons":      "warm-practical, use beauty vocab",
        "restaurants": "casual-enthusiastic, owner-to-owner",
        "gyms":        "motivational, coaching tone",
        "pharmacies":  "clinical-factual, no brand names",
    }
    voice = cat_voice.get(anchor["cat_slug"], "professional, natural")

    scope = (
        "MESSAGE TYPE: Customer-facing (send_as=merchant_on_behalf). Start with customer name."
        if is_cust else
        "MESSAGE TYPE: Merchant-facing (send_as=vera). Address the owner."
    )

    anchor_block = "\n".join(lines)

    return f"""TRIGGER KIND: {kind}
{scope}
CATEGORY VOICE: {voice}

=== ANCHOR FACTS — USE ALL OF THESE ===
{anchor_block}
========================================

Write the message now. Start with KEY FACT. End with CTA. <=300 chars."""


def _parse(raw, anchor, trigger, customer):
    try:
        clean = re.sub(r"```(?:json)?|```", "", raw).strip()
        m = re.search(r"\{.*\}", clean, re.DOTALL)
        result = json.loads(m.group(0) if m else clean)
    except Exception:
        result = _fallback_from_anchor(anchor, customer)

    body = result.get("body", "")
    body = re.sub(r"https?://\S+|www\.\S+", "", body).strip()
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS - 3] + "..."

    is_cust = customer is not None
    result["body"]            = body
    result["suppression_key"] = trigger.get("suppression_key", f"trg:{trigger.get('id','')}")
    result.setdefault("cta",     "open_ended")
    result.setdefault("send_as", "merchant_on_behalf" if is_cust else "vera")
    result["rationale"] = f"anchor={anchor.get('key_fact','')[:60]} | kind={trigger.get('kind','')}"
    return result


def _fallback_from_anchor(anchor, customer):
    is_cust  = customer is not None
    name     = anchor.get("customer_name", "") if is_cust else anchor.get("owner_salutation", "")
    key_fact = anchor.get("key_fact", "Update on your account")
    cta      = anchor.get("suggested_cta", "Want to know more?")
    body     = f"{name} — {key_fact}. {cta}" if name else f"{key_fact}. {cta}"
    if len(body) > 300:
        body = body[:297] + "..."
    return {"body": body, "cta": "open_ended", "send_as": "merchant_on_behalf" if is_cust else "vera"}
