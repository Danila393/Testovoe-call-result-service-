FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
COPY producer.py ./

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000

# Readiness: MongoDB reachable and the consumer attached to the queue (see GET /health).
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

CMD ["uvicorn", "app.main:build_default_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
