#!/usr/bin/env bash
# 5-minute health watchdog for the 14-day unattended run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${WATCHDOG_LOG_DIR:-$ROOT/ops/logs}"
LOG_FILE="$LOG_DIR/watchdog.log"
ALERT_FILE="$LOG_DIR/alerts.log"
COMPOSE_DIR="$ROOT"
DISK_LIMIT_PCT="${DISK_LIMIT_PCT:-85}"
REDIS_MEM_LIMIT_PCT="${REDIS_MEM_LIMIT_PCT:-90}"

mkdir -p "$LOG_DIR"
ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

log() {
  echo "$(ts) $*" | tee -a "$LOG_FILE"
}

alert() {
  local msg="$*"
  echo "$(ts) ALERT $msg" | tee -a "$ALERT_FILE" >>"$LOG_FILE"
  # Desktop notification when available (silent otherwise).
  if command -v notify-send >/dev/null 2>&1; then
    notify-send -u critical "polymarketer watchdog" "$msg" 2>/dev/null || true
  fi
}

fail=0

# --- HTTP healthz ---
for url in \
  "http://127.0.0.1:8080/healthz" \
  "http://127.0.0.1:8090/healthz" \
  "http://127.0.0.1:8091/api/healthz"
do
  if ! curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
    alert "healthz_failed $url"
    fail=1
  else
    log "ok healthz $url"
  fi
done

# --- Disk ---
disk_pct="$(df -P / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
if [[ -n "$disk_pct" && "$disk_pct" -ge "$DISK_LIMIT_PCT" ]]; then
  alert "disk_high root=${disk_pct}% limit=${DISK_LIMIT_PCT}%"
  fail=1
else
  log "ok disk root=${disk_pct}%"
fi

# --- Redis memory ---
if command -v docker >/dev/null 2>&1; then
  used="$(cd "$COMPOSE_DIR" && docker compose exec -T redis redis-cli INFO memory 2>/dev/null \
    | awk -F: '/^used_memory:/{gsub(/\r/,"",$2); print $2}')"
  maxm="$(cd "$COMPOSE_DIR" && docker compose exec -T redis redis-cli INFO memory 2>/dev/null \
    | awk -F: '/^maxmemory:/{gsub(/\r/,"",$2); print $2}')"
  if [[ -n "${used:-}" && -n "${maxm:-}" && "$maxm" -gt 0 ]]; then
    pct=$(( used * 100 / maxm ))
    if [[ "$pct" -ge "$REDIS_MEM_LIMIT_PCT" ]]; then
      alert "redis_mem_high used=${used} max=${maxm} pct=${pct}%"
      fail=1
    else
      log "ok redis_mem used=${used} max=${maxm} pct=${pct}%"
    fi
  else
    alert "redis_mem_check_failed"
    fail=1
  fi

  # --- Timescale chunk health ---
  chunk_info="$(cd "$COMPOSE_DIR" && docker compose exec -T timescaledb \
    psql -U kalshi -d kalshi -t -A -c \
    "SELECT COUNT(*)||'|'||COALESCE(SUM(CASE WHEN is_compressed THEN 1 ELSE 0 END),0)||'|'||pg_size_pretty(hypertable_size('book_deltas'))
     FROM timescaledb_information.chunks WHERE hypertable_name='book_deltas';" 2>/dev/null | tr -d '\r')"
  if [[ -z "$chunk_info" ]]; then
    alert "timescale_chunk_check_failed"
    fail=1
  else
    chunks="${chunk_info%%|*}"
    rest="${chunk_info#*|}"
    compressed="${rest%%|*}"
    size="${rest#*|}"
    log "ok book_deltas chunks=${chunks} compressed=${compressed} size=${size}"
    if [[ "${chunks:-0}" -lt 1 ]]; then
      alert "book_deltas_no_chunks"
      fail=1
    fi
  fi

  # --- Compose container status ---
  unhealthy="$(cd "$COMPOSE_DIR" && docker compose ps --format '{{.Name}} {{.Status}}' 2>/dev/null \
    | awk '/unhealthy|Restarting|Exited/ {print}' || true)"
  if [[ -n "$unhealthy" ]]; then
    alert "containers_bad $(echo "$unhealthy" | tr '\n' ';')"
    fail=1
  else
    log "ok containers"
  fi
fi

if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
exit 0
