# Orchard FastAPI backend. Talks to the "postgres" and "chromadb" services
# over the compose network; no embedded storage.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code (see .dockerignore for what's excluded).
COPY app ./app
COPY docker ./docker

# Uploaded source files live on a named volume mounted here.
RUN mkdir -p /app/uploads
ENV ORCHARD_UPLOADS_DIR=/app/uploads

EXPOSE 8000

# The compose healthcheck hits GET /health; schema comes from the postgres
# container's init.sql, so there's nothing to bootstrap here.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
