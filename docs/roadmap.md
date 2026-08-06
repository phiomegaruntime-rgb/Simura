# CellTwin Roadmap

The project is built one component at a time. Each component is independently
useful and leaves the repo in a runnable, tested state.

## Component 1 — Physics simulator ✅ (v0.1)

A vectorized electro-thermal battery pack model with fault injection, emitting a
stable telemetry contract.

- [x] Cell electrical model (Thevenin ECM + OCV–SoC), thermal model, coulomb counting
- [x] Pack assembly with exact series/parallel current sharing and imbalance
- [x] Fault framework: internal short, resistance growth, cooling loss, thermal runaway, sensor drift
- [x] Load profiles (constant current/power, charge–discharge cycle, sinusoidal)
- [x] Telemetry snapshot dataclasses + example + physics-invariant tests

**Backlog for the sim** (nice-to-have, non-blocking): LFP/other chemistries,
2nd-order RC, Arrhenius temperature-dependent parameters, calendar aging,
temperature-dependent OCV.

## Component 2 — Twin core + time-series store ✅ (v0.2)

Turn the simulator's telemetry stream into a persisted, queryable twin.

- [x] Telemetry transport over **MQTT** (`aiomqtt`) — publisher publishes,
  twin core subscribes. Decouples "the asset" from "the twin." Retained config
  topic so late-joining twin cores still learn each system's topology.
- [x] **TimescaleDB** (`asyncpg`) for history; hypertables for pack/cell series,
  `time_bucket` downsampling for history queries.
- [x] **FastAPI** service: live state (REST), history (downsampled), per-cell
  view, and a per-system live stream (WebSocket). Twin registry via `systems`
  table so multiple packs/systems coexist.
- [x] `docker compose -f deploy/docker-compose.yml up --build` brings up broker +
  DB + twin core + a simulated asset together.

**Verified end-to-end:** the injected internal short in module 3 shows up in the
twin as the hottest cell (module 3, slot 0) with drained SoC, queryable via REST
and streamed over WebSocket.

## Component 3 — Live dashboard ✅ (v0.3)

A screenshot that makes people want to try it. React + TypeScript + Tailwind +
Recharts, served by nginx (which also proxies the API + WebSocket).

- [x] Real-time cell heatmap (temp / voltage / SoC) with per-cell hover and an
  absolute-scale temperature colorbar, so an overheating cell visibly stands out.
- [x] Health banner + stat tiles (voltage, power, SoC, max temp with status).
- [x] Live SoC and temperature trend charts (single-series each, no dual axis),
  seeded from REST history and updated over the WebSocket.
- [x] Client-derived fault timeline; system selector; live-connection indicator.
- [x] Added to the compose stack as the `dashboard` service on port 8080.

**Verified visually:** with the fault scenario running, module 3 glows amber on
the heatmap while neighbours stay calm, and the temperature trend shows the
fault's repeating sawtooth. Colors follow the data-viz design system (reserved
status colors, absolute thermal scale, per-metric ramps).

## Component 4 — Anomaly detection ✅ (v0.4)

Flag cells misbehaving *before* they cross any absolute limit.

- [x] `celltwin.detect` — a pure, unit-tested library: **peer-consensus** robust
  z-scores (median + MAD across the pack, per metric), combined into a directional
  anomaly score and smoothed with an EWMA so only sustained deviation flags. No
  training data, no per-asset tuning.
- [x] `detector` service subscribes to telemetry, publishes to `celltwin/anomaly/{id}`.
- [x] Twin core ingests anomaly frames: `anomaly_summary` hypertable, live cache,
  `/api/systems/{id}/anomaly` + `/anomaly/history`, WebSocket broadcast.
- [x] Dashboard: anomaly heatmap view + per-cell badges, anomaly panel, score
  trend, and anomaly folded into the health banner as early warning.
- [x] Added to the compose stack as the `detector` service.

**Verified end-to-end:** the internal-short cell is flagged **critical at ~36 °C**,
~5 min (sim) before its temperature reaches the 45 °C limit — while a healthy pack
stays quiet (peak score < 1.2, zero false positives). Calibrated against the
simulator's healthy vs. fault scenarios.

## Component 5 — Diagnosis, SoH, RUL & safety ✅ (v0.5)

