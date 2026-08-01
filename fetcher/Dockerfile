FROM python:3.12-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 appuser

COPY fetcher/requirements.txt /app/fetcher/requirements.txt
RUN pip install --no-cache-dir -r /app/fetcher/requirements.txt

COPY common /app/common
COPY storage /app/storage
COPY fetcher /app/fetcher

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

USER appuser

WORKDIR /app/fetcher

CMD ["python", "-m", "app.main"]
