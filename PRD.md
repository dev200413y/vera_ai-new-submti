# Vera Challenger Bot — PRD

**Author**: Dev Varshney | varshney.dev.013@gmail.com  
**Model**: mistral-large-latest (student free tier)  
**Stack**: FastAPI + Mistral AI

---

## What This Bot Does

Receives merchant/customer/trigger data from magicpin judge → composes personalized WhatsApp messages → handles replies.

---

## File Structure

```
config.py            ← All settings (API key, model, limits)
llm.py               ← Mistral API caller (pure stdlib, no SDK)
detection.py         ← Auto-reply / commitment / exit detection
anchor.py            ← Deterministic fact extractor (CORE LOGIC)
composer.py          ← compose() — 4 contexts → 1 message
conversation.py      ← Reply state machine (FSM)
bot.py               ← FastAPI — 5 HTTP endpoints only
generate_submission.py ← Creates submission.jsonl
judge_simulator.py   ← Provided by magicpin (do not edit)
requirements.txt     ← fastapi + uvicorn + pydantic
Dockerfile           ← GCP Cloud Run
dataset/             ← 5 categories, 50 merchants, 200 customers, 100 triggers
```

---

## Core Architecture: Anchor-First

**Problem with naive LLM approach:**
```
Dump 200 lines of JSON → "write a good message" → vague output
```

**Our approach:**
```
Step 1: anchor.py extracts 5-6 EXACT facts deterministically
        (real numbers, real names, real dates — no LLM involved)

Step 2: composer.py tells LLM:
        "USE THESE EXACT FACTS — just wrap in natural language"

Step 3: LLM polishes language only, does not decide facts
```

**Example — recall_due trigger:**
```
Anchor extracts:
  customer_name = "Priya"
  months_gap    = "6 months"
  slot_1        = "Wed 5 Nov, 6pm"
  slot_2        = "Thu 6 Nov, 5pm"
  price         = "Dental Cleaning @ ₹299"

LLM writes:
  "Hi Priya 🦷 Dr. Meera's clinic here.
   6 months ho gaye aapki last cleaning ko.
   Dental Cleaning @ ₹299 — slots:
   1️⃣ Wed 5 Nov 6pm  2️⃣ Thu 6 Nov 5pm
   Reply 1 ya 2 karo 🙏"
```

---

## Language Personalization

7 Indian languages detected from merchant/customer data:

| Merchant City | Language Used |
|---|---|
| Delhi, Lucknow | Hinglish |
| Bangalore | Kannada-English mix |
| Chennai | Tamil-English mix |
| Hyderabad | Telugu-English mix |
| Pune, Mumbai | Marathi-English mix |
| Ahmedabad | Gujarati-English mix |
| Chandigarh | Punjabi-English mix |

Customer language is detected separately — if customer prefers Tamil but merchant is Hindi-speaking, customer message goes in Tamil-English.

---

## Reply State Machine

```
merchant_message
      │
      ├─ is_exit?          → action: END
      ├─ is_auto_reply?    → 1st time: human appeal
      │                      2nd time: END
      ├─ is_commitment?    → action mode: confirm immediately
      ├─ 4+ vera turns?    → graceful goodbye
      └─ normal reply      → LLM continuation
```

---

## Scoring Optimization

| Judge Dimension | What We Do |
|---|---|
| Specificity | anchor.py extracts real numbers before LLM sees anything |
| Category fit | 5 voice profiles — dentist ≠ salon ≠ restaurant |
| Merchant fit | Active offers, CTR delta, customer aggregate injected |
| Trigger relevance | KEY FACT = trigger's most important data point |
| Engagement | One CTA, loss aversion / curiosity / social proof levers |

---

## Setup

```bash
pip install -r requirements.txt
export MISTRAL_API_KEY=your_key    # console.mistral.ai
uvicorn bot:app --host 0.0.0.0 --port 8080

# Test
python judge_simulator.py

# Generate submission
python generate_submission.py

# Deploy GCP
gcloud run deploy vera-bot --source . \
  --region asia-south1 --allow-unauthenticated \
  --port 8080 --set-env-vars MISTRAL_API_KEY=your_key
```