The capstone intelligence: not just *that* something is wrong, but *what*, *how
healthy*, *how long*, and *how dangerous*.

- [x] `celltwin.health` — a pure, unit-tested library:
  - **Diagnosis** by fault-fingerprint matching over the anomaly z-scores +
    health features: tells internal short / cooling fault / resistance growth /
    sensor fault / thermal runaway apart, with a confidence and a plain-English
    rationale.
  - **State of health** from online DCIR estimation (`(OCV(SoC) − V)/I`), so
    resistance growth shows up and a short/sensor fault correctly does not.
  - **RUL** as acute time-to-critical from the smoothed heating rate.
  - **Safety state** (nominal / warning / **alarm**) with a runaway alarm.
- [x] The `analytics` service publishes assessments to `celltwin/assessment/{id}`
  on the same frame as the anomaly (aligned features).
- [x] Twin core: `assessment_summary` hypertable, live cache, `/assessment` +
  `/assessment/history`, WebSocket broadcast.
- [x] Dashboard: a Diagnosis & Prognosis card (fault, confidence, rationale, SoH,
  time-to-critical) and safety folded into the health banner.

**Verified end-to-end:** the internal short is named "Internal short (100%
confidence)" with rationale *"25.4σ hotter and draining 3.8σ faster than peers"*
while max temperature still reads "Healthy". All five fault types are classified
correctly in tests; a healthy pack gets no diagnosis.

## Component 6 — Real-hardware connectors ✅ (v0.6)

Bring real BMS data in over industrial protocols, producing the *same* telemetry
envelope the simulator does — so the whole twin/analytics/dashboard stack works
on real data unchanged.

- [x] `celltwin.connect` — a protocol-agnostic **decode** core (`SourceFrame` +
  `DeviceMapping` → telemetry) that handles unit scaling, per-module→per-cell
  temperature expansion, and deriving the per-cell current/SoC a real BMS does
  not report.
- [x] Connectors: **Modbus TCP** (register map), **OPC-UA** (node ids), and an
  **MQTT bridge** (adapt a foreign JSON schema via dotted paths). Config-file
  driven (`examples/connectors/*.yaml`), no code to point at a device.
- [x] `celltwin.connect.devsim` — simulated Modbus/OPC-UA BMS devices (the
  hardware analog of the physics simulator) for demos and tests.
- [x] Added to the stack: a `device-sim` (Modbus) + `modbus-connector` feeding a
  second system, `bess-modbus-01`.

**Verified end-to-end:** Modbus-sourced data flows through decode → store →
anomaly → diagnosis → dashboard identically to simulator data. Round-trip tests
cover Modbus and OPC-UA (device sim → connector → decoded telemetry). A nice
honesty check: with per-module temperature and pack SoC, the Modbus system
diagnoses the internal short as a *cooling fault* — diagnosis degrades gracefully
with sensor granularity.

### Backlog
- CAN bus (python-can), Modbus RTU/serial, TLS/auth for OPC-UA and MQTT.

## Component 7 — Fleet, deployment & community 🚧 (v0.7, in progress)

Operate a *fleet* of twins, not one pack at a time, and start hardening for
real deployment.

- [x] `celltwin.fleet` — a pure, unit-tested rollup library: condense every
  system's latest telemetry/anomaly/assessment into one status row (overall
  level + plain-English reason, mirroring the single-system banner), with
  timestamp-based liveness. Fleet summary: counts by status, worst system,
  aggregate power, safety-alarm count.
- [x] `/api/fleet` — one call returns the whole fleet, worst-first. Thin wiring
  over `build_fleet`; all logic stays in the tested library.
- [x] **Optional API-key auth** (`CELLTWIN_API_KEY`): off by default so the demo
  stays frictionless; when set, REST + WebSocket require the key (Bearer /
  `X-API-Key` / `?api_key=`), while `/health` stays open for liveness probes.
  The dashboard's nginx injects the key on the `/api` + `/ws` upstream hop
  (envsubst-templated config), so the browser never handles it and the whole
  stack works secured with `CELLTWIN_API_KEY=… docker compose up`.
- [x] Dashboard **fleet overview**: a status-tiled grid of all systems that
  drills into the existing per-system dashboard; `bess-02` (healthy) added to
  the stack so the fleet shows a real healthy/faulted/Modbus mix.
