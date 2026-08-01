FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY storage/migrate.sh /migrate.sh
COPY storage/migrations /migrations

RUN chmod +x /migrate.sh

CMD ["/migrate.sh"]
