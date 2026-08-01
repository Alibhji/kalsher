FROM node:22-alpine AS web

WORKDIR /app/ui/web

COPY ui/web/package.json ./
RUN npm install

COPY ui/web/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 appuser

COPY ui/requirements.txt /app/ui/requirements.txt
RUN pip install --no-cache-dir -r /app/ui/requirements.txt

COPY common /app/common
COPY storage /app/storage
COPY ui /app/ui
COPY --from=web /app/ui/web/dist /app/ui/web/dist

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8090

CMD ["python", "-m", "ui.server.main"]
