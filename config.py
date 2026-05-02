"""
config.py — All configuration in one place.
Change MISTRAL_API_KEY here or set it as environment variable.
"""

import os

# ── Mistral API ──────────────────────────────────────────
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MISTRAL_MODEL   = "mistral-large-latest"   # student free tier — better quality
MISTRAL_URL     = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_TIMEOUT = 12   # large model thoda slow hai — 12s safe hai
LLM_MAX_TOKENS  = 400  # max tokens for compose(); 200 for replies

# ── Bot identity ─────────────────────────────────────────
TEAM_NAME     = "DevVarshney"
TEAM_MEMBERS  = ["Dev Varshney"]
CONTACT_EMAIL = "varshney.dev.013@gmail.com"
BOT_VERSION   = "2.0.0"

# ── Limits ───────────────────────────────────────────────
MAX_BODY_CHARS       = 300   # hard cap on every outgoing message
MAX_ACTIONS_PER_TICK = 10    # stay well under the judge's 20-action limit
MAX_VERA_TURNS       = 4     # graceful exit after this many unanswered Vera turns
MAX_AUTO_REPLIES     = 2     # exit after this many detected auto-replies in one conv