- [x] **Docs site** (mkdocs-material, `mkdocs.yml` + `docs/`) with a GitHub Pages
  workflow, and a **contribution guide** (`CONTRIBUTING.md`).
- [x] **Expanded examples**: full analytics pipeline offline (`run_analytics.py`),
  a custom duty-cycle profile (`custom_profile.py`), a chemistry swap
  (`ocv_chemistry.py`, NMC vs LFP), and example/connector READMEs. Exposed
  `make_ocv` on the public `celltwin.sim` API.

**Verified:** the fleet rollup is unit-tested against hand-built envelopes and
the simulator's fault scenarios (internal short → critical, healthy → good), the
auth guard is tested across disabled/enabled and all three key transports, every
example runs, and `mkdocs build --strict` is clean.

### Backlog (remaining Component 7)
- **Helm chart / K8s manifests** for a cluster deployment (compose is dev-first).

## Component 8 — Validation against real battery data ✅ (v0.8)

Ground the twin in reality: check the physics model against **open,
publicly-licensed** battery datasets instead of taking it on faith.

- [x] `celltwin.validate` — a pure, unit-tested library:
  - **Catalog** of open datasets (NASA PCoE, Oxford, CALCE, Sandia,
    Stanford–MIT–TRI, RWTH Aachen, HNEI) with license, citation, and
    "what it validates" metadata. CellTwin redistributes **no** dataset bytes —
    only a directory pointing at each source.
  - **Loaders** normalize a user's own download (`.mat` via SciPy, or CSV) into
    one `ReferenceRun` (discharge-positive, matching the sim).
  - **Engine** replays the measured current through CellTwin's own 1×1 cell model
    and reports terminal-voltage error (RMSE/MAE/max/bias), with an optional
    best-fit R0/SoC scan — a single source of physics truth (reuses `BatteryPack`).
- [x] A tiny, clearly-labelled **synthetic** sample bundled so the CLI, tests, and
  a dashboard demo run offline out of the box.
- [x] Twin core: `GET /api/validation/datasets` (the selectable catalog) and
  `POST /api/validation/run` (an in-browser demonstration on the synthetic sample,
  honestly labelled — it never claims to have validated a real dataset).
- [x] Dashboard **Validation** view: selectable dataset cards (license badge,
  copy-citation, copy-CLI-command) + a measured-vs-model voltage overlay and
  RMSE/MAE/bias tiles.
- [x] CLI (`python -m celltwin.validate`), `examples/validate_demo.py`, and docs.

**Verified:** on the synthetic sample (true R0 = 25 mΩ), the nominal model
(R0 = 20 mΩ) gives RMSE 19.6 mV; fitting recovers R0 = 25 mΩ and drops RMSE to
1.9 mV — the 2 mV noise floor. 13 new tests pass; the dashboard builds clean.

### Backlog
- Chemistry-specific OCV tables (LFP) so non-NMC datasets validate without the
  built-in-NMC-curve caveat; capacity-fade/SoH validation across aging cycles;
  optional browser file-upload so real downloads can be validated in-app.

## Component 9 — User-defined systems ✅ (v0.9)

Let users design and test their own BESS, not just the built-in scenarios.

