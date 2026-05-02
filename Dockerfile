FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all source files
COPY config.py llm.py detection.py anchor.py composer.py conversation.py bot.py ./

# Cloud Run sets PORT=8080 automatically
ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "bot:app", "--host", "0.0.0.0", "--port", "8080"]
