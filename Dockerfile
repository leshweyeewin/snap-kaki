# SnapKaki on Cloud Run.
#
# Single stage: there is nothing to compile, and the wheels are small enough
# that a builder stage would add a layer of complexity for no size win.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Requirements first so a code change does not re-resolve the dependency tree.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app/ ./app/
COPY web/ ./web/

# Cloud Run injects PORT and ignores EXPOSE; this is for local `docker run`.
ENV PORT=8080
EXPOSE 8080

# Single worker on purpose. Cloud Run scales by instance, and the in-memory
# session fallback in app/session.py is per-process — a second worker would
# make a Firestore outage look like randomly vanishing sessions.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