- [x] `celltwin.builder` — a pure, unit-tested library: a JSON-serializable
  `SystemSpec` (chemistry, cell params, topology, load profile, faults, sim
  settings), `validate_spec` (a list of problems, not a crash), `build_simulator`
  (reuses `celltwin.sim` and swaps in the chemistry's OCV curve), and `preview`
  (runs the spec **offline** — no MQTT, no DB — into a summary: final/min SoC,
  voltage window, peak temp, energy throughput, whether the temp limit was crossed
  and when, plus sparklines).
- [x] Twin core: `GET /api/builder/options` (form enumerations + a default spec),
  `POST /api/builder/validate`, `POST /api/builder/preview` (400 with the error
  list if invalid). Pure compute — no process management in the twin core.
- [x] Publisher **`--spec my.json`** builds exactly the previewed simulator and
  streams it live, so a custom system joins the fleet/analytics/dashboard like any
  other. `python -m celltwin.builder --example|--validate|--preview` CLI too.
- [x] Dashboard **Build** view: a form over the spec (chemistry, topology, profile,
  faults), an offline **Preview** with summary tiles + SoC/temp/voltage sparklines,
  and **Export spec JSON** + **Copy go-live command**.

**Verified:** the builder is unit-tested (spec round-trip, validation catches bad
topology/chemistry/fault-cell/step-count, every profile & fault type builds and
runs, LFP uses the LFP voltage range, a hard short trips the temp limit); the API
is exercised over HTTP (options/validate/preview, 400 on invalid); the example and
CLI run; the dashboard builds clean.

### Backlog
- Import an existing system's config as a starting spec.

## Component 10 — System lifecycle & sources ✅ (v0.10)

Control systems from the app, and choose where their data comes from.

- [x] The twin core can **run simulations itself** (`celltwin.twincore.simctl.SimManager`):
  a Component-9 `SystemSpec` is run in-process and published to MQTT exactly like
  the external publisher, so it flows through ingest → store → analytics → fleet
  unchanged — but the twin core holds the task handle. The manager is MQTT-agnostic
  (injected `publish`), so its lifecycle is unit-tested with a fake publisher.
- [x] **Sources**: `simulation` (twin-core-run, controllable) vs `realtime`
  (external feed — publisher/connector/real BMS — ingest-only). Persisted on the
  `systems` registry (`source`/`spec`/`run_state`); running sims are restored on boot.
- [x] Endpoints: `POST /api/systems` (create sim or register real-time),
  `POST /api/systems/{id}/start|pause|resume` (409 for real-time),
  `DELETE /api/systems/{id}` (full purge: registry + history + retained config).
  `/api/fleet` and `/api/systems` carry `source` + live `run_state`.
- [x] Dashboard: fleet cards get **Start/Pause/Resume/Delete** (sims) or
  **Delete only** (real-time) with a source badge, an inline delete-confirm, and a
  **+ New system** dialog; the Build tab gains **▶ Start in fleet**.

**Verified:** `test_simctl` drives create/start/pause(frozen)/resume/stop/remove
with a fake publisher; fleet rollup carries source/run_state; the control endpoints
are exercised over HTTP (create sim + real-time, 409 on real-time pause, 400 on a
bad spec, DELETE purge); pause/resume/delete confirmed live in the rebuilt stack.

### Backlog
- Opt-in resilience: auto-restart a sim if the broker blips (today a broker loss
  stops sims, which can be re-started); per-sim speed control from the UI.

## Component 11 — Weather & environmental coupling ✅ (v0.11)

Make the environment part of the simulation — and do it reusably.

- [x] **Standalone, domain-agnostic package** `celltwin.weather` (zero back-deps on
  the simulator): a `WeatherSample` contract + a one-method `WeatherProvider`
  interface, with `Static` / `Synthetic` (deterministic diurnal, offline) /
  `CsvReplay` / `OpenMeteo` (live, **no API key**) providers, plus a `CachedProvider`
  that caches and **falls back offline on any error**. Declarative `build_provider`.
- [x] **Physics coupling** (`celltwin.sim.environment`): maps a weather sample onto
  three levers the thermal model already exposes — air temperature → ambient,
  wind → convective cooling, solar → per-cell heat load. `BatteryPack.step` gains an
  optional `ambient_c`; the `Simulator` queries the provider each step and stamps the
  conditions onto each telemetry frame. Backward-compatible: no provider → unchanged.
- [x] **Builder integration**: an optional `WeatherSpec` on `SystemSpec`
  (`type="none"` by default), validated, exposed via `/api/builder/options`, and
  summarised in the offline preview (ambient range, peak solar, ambient sparkline).
  Preview substitutes a synthetic stand-in for live sources so it stays offline.
- [x] **Live**: publisher `--spec` and twin-core-run sims pick up weather
  automatically; a live source's first fetch runs **off the event loop**. Dashboard
  Build form gains a **Weather** section and the system view a live ambient/wind/solar
  strip + a cell-temp-vs-ambient overlay.

**Verified:** `test_weather` (21) covers the samples, every provider (Open-Meteo
parsed from a saved fixture — no network), the cache fallback, and an end-to-end
proof that cell temperatures track a diurnal ambient; builder + simctl weather tests
pass; dashboard `npm run build` and `mkdocs build --strict` clean.

### Backlog
- Persist weather to history (needs a schema column); calibrate coupling
  coefficients against a real enclosure; async weather fetch client.
