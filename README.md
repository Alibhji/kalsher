# Kalshi Live Market Data Pipeline

Live dashboard and data pipeline for Kalshi crypto calendar markets ([kalshi.com/calendar/crypto](https://kalshi.com/calendar/crypto)). REST discovery plus WebSocket streaming into Redis (hot state) and TimescaleDB (history). The UI shows active bets with live quotes, charts, and an archive of closed windows.

**Tracked series** (configurable in `fetcher/config.yaml`):

| Type | Tickers |
|------|---------|
| 15-minute binaries | `KXBTC15M`, `KXETH15M`, `KXDOGE15M`, `KXBNB15M`, `KXSOL15M`, `KXHYPE15M`, `KXXRP15M` |
| Hourly strike ladders | `KXBTCD`, `KXETHD`, `KXSOLD` |

---

## Components

```
Kalshi REST + WS
       │
       ▼
  ┌─────────┐     kalshi:live      ┌──────────────┐
  │ fetcher │ ── pub/sub ────────► │     ui       │ ──► browser :8090
  └────┬────┘                      └──────┬───────┘
       │                                  │
       ├──────────► redis  (hot quotes, universe, streams)
       │
       └──────────► timescaledb  (ticks, markets, archive)
```

| Component | Path | Role |
|-----------|------|------|
| **fetcher** | `fetcher/` | Discovers markets per series, subscribes to Kalshi WS (ticker, trades, book, lifecycle), enriches metadata, archives closed markets, publishes live fanout |
| **ui** | `ui/` | FastAPI/aiohttp server + React dashboard: live table, WebSocket gateway, charts, archive panel |
| **redis** | `storage/redis.conf` | Hot market hashes, universe set, Redis streams for downstream analyzers |
| **timescaledb** | `storage/migrations/` | Hypertables for ticks/trades/book; `markets` table + archive queries |
| **migrator** | `storage/` | One-shot job: applies SQL migrations on startup |
| **common** | `common/` | Shared Kalshi client, settings, liquidity helpers, models |

When a 15m window **closes**, the fetcher archives it to TimescaleDB, removes it from Redis, rescans for the **next** event, and the UI receives WebSocket `rm` / `add` messages so the dashboard updates without refresh.

---

## Setup

### Prerequisites

- Docker + Docker Compose
- Kalshi API key ID + RSA private key ([Kalshi → Account → API Keys](https://kalshi.com))
- For **demo**: use demo credentials and the URLs in `.env.example`
- For **production**: uncomment production URLs in `.env`

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

- Set `KALSHI_KEY_ID` to your API key ID
- Leave `KALSHI_REST_BASE` / `KALSHI_WS_URL` on demo or switch to production

### 2. Add your private key

Docker Compose mounts the key from the **project root**:

```bash
cp /path/to/your/kalshi-private-key.pem ./kalshi.pem
chmod 600 kalshi.pem
```

(`kalshi.pem` is gitignored — never commit it.)

Alternatively, place a copy in `secrets/kalshi_private_key.pem` and symlink: `ln -sf secrets/kalshi_private_key.pem kalshi.pem`

### 3. Start the stack

```bash
docker compose up --build
```

Startup order: TimescaleDB + Redis → migrator (schema) → fetcher → UI.

### 4. Open the dashboard

- **UI:** [http://localhost:8090](http://localhost:8090)
- **Fetcher metrics:** [http://localhost:8080/metrics](http://localhost:8080/metrics)
- **Fetcher health:** [http://localhost:8080/healthz](http://localhost:8080/healthz)

---

## Configuration

| File | Purpose |
|------|---------|
| `fetcher/config.yaml` | Series allowlist, discovery interval, WS channels, sink batching |
| `ui/config.yaml` | Live-only filter, archive limits, underlying symbol map |
| `.env` | API credentials, log level, ports |

Key fetcher knob: `filters.series_allowlist` and `live_event_only: true` (one live event per series, ~800 tickers).

Set `DEBUG=true` in `.env` for verbose logs (WS payloads, REST traces). Default is quiet.

---

## API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET :8090/api/markets` | Active markets JSON |
| `GET :8090/api/markets/{ticker}/history` | Chart history (TimescaleDB) |
| `GET :8090/api/archive/tree` | Closed liquid bets (grouped) |
| `WS :8090/ws` | Live quotes + add/remove on rollover |
| `GET :8090/metrics` | Hub size, feed lag, WS clients |

---

## Local development (optional)

**Python tests**

```bash
cd ui && python3 -m pytest tests/ -q
cd fetcher && python3 -m pytest tests/ -q
```

**Frontend only** (proxies API/WS to `:8090`)

```bash
cd ui/web
npm install
npm run dev
```

**Rebuild UI after frontend changes**

```bash
docker compose build ui && docker compose up -d ui
```

---

## Analyzer / downstream access

- **Redis hot state:** `kalshi:market:{ticker}`, `kalshi:universe`, `kalshi:book:{ticker}:{yes|no}`
- **Redis pub/sub:** `kalshi:live` (msgpack fanout from fetcher)
- **Redis streams:** `kalshi:stream:ticks`, `trades`, `book`, `underlying`
- **TimescaleDB:** `ticks`, `trades`, `book_deltas`, `markets`, continuous aggregates `market_1s`

---

## Project layout

```
├── common/           Shared libraries
├── fetcher/          Ingestion service
├── ui/
│   ├── server/       Python API + WS gateway
│   └── web/          React + Vite frontend
├── storage/
│   ├── migrations/   Timescale schema
│   └── clients/      Redis + Timescale writers
├── docker-compose.yml
├── .env.example
└── kalshi.pem        Your key (gitignored)
```
