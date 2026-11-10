# syntax=docker/dockerfile:1
# Sessions service. Build context: services/sessions.
FROM python:3.12-slim-bookworm

ARG APP_VERSION=dev
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    APP_VERSION=${APP_VERSION}

WORKDIR /app

# Unprivileged user; the image never runs as root.
RUN useradd --create-home --uid 10001 appuser

# Dependencies first, so editing source does not reinstall packages.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Explicit list of what the service needs to run. No COPY . ., no .env, no tests.
COPY app.py db.py domain_logic.py seed.json ./
COPY migrations/ ./migrations/

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ['PORT']+'/health', timeout=4).status==200 else 1)" || exit 1

# One worker, so a single process runs migrations at boot. The long timeout
# covers a cold start: the database may take about a minute to resume.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 120 --access-logfile - app:app"]
