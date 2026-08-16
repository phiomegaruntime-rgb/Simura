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
| `GET` | `/api/systems/{id}/faults` | Every fault on a simulation, in the order applied. A fault's position is its handle. |
| `POST` | `/api/systems/{id}/faults` | Inject a fault into a **running** simulation (`{type, series, parallel, params}`), effective on its next timestep. 409 for real-time. |
| `DELETE` | `/api/systems/{id}/faults/{index}` | Repair **one** fault by position — fix a cell without fixing the pack. |
| `DELETE` | `/api/systems/{id}/faults` | Repair: drop every fault from the running simulation and its spec. |
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

**Wires** (pure compute — no MQTT, no DB)

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/api/wires/catalog` | Conductor materials, insulation classes, and the selectable wire catalog. |
| `POST` | `/api/wires/evaluate` | Check one run (`{spec, current_a, system_voltage_v?, max_drop_pct?, round_trip?}`) against ampacity / voltage drop / temperature. |
| `POST` | `/api/wires/recommend` | Smallest catalog wire meeting the constraints for a current/length/voltage/drop. |
| `POST` | `/api/wires/network` | Solve a multi-node wire network (`{nodes, segments, elapsed_s?, weather?}`); a segment may carry `faults`. |
| `GET` | `/api/wires/validation/standards` | Catalog of published DC-resistance standards the wire model can be checked against. |
| `POST` | `/api/wires/validation/run` | Validate the model against one bundled standard (`{standard_id}`): per-gauge percent error + published-vs-model curves. |
| `POST` | `/api/wires/validation/upload` | Validate against a user's measured-resistance CSV (multipart: `file`, `material`, `awg_col`, `resistance_col`, `ref_temp_c`, `resistance_unit`). |
| `GET` | `/api/lights/catalog` | Light technologies, lamps, fault/profile/control types, and task illuminance targets. |
| `POST` | `/api/lights/evaluate` | Check a lighting design (`{spec, n_luminaires, length_m, width_m, mounting_height_m?, task?, maintenance_hours?, weather?}`) against illuminance, colour and installed power. |
| `POST` | `/api/lights/recommend` | The catalog lamp meeting the target at the lowest installed power, plus every alternative ranked. |
| `POST` | `/api/lights/layout` | Solve the illuminance field over a room (`{length_m, width_m, grid?/luminaires?, target_lux?, min_uniformity?, weather?}`); a luminaire may carry `faults`. |
| `POST` | `/api/lights/spectrum` | One lamp's spectral power distribution and everything derived from it (`{spec, drive?, ambient_c?, bin_nm?}`). |
| `POST` | `/api/lights/simulate` | Run one luminaire through time — warm-up, thermal settle, controls, faults (`{spec, profile?, control?, faults?, weather?, dt_s?, duration_s?}`). |
| `GET` | `/api/lights/validation/standards` | Catalog of published photometric references the lighting model can be checked against. |
| `POST` | `/api/lights/validation/run` | Validate against one bundled standard (`{standard_id}`): per-point error, absolute and relative. |
| `POST` | `/api/lights/validation/live` | Validate the daylight model against **live** measured irradiance (`{latitude, longitude, hours?}`). The only route that reaches the network. |
| `POST` | `/api/lights/validation/upload` | Validate against a user's photometric CSV (multipart: `file`, `quantity`, `x_col`, `value_col`, `key_col`). |

**Weather**

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/api/weather/places?q=` | Places matching a name — label, coordinates, and the **IANA timezone** (what makes a local clock possible). Proxies Open-Meteo's geocoding so the browser keeps talking to one origin. A failed lookup is `[]`, not a 500. |
| `POST` | `/api/weather/sample` | Evaluate a weather spec (`{type, params}`) **right now**, with no system involved. `{"weather": null}` for `type: "none"`. Providers are cached per spec, so a live source fetches once rather than per call. |

**Health**

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/health` | `{"status": "ok"}` — unauthenticated, for liveness probes. |

Interactive docs are served at `/docs` (Swagger UI) when the twin core is
running.

### Injecting a fault into a running system

Faults used to be spec-time only, so breaking a pack meant rebuilding it from
`t=0`. `POST /api/systems/{id}/faults` instead appends to the two places a fault
lives — the **running** simulator's fault list, stamped with the simulator's
current time, and the **spec**, so it survives the run loop's duration rollover
and is republished with the retained config:

```bash
curl -X POST localhost:8000/api/systems/my-bess-01/faults \
  -H 'Content-Type: application/json' \
  -d '{"type": "internal_short", "series": 3, "parallel": 0, "params": {"r_short_ohm": 1.0}}'
