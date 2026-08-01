#!/bin/sh
set -e
echo "Running migrations..."
for f in /migrations/*.sql; do
  echo "Applying $f"
  psql "$TIMESCALE_DSN" -v ON_ERROR_STOP=1 -f "$f"
done
echo "Migrations complete."
