# Vera Challenger Bot
**Dev Varshney** | varshney.dev.013@gmail.com

## Quick Start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Set API key (get free key at console.mistral.ai)
export MISTRAL_API_KEY=your_key      # Mac/Linux
set MISTRAL_API_KEY=your_key         # Windows

# 3. Start bot
uvicorn bot:app --host 0.0.0.0 --port 8080

# 4. Test (new terminal)
python judge_simulator.py

# 5. Generate submission.jsonl
python generate_submission.py

# 6. Deploy to GCP
gcloud run deploy vera-bot --source . \
  --region asia-south1 --allow-unauthenticated \
  --port 8080 --set-env-vars MISTRAL_API_KEY=your_key
```

## Endpoints
| Endpoint | Purpose |
|---|---|
| POST /v1/context | Receive category/merchant/customer/trigger data |
| POST /v1/tick | Compose proactive messages |
| POST /v1/reply | Handle merchant replies |
| GET /v1/healthz | Liveness check |
| GET /v1/metadata | Bot identity |
