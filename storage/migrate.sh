#!/bin/sh
set -e

echo "Running migrations..."

psql "$TIMESCALE_DSN" -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
SQL

for f in /migrations/*.sql; do
  name="$(basename "$f")"
  applied="$(psql "$TIMESCALE_DSN" -tAc "SELECT 1 FROM schema_migrations WHERE filename='$name'" | tr -d '[:space:]')"
  if [ "$applied" = "1" ]; then
    echo "Skipping $name (already applied)"
    continue
  fi
  echo "Applying $f"
  psql "$TIMESCALE_DSN" -v ON_ERROR_STOP=1 -f "$f"
  psql "$TIMESCALE_DSN" -v ON_ERROR_STOP=1 -c \
    "INSERT INTO schema_migrations(filename) VALUES ('$name')"
done

echo "Migrations complete."
