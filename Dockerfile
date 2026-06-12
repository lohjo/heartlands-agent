# Heartland Commons — single shared Cloud Run image (ADR-6)
# One image serves all standard-tier tenants; isolation is logical, per-tenant,
# in Firestore. The dedicated tier (institutional partners) runs this SAME image
# with a different infrastructure flag — no code fork.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /srv

# Install dependencies first for layer caching.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install -e .

# CRITICAL: run from inside app/ so `soar_orchestrator` and `shared` import
# (see README). uvicorn binds the Cloud Run-provided $PORT.
WORKDIR /srv/app
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT}
