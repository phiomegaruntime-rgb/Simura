# Twin core & API

The twin core ingests the fleet's telemetry over MQTT, persists it to
TimescaleDB, and serves the live twin over REST + WebSocket. It only ever sees
the MQTT **envelope** (`{system_id, timestamp, telemetry}`) — never the simulator
— which is what makes real hardware swappable. See the
[architecture](architecture.md) for the data flow.

## REST endpoints

**Fleet**

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/api/fleet` | Whole-fleet rollup: one status row per system (worst-first) + a summary (counts by status, worst system, aggregate power, alarms, live count). |
| `GET` | `/api/systems` | The twin registry (with `source`, `run_state`, `live`). |
| `POST` | `/api/systems` | Create a **simulation** (from a spec, twin-core-run) or register a **real-time** system. |
| `POST` | `/api/systems/{id}/start` \| `/pause` \| `/resume` | Control a simulation's run state (409 for real-time). |
| `DELETE` | `/api/systems/{id}` | Purge a system: stop its sim, clear retained config, delete registry + history. |

**Per system** (`{id}` = a `system_id`)

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/api/systems/{id}/state` | Latest telemetry frame (from memory if live, else the DB). |
| `GET` | `/api/systems/{id}/cells` | Latest per-cell telemetry. |
| `GET` | `/api/systems/{id}/history?minutes=&bucket_s=` | Pack history, optionally downsampled with `time_bucket`. |
| `GET` | `/api/systems/{id}/anomaly` | Latest full anomaly report (per-cell scores). |
| `GET` | `/api/systems/{id}/anomaly/history?minutes=&bucket_s=` | Anomaly-score history. |
| `GET` | `/api/systems/{id}/assessment` | Latest full assessment (diagnosis, per-cell SoH, RUL, safety). |
| `GET` | `/api/systems/{id}/assessment/history?minutes=&bucket_s=` | State-of-health history. |

**Validation** (see [Validation](validation.md))

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/api/validation/datasets` | The catalog of open datasets (metadata + license) to select and validate against. |
| `POST` | `/api/validation/run` | In-browser demo: validates a bundled synthetic sample matched to the requested dataset's chemistry. |
| `POST` | `/api/validation/upload` | Validate the model against an **uploaded** dataset file (multipart; CSV, or `.mat` with SciPy). |

**System builder** (see [System builder](builder.md))

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/api/builder/options` | Enumerations (chemistries, profile & fault types + params) and a default spec for the form. |
| `POST` | `/api/builder/validate` | `{valid, errors}` for a user's system spec. |
| `POST` | `/api/builder/preview` | Offline run of a spec: summary + sparklines (400 with `errors` if invalid). |

**Health**

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/health` | `{"status": "ok"}` — unauthenticated, for liveness probes. |

Interactive docs are served at `/docs` (Swagger UI) when the twin core is
running.

### Sources & lifecycle

Every system has a **source**:

- **`realtime`** — fed by an external process (a `publisher`, a connector, or a
  real BMS) publishing to `celltwin/telemetry/{id}`. The twin core only ingests
  it, so it supports **Delete** only (you can't pause a real battery or a foreign
  process). External feeds auto-register as `realtime` on first message.
- **`simulation`** — built from a Component-9 `SystemSpec` and **run by the twin
  core itself** (via the `SimManager`, which publishes to MQTT exactly like the
  external publisher, so ingest/analytics/fleet treat it identically). These are
  fully controllable: **start / pause / resume / delete**. `run_state` is
  `running` / `paused` / `stopped`; a paused sim holds its state and stops
  publishing. Simulations are persisted with their spec and restored (running ones
  restarted) when the twin core boots.

`POST /api/systems` creates either kind; `DELETE` is a full purge (registry row +
all time-series history) and clears the retained MQTT config so a deleted system
never reappears. Speed is set by `CELLTWIN_SIM_DEFAULT_SPEED` (default 10×).

### The fleet rollup

`/api/fleet` aggregates the registry with the live telemetry/anomaly/assessment
caches into `{"summary": {...}, "systems": [...]}`. Each system row carries an
overall `status` (`good` / `warning` / `serious` / `critical`, the worst of its
temperature, imbalance, anomaly, and safety signals) and a plain-English
`status_reason`, plus the headline metrics (SoC, max temp, anomaly score, SoH,
fault type, safety state) and a timestamp-based `live` flag. The logic is a pure
library (`celltwin.fleet`); the endpoint is just wiring.

## WebSocket

```
ws://<host>/ws/systems/{id}
```

On connect the socket immediately sends the current telemetry, anomaly, and
assessment frames (so a new client isn't blank), then one message per frame as
they arrive. The three frame kinds are distinct envelopes on the same socket;
clients tell them apart by shape (`telemetry` / `anomaly` / `assessment`).

## Authentication

Auth is **off by default** so the demo stack stays frictionless. Set
`CELLTWIN_API_KEY` on the twin core to require it on every `/api/*` route and the
WebSocket; `/health` stays open. Present the key three ways:

```bash
# REST
curl -H "Authorization: Bearer $KEY" localhost:8000/api/fleet
curl -H "X-API-Key: $KEY"            localhost:8000/api/fleet

# WebSocket (browsers can't set headers on the handshake, so use a query param)
ws://localhost:8000/ws/systems/bess-01?api_key=<key>
```

The key is compared in constant time. A missing/invalid key gets `401` on REST;
the WebSocket is closed with code `1008` (policy violation).

### With the dashboard

The dashboard is a trusted same-origin front-end, so its **nginx injects the key
on the `/api` and `/ws` upstream hop** — the browser never handles it. Set the
key once and the whole stack is secured while the dashboard keeps working:

```bash
CELLTWIN_API_KEY=your-secret docker compose -f deploy/docker-compose.yml up --build
```

Both the `twincore` and `dashboard` services read `CELLTWIN_API_KEY`; nginx's
config is templated (`envsubst`) so the same value it enforces is the value it
injects. Direct access to `:8000` then requires the key; the dashboard on `:8080`
does not.

## Configuration

12-factor, all prefixed `CELLTWIN_` (defaults target a local `docker compose`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `CELLTWIN_MQTT_HOST` / `_PORT` | `localhost` / `1883` | Broker to subscribe to. |
| `CELLTWIN_DATABASE_URL` | local Postgres DSN | TimescaleDB connection. |
| `CELLTWIN_API_KEY` | *(empty = auth off)* | Optional API key. |
| `CELLTWIN_FLEET_STALE_AFTER_S` | `15` | A system is `live` in the rollup if its latest frame is newer than this. |
| `CELLTWIN_VALIDATION_MAX_UPLOAD_MB` | `25` | Max size of a dataset uploaded to `/api/validation/upload`. |
| `CELLTWIN_SIM_DEFAULT_SPEED` | `10` | Real-time multiplier for twin-core-run simulations. |
| `CELLTWIN_CORS_ORIGINS` | `*` | Allowed browser origins (matters mainly for the Vite dev server). |
| `CELLTWIN_DB_MIN_POOL` / `_MAX_POOL` | `1` / `5` | asyncpg pool bounds. |
| `CELLTWIN_DB_CONNECT_RETRIES` / `_RETRY_S` | `30` / `2.0` | Startup wait for the DB to come up. |

## Storage

TimescaleDB hypertables hold pack and per-cell series plus anomaly/assessment
summaries; `time_bucket` downsampling keeps wide history queries cheap. A
`systems` registry table lets many packs coexist. Schema lives in
`twincore/schema.sql`.