```

The pack degrades from wherever it already is. Fault types and their parameters
are the ones `GET /api/builder/options` enumerates. A cell outside the pack's
topology, or an unknown type, is a 400 with `errors`.

`GET` the same path to list what's currently on a system. Faults come back in the
order they were applied, which is also the order of the running simulator's own
fault list — the two are built and appended in lockstep — so a fault's **position
is its handle**: `DELETE .../faults/2` repairs that one and leaves the rest of the
damage in place, while `DELETE .../faults` repairs everything.

This is what lets any operator tool walk up to a live rack, break one cell, and
later fix just that cell without disturbing the rest of the damage.

### Faulting a wire run

A segment in a network solve may carry `faults` (`[{type, ...params}]`, one of
`resistance_growth`, `contact_resistance`, `conductor_damage`,
`insulation_degradation`, `ground_fault`) and the body may carry `elapsed_s` —
how long they have been active, which matters for the ones that develop over time.

A fault changes the *conductance the network sees*, not just one wire's
temperature, so the whole network re-settles around it: a loose joint starves
everything downstream of it, and a ground fault leaks current that the load beyond
it never receives.

### Solving a network in weather

The body may carry `weather` (`{air_temp_c, wind_speed_ms?, solar_w_m2?}`, the
same shape `/api/wires/evaluate` takes). The whole network is then solved for that
day: every conductor cools toward the real ambient, wind multiplies its convective
cooling, absorbed sunlight adds heat scaled by each run's own sun-facing
silhouette, and **ampacity is derated for ambient** — the conservative standard
correction, which deliberately does not credit the wind.

Because resistance rises with temperature, a hot still day genuinely costs more
voltage at the far end of a run than a cold windy one. Weather rides the same
`FaultEffect` channels faults do (`cooling_mult`, `extra_heat_w`), exactly as
`WireSimulator` folds it in, so the two compose without a special case.

### Sources & lifecycle

Every system has a **source**:

- **`realtime`** — fed by an external process (a `publisher`, a connector, or a
  real BMS) publishing to `simura/telemetry/{id}`. The twin core only ingests
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
never reappears. Speed is set by `SIMURA_SIM_DEFAULT_SPEED` (default 10×).

### The fleet rollup

`/api/fleet` aggregates the registry with the live telemetry/anomaly/assessment
caches into `{"summary": {...}, "systems": [...]}`. Each system row carries an
overall `status` (`good` / `warning` / `serious` / `critical`, the worst of its
temperature, imbalance, anomaly, and safety signals) and a plain-English
`status_reason`, plus the headline metrics (SoC, max temp, anomaly score, SoH,
fault type, safety state) and a timestamp-based `live` flag. The logic is a pure
library (`simura.fleet`); the endpoint is just wiring.

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
`SIMURA_API_KEY` on the twin core to require it on every `/api/*` route and the
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
SIMURA_API_KEY=your-secret docker compose -f deploy/docker-compose.yml up --build
```

Both the `twincore` and `dashboard` services read `SIMURA_API_KEY`; nginx's
config is templated (`envsubst`) so the same value it enforces is the value it
injects. Direct access to `:8000` then requires the key; the dashboard on `:8080`
does not.

## Configuration

12-factor, all prefixed `SIMURA_` (defaults target a local `docker compose`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `SIMURA_MQTT_HOST` / `_PORT` | `localhost` / `1883` | Broker to subscribe to. |
| `SIMURA_DATABASE_URL` | local Postgres DSN | TimescaleDB connection. |
| `SIMURA_API_KEY` | *(empty = auth off)* | Optional API key. |
| `SIMURA_FLEET_STALE_AFTER_S` | `15` | A system is `live` in the rollup if its latest frame is newer than this. |
| `SIMURA_VALIDATION_MAX_UPLOAD_MB` | `25` | Max size of a dataset uploaded to `/api/validation/upload`. |
| `SIMURA_SIM_DEFAULT_SPEED` | `10` | Real-time multiplier for twin-core-run simulations. |
| `SIMURA_CORS_ORIGINS` | `*` | Allowed browser origins (matters mainly for the Vite dev server). |
| `SIMURA_DB_MIN_POOL` / `_MAX_POOL` | `1` / `5` | asyncpg pool bounds. |
| `SIMURA_DB_CONNECT_RETRIES` / `_RETRY_S` | `30` / `2.0` | Startup wait for the DB to come up. |

## Storage

TimescaleDB hypertables hold pack and per-cell series plus anomaly/assessment
summaries; `time_bucket` downsampling keeps wide history queries cheap. A
`systems` registry table lets many packs coexist. Schema lives in
`twincore/schema.sql`.
