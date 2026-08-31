# Simura Roadmap

The project is built one component at a time. Each component is independently
useful and leaves the repo in a runnable, tested state.

Development runs in **two phases**, against one mission — *a CRM for simulations, so
that anybody can simulate*.

- **Phase 1 — the physics substrate (v0.1 → v0.16, largely done).** Build faithful,
  independently-validated physics components (batteries, wires, lights) and the shared
  framework that serves them as live digital twins: a twin core, a dashboard, hardware
  connectors, validation against real data, and fleet control. This is the un-fakeable
  part — "anybody can simulate" is worthless on top of toy physics, so the substrate
  had to earn trust first. **Components 1–14 below are Phase 1.**
- **Phase 2 — the mission layer (in progress).** Turn that substrate into what the mission
  actually describes: a place where people from *different domains* get familiar with a
  simulation without becoming an expert in all of it, where knowledge *persists across
  projects* instead of restarting from zero, and where "everyone" can actually get in.
  Phase 1 optimised physics fidelity and breadth; Phase 2 optimises accessibility,
  collaboration, and reuse. **Components 15–19** are Phase 2, laid out at the end of this
  document — all of them built to run locally, with the hosted half of the original sketch
  parked in **Deferred — hosting & deployment**.
- **Phase 2.1 — the world outside the model (in parallel).** A second track, running
  alongside Phase 2 rather than after it, on a question neither phase had asked: every
  simulation Simura runs *stands somewhere*, and it did not know where. Phase 2.1 lets a
  system read its surroundings from the files that already describe them, in the way
  Component 11 let it read the weather. **Component 20** is Phase 2.1, and it is
  independent of Components 15–19 in both directions: neither blocks the other.

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

- [x] `simura.detect` — a pure, unit-tested library: **peer-consensus** robust
  z-scores (median + MAD across the pack, per metric), combined into a directional
  anomaly score and smoothed with an EWMA so only sustained deviation flags. No
  training data, no per-asset tuning.
- [x] `detector` service subscribes to telemetry, publishes to `simura/anomaly/{id}`.
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

- [x] `simura.health` — a pure, unit-tested library:
  - **Diagnosis** by fault-fingerprint matching over the anomaly z-scores +
    health features: tells internal short / cooling fault / resistance growth /
    sensor fault / thermal runaway apart, with a confidence and a plain-English
    rationale.
  - **State of health** from online DCIR estimation (`(OCV(SoC) − V)/I`), so
    resistance growth shows up and a short/sensor fault correctly does not.
  - **RUL** as acute time-to-critical from the smoothed heating rate.
  - **Safety state** (nominal / warning / **alarm**) with a runaway alarm.
- [x] The `analytics` service publishes assessments to `simura/assessment/{id}`
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

- [x] `simura.connect` — a protocol-agnostic **decode** core (`SourceFrame` +
  `DeviceMapping` → telemetry) that handles unit scaling, per-module→per-cell
  temperature expansion, and deriving the per-cell current/SoC a real BMS does
  not report.
- [x] Connectors: **Modbus TCP** (register map), **OPC-UA** (node ids), and an
  **MQTT bridge** (adapt a foreign JSON schema via dotted paths). Config-file
  driven (`examples/connectors/*.yaml`), no code to point at a device.
- [x] `simura.connect.devsim` — simulated Modbus/OPC-UA BMS devices (the
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

- [x] `simura.fleet` — a pure, unit-tested rollup library: condense every
  system's latest telemetry/anomaly/assessment into one status row (overall
  level + plain-English reason, mirroring the single-system banner), with
  timestamp-based liveness. Fleet summary: counts by status, worst system,
  aggregate power, safety-alarm count.
- [x] `/api/fleet` — one call returns the whole fleet, worst-first. Thin wiring
  over `build_fleet`; all logic stays in the tested library.
- [x] **Optional API-key auth** (`SIMURA_API_KEY`): off by default so the demo
  stays frictionless; when set, REST + WebSocket require the key (Bearer /
  `X-API-Key` / `?api_key=`), while `/health` stays open for liveness probes.
  The dashboard's nginx injects the key on the `/api` + `/ws` upstream hop
  (envsubst-templated config), so the browser never handles it and the whole
  stack works secured with `SIMURA_API_KEY=… docker compose up`.
- [x] Dashboard **fleet overview**: a status-tiled grid of all systems that
  drills into the existing per-system dashboard; `bess-02` (healthy) added to
  the stack so the fleet shows a real healthy/faulted/Modbus mix.
- [x] **Docs site** (mkdocs-material, `mkdocs.yml` + `docs/`) with a GitHub Pages
  workflow, and a **contribution guide** (`CONTRIBUTING.md`).
- [x] **Expanded examples**: full analytics pipeline offline (`run_analytics.py`),
  a custom duty-cycle profile (`custom_profile.py`), a chemistry swap
  (`ocv_chemistry.py`, NMC vs LFP), and example/connector READMEs. Exposed
  `make_ocv` on the public `simura.sim` API.

**Verified:** the fleet rollup is unit-tested against hand-built envelopes and
the simulator's fault scenarios (internal short → critical, healthy → good), the
auth guard is tested across disabled/enabled and all three key transports, every
example runs, and `mkdocs build --strict` is clean.

### Backlog (remaining Component 7)
- **Helm chart / K8s manifests** for a cluster deployment (compose is dev-first).

## Component 8 — Validation against real battery data ✅ (v0.8)

Ground the twin in reality: check the physics model against **open,
publicly-licensed** battery datasets instead of taking it on faith.

- [x] `simura.validate` — a pure, unit-tested library:
  - **Catalog** of open datasets (NASA PCoE, Oxford, CALCE, Sandia,
    Stanford–MIT–TRI, RWTH Aachen, HNEI) with license, citation, and
    "what it validates" metadata. Simura redistributes **no** dataset bytes —
    only a directory pointing at each source.
  - **Loaders** normalize a user's own download (`.mat` via SciPy, or CSV) into
    one `ReferenceRun` (discharge-positive, matching the sim).
  - **Engine** replays the measured current through Simura's own 1×1 cell model
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
- [x] CLI (`python -m simura.validate`), `examples/validate_demo.py`, and docs.

**Verified:** on the synthetic sample (true R0 = 25 mΩ), the nominal model
(R0 = 20 mΩ) gives RMSE 19.6 mV; fitting recovers R0 = 25 mΩ and drops RMSE to
1.9 mV — the 2 mV noise floor. 13 new tests pass; the dashboard builds clean.

### Backlog
- Chemistry-specific OCV tables (LFP) so non-NMC datasets validate without the
  built-in-NMC-curve caveat; capacity-fade/SoH validation across aging cycles;
  optional browser file-upload so real downloads can be validated in-app.

## Component 9 — User-defined systems ✅ (v0.9)

Let users design and test their own BESS, not just the built-in scenarios.

- [x] `simura.builder` — a pure, unit-tested library: a JSON-serializable
  `SystemSpec` (chemistry, cell params, topology, load profile, faults, sim
  settings), `validate_spec` (a list of problems, not a crash), `build_simulator`
  (reuses `simura.sim` and swaps in the chemistry's OCV curve), and `preview`
  (runs the spec **offline** — no MQTT, no DB — into a summary: final/min SoC,
  voltage window, peak temp, energy throughput, whether the temp limit was crossed
  and when, plus sparklines).
- [x] Twin core: `GET /api/builder/options` (form enumerations + a default spec),
  `POST /api/builder/validate`, `POST /api/builder/preview` (400 with the error
  list if invalid). Pure compute — no process management in the twin core.
- [x] Publisher **`--spec my.json`** builds exactly the previewed simulator and
  streams it live, so a custom system joins the fleet/analytics/dashboard like any
  other. `python -m simura.builder --example|--validate|--preview` CLI too.
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

- [x] The twin core can **run simulations itself** (`simura.twincore.simctl.SimManager`):
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

- [x] **Standalone, domain-agnostic package** `simura.weather` (zero back-deps on
  the simulator): a `WeatherSample` contract + a one-method `WeatherProvider`
  interface, with `Static` / `Synthetic` (deterministic diurnal, offline) /
  `CsvReplay` / `OpenMeteo` (live, **no API key**) providers, plus a `CachedProvider`
  that caches and **falls back offline on any error**. Declarative `build_provider`.
- [x] **Physics coupling** (`simura.sim.environment`): maps a weather sample onto
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
- [x] **Integrator stability guard**: `validate_spec` now rejects a `dt_s` too large
  for stable explicit-Euler integration of the RC branch (`dt < 2·r1·c1`) or the
  thermal node (`dt < 2·c_th/k_cool`, tightened by wind cooling), turning a silent
  numerical blow-up into a clear error with a suggested `dt_s`.

**Verified:** `test_weather` (21) covers the samples, every provider (Open-Meteo
parsed from a saved fixture — no network), the cache fallback, and an end-to-end
proof that cell temperatures track a diurnal ambient; builder + simctl weather tests
pass; dashboard `npm run build` and `mkdocs build --strict` clean.

### Backlog
- Persist weather to history (needs a schema column); calibrate coupling
  coefficients against a real enclosure; async weather fetch client.

## Component 12 — Wire simulation & wiring planning ✅ (v0.12)

Start growing Simura beyond the battery, toward a platform where users assemble
a machine from real electrical (and eventually mechanical) parts. The first such
part is the **wire**: pick from real wire types, simulate a conductor's
electro-thermal behaviour under load, and test wiring logic and planning.

- [x] **Standalone, domain-agnostic package** `simura.wires` (zero back-deps on
  the battery model, exactly like `simura.weather`): it knows conductors and
  electrical physics, not batteries. A `WireSpec`/`Wire` config-vs-state split, a
  `WireTelemetry` contract, and a `WireSimulator` generator — the same shapes as
  the battery `sim` package. Physics: `R = rho(T)·L/A` with a temperature
  coefficient, `ΔV = I·R`, `P = I²R`, and a lumped thermal node
  `dT/dt = (I²R − k_cool·(T−T_amb))/C_th` whose capacity/cooling default to
  geometry-based estimates.
- [x] **A catalog of real parts** (`catalog.py`): conductor materials (copper /
  aluminium / tinned copper), an AWG↔area table, insulation classes with
  temperature ratings, and curated `WireType`s with reference ampacity — the
  wiring analog of the OCV chemistry tables, honestly labelled as reference-only.
- [x] **Wiring logic & planning** (`planning.py`): `evaluate_run` checks a run
  against ampacity, voltage drop and insulation temperature (a list of problems,
  never a crash); `recommend_gauge` sizes the smallest catalog wire that
  satisfies every constraint. `round_trip` accounts for the two-conductor path.
- [x] **Multi-node network** (`network.py`): connect nodes with wire segments, fix
  a source voltage, draw loads, and solve the DC operating point by nodal analysis
  (`numpy.linalg`), iterating resistance↔temperature to a fixed point. Per-segment
  current / drop / loss / temperature / utilisation + a rolled-up problem list.
- [x] **Faults** (`faults.py`): the same accumulator pattern as the battery side —
  resistance growth (corrosion), contact resistance (loose joint), conductor
  damage (nicked strands), insulation degradation, and ground-fault leakage.
- [x] **Validation** (`validation/`): the wiring counterpart to the battery
  validation pipeline — check the conductor model against **published DC-resistance
  standards** (annealed copper at 20 °C / 75 °C, hard-drawn aluminium) or a user's
  measured-resistance CSV. Replays each gauge through the same `Wire` the twin uses
  and reports the per-gauge percent error (RMSE / MAE / max / mean-bias). The
  reference tables are computed offline from the standard resistivity and nominal
  AWG area (`R = ρ·L/A`), so the small, honest copper bias (~2.5 %, pure vs annealed
  copper) falls straight out.
- [x] **Weather coupling** (`environment.py`): the conductor counterpart to the
  battery's `sim.environment` — reuses the domain-agnostic `simura.weather` package
  to drive ambient temperature, wind-boosted convective cooling and absorbed solar
  heat (the standard conductor heat balance / dynamic line rating, cf. IEEE 738).
  Rides the fault-effect `cooling_mult` (wind) and `extra_heat_w` (sun) channels;
  weather conditions ride along on each `WireTelemetry` frame. Also threaded into
  the **planner**: `evaluate_run` / `recommend_gauge` take an optional weather
  sample, derating ampacity for ambient (standard `sqrt` correction) and reflecting
  wind/sun in the predicted temperature — surfaced in the dashboard **Wires** view.
- [x] **Declarative builders**, a CLI (`python -m simura.wires --catalog |
  --evaluate | --recommend | --network | --simulate [--weather]`, plus
  `python -m simura.wires.validation --list | --standard <id>`), three examples
  (`wire_planning.py`, `wire_thermal.py`, `wire_weather.py`), and a docs page.

**Verified:** `test_wires` (36) covers AWG area vs the standard table, `R = ρL/A`
against the textbook 12 AWG value and its temperature dependence, thermal
convergence to `ΔT = I²R/k_cool`, spec resolution, planning (over-ampacity, drop
limit, smallest-adequate gauge sizing), all fault types, telemetry round-trip, and
the network solve (a 2-node run's self-consistency, a branch conserving current
per KCL with monotonically dropping node voltages). `test_wire_validation` (11)
covers the standards catalog, the expected copper/aluminium resistivity bias, a
self-consistency zero-error check, overlay alignment, and the upload-CSV loader
(unit conversion, missing-column and non-standard-gauge handling).
`test_wire_weather` (15) covers the environment coupling's three levers and each
one's correct effect on steady-state temperature (hotter ambient, wind cools, sun
heats at zero current), telemetry carrying the conditions, and the weather-aware
planner (hot-ambient ampacity derating, cold-day uprating, wind cooling the
temperature without crediting the ampacity, and `recommend_gauge` sizing up on a
hot day). All three examples run and `mkdocs build --strict` stays clean.

### Backlog
- AC / reactance, temperature-derated catalog ampacity tables, bundle/conduit
  grouping factors, and mechanical parts (a future component family).

### Dashboard slice ✅

- [x] **Wiring planner** view: check a run / recommend a gauge + the wire catalog,
  over `/api/wires/{catalog,evaluate,recommend,network}`.
- [x] **Validation** view: validate the conductor model against a bundled standard
  or an uploaded CSV, over `/api/wires/validation/{standards,run,upload}`.
- All routes are pure compute (no MQTT, no DB), guarded by the same optional API
  key as the rest of `/api/*`. The dashboard opens on a landing of component cards
  (Batteries / Wires); each card scopes the header nav to that component.

> **Removed (v0.15):** the earlier *energy-flow systems* component (`simura.energyflow`
> — cells + wires coupled by nodal analysis) and the *DC-motor* mechanical part
> that built on it were removed from the project, along with their dashboard views,
> API endpoints, examples and docs.

## Component 13 — Reserved 🔒

This component number is taken by work that is **not part of the open-source
distribution**. It is developed separately and is not included in this
repository; nothing here depends on it, and the dashboard builds and runs
complete without it.

**Relationship to Phase 2.** The Phase 2 mission layer (Components 15–19) is
open-source and, like everything else in this repo, does **not** depend on Component 13;
where the two touch the same ground — a hosted front door, collaboration — Component 13
stays the separately-developed track, and the open mission layer must stand complete
without it, exactly as the substrate does today.

The platform work it drove *is* open source, and shipped in v0.15:

### Fault control and network faults (v0.15)

- [x] A full fault resource on a running simulation: `POST /api/systems/{id}/faults`
  injects one effective on the next timestep, `GET` lists what's attached,
  `DELETE .../faults/{index}` repairs **one** (fix a cell without fixing the pack),
  and `DELETE .../faults` repairs everything. `SimManager` now holds the live
  `Simulator`, stamps each fault with the simulator's current time, appends it to
  the spec as well so it survives the run loop's duration rollover, and republishes
  the retained config. The spec's fault list and the simulator's are built and
  appended in lockstep, which is what makes a position a usable handle.
- [x] Per-segment **faults in the network solve**: `Segment.faults` +
  `WireNetwork.solve(elapsed_s=...)`, a declarative `simura.wires.build_fault`,
  and `faults` / `elapsed_s` on `POST /api/wires/network`. A fault changes the
  conductance the network sees, so one loose joint starves the load beyond it.
- [x] **Weather in the network solve**: `WireNetwork.solve(weather=..., coupling=...)`
  and a `weather` body field on `POST /api/wires/network`, applying the existing
  `WireEnvironmentCoupling` per segment (solar scaled by each run's own silhouette)
  and derating ampacity for ambient — the same treatment `evaluate_run` already
  gave a single run, now for a whole network. Weather rides the same `FaultEffect`
  channels faults do, so the two compose with no special case.
- [x] An **optional-module slot** in the dashboard (`dashboard/src/modules/`,
  discovered by `src/lib/modules.ts`): a self-contained view ships its own landing
  card, sub-nav and lazily-loaded root, and the core app never imports one by
  name. See [Contributing](contributing.md).

**Verified:** `test_simctl` (+8) covers a fault injected into a running sim
reaching the targeted cell and making it the hottest in the pack, the "now" stamp,
config republication, cell-bounds and unknown-type rejection, listing in order,
removing one by index (leaving the spec and the live sim parallel), rejecting a
bad index without losing anything, and — the one that matters — a repaired cell
measurably cooling back down once its short is removed.
`test_wires` (+13) covers a loose joint re-settling the whole network, lost
cross-section derating a good run into an overload, aged insulation moving only
the rating, a ground fault leaking past the load, corrosion developing with
`elapsed_s`, and — importantly — that an unfaulted network is bit-for-bit what it
was before faults existed; and, for weather, a hot day costing both voltage and
headroom, wind cooling a run without crediting its rating, sun heating an idle
one, weather and faults compounding, and the no-weather path being untouched.
Full suite **189 pass**. The dashboard type-checks and builds.


## Component 14 — Light simulation & lighting design ✅ (v0.16)

**Goal.** The third standalone physics library, and the one where the useful
output is not measured in watts at all. Model **every kind of light source** —
LED to sodium arc — from its spectrum up, then answer the questions a lighting
engineer actually asks, couple it to weather *and* daylight, and validate it
against published photometry and the live sky.

### The design decision everything follows from

**Efficacy is computed, never looked up.** A source is a spectral power
distribution; Planck's law and the CIE 1931 observer turn that into lumens,
chromaticity and colour temperature. Nothing in the code says a dimmed filament
goes orange, or that warm white loses to cool white, or that low-pressure sodium
beats everything and renders no colour. All of it emerges — which is what makes
the model predictive rather than a lookup table with extra steps.

### What was built

- [x] **`simura.lights.spectrum`** — Planck's law, the Wyman–Sloan–Shirley analytic
  CIE colour-matching fit, luminous efficacy of radiation, chromaticity, McCamy
  CCT with a Planckian-locus guard (so a green laser correctly has *no* colour
  temperature), and SPD builders: blackbody, selective thermal (tungsten's
  non-grey emissivity, worth ~50% more efficacy), Gaussian bands, arc line
  spectra, and phosphor-converted white LED. Out-of-band infrared is tracked
  explicitly, because a filament puts 90% of its power there and omitting it
  would flatter every incandescent lamp by an order of magnitude.
- [x] **`simura.lights.catalog`** — 14 technologies across 4 families
  (incandescent/halogen; LED/high-CRI LED/laser diode; fluorescent/CFL/induction/
  low-pressure sodium/neon; metal halide/high-pressure sodium/mercury vapour/
  xenon arc) and 20 real lamps with published fluxes the model never consults.
- [x] **`simura.lights.lamp`** — three electrical laws behind one photometric
  chain. Filaments solve an energy balance by bisection with geometry back-solved
  from the design point; junctions obey a diode law with droop and thermal
  derating; arcs hold a fixed voltage with warm-up, restrike and vapour-pressure
  response. LED phosphor blends are chosen by walking the curve of blends that
  land on the Planckian locus — which is what binning really is.
- [x] **`simura.lights.photometry`** — solid angle, candela, inverse-square with
  Lambert's cosine, room index, utilisation factor, light loss factor, the lumen
  method, and standard-practice task illuminances.
- [x] **`simura.lights.planning`** — `evaluate_installation` / `recommend_lamp`,
  checking illuminance, colour rendering and installed power, at the *end* of a
  maintenance cycle by default. Returns every candidate ranked, because the trade
  between technologies is the interesting part.
- [x] **`simura.lights.layout`** — a split-flux illuminance field over a room:
  geometry for the direct component and its shape, interreflection added
  uniformly to match the lumen method. Reports the uniformity an average hides,
  with per-luminaire fault injection.
- [x] **`simura.lights.faults`** — the ways lighting actually fails, most of them
  gradual: lumen depreciation, phosphor degradation, heatsink loss, driver fault,
  supply sag, flicker, lens fouling, burnout.
- [x] **`simura.lights.environment`** — weather reaching a luminaire through *two*
  channels: thermally (ambient, wind, absorbed sun — moving LED and fluorescent
  output in opposite directions) and optically (daylight illuminance from solar
  geometry and a clear-sky model, driving photocell and daylight-harvesting
  controls that layer on top of a schedule).
- [x] **`simura.lights.simulator` / `profiles` / `telemetry` / `config`** — the
  same shape as the wire and battery sides: a generator yielding one frame per
  step, declarative builders for every fault, profile and control.

### Validation ✅

Five bundled standards, deliberately checking the model at five different depths
rather than five variations of one:

| Standard | What it checks | Result |
| --- | --- | --- |
| `cie-photopic-1931` | the analytic fit vs the tabulated CIE observer | RMSE 0.003 abs |
| `blackbody-cct-locus` | Planck + chromaticity + McCamy (an exact reference) | 0.8% |
| `lamp-efficacy-published` | the whole chain, 20 lamps, 4 families, 15× range | 6.5% |
| `led-junction-derating` | the solid-state derating law | 0.9% |
| `fluorescent-ambient-response` | the vapour-pressure response | 9.0% |

Reports carry absolute **and** relative metrics, because `V(λ)` passes through
0.0004 in the far violet where percent error is meaningless — so neither measure
can flatter the model.

- [x] **Real-time validation** (`--live`): the one reference in Simura that does
  not ship with the repository. Fetches measured shortwave radiation for a real
  place from Open-Meteo and checks the daylight model against it. Separates the
  clear-hour metrics (the honest test of geometry and the efficacy constant) from
  the all-hours error (which measures how cloudy the window was) and counts
  envelope violations. ~13% clear-hour RMSE over London.
- [x] **User uploads** — validate against your own integrating-sphere or datasheet
  CSV, with relative curves renormalised so a file normalised at 40 °C is not
  reported as error against a model normalised at 25 °C.

### Twin core & dashboard ✅

- [x] `GET /api/lights/catalog`, `POST /api/lights/{evaluate,recommend,layout,
  spectrum,simulate}`, `GET /api/lights/validation/standards`,
  `POST /api/lights/validation/{run,live,upload}` — all pure compute.
- [x] A **Lights** component card with a lighting planner (space and task, check /
  recommend / solve-the-field, ranked alternatives, an illuminance heatmap, and
  each lamp's spectrum drawn in its own colours) and a **Validation** view with
  the five standards plus the live-sky check and a place search.

**Verified:** `test_lights` (75) covers the spectral core against literature
anchors (2800 K → 15 lm/W, peak 95 lm/W at 6600 K, 555 nm → 683 lm/W), all four
families' physics, faults, photometry, planning and layouts — and, most usefully,
the *emergent* behaviours: dimming a filament costing far more light than power,
a hotter filament being the more efficacious one, fluorescent and LED derating in
opposite directions, warm white losing to cool white, and a hot HID lamp refusing
to restrike. `test_light_validation` (24) covers every standard, the upload path,
and the live daylight validation against a saved payload with no network — including
that it separates cloud from model error and that polar night is not reported as a
failure. Full suite **291 pass**. The dashboard type-checks and builds.

### Backlog
- Per-luminaire aiming and asymmetric (roadway) photometric distributions, real
  IES/LDT photometric file import, a proper CIE Ra from the test-colour samples,
  and glare metrics (UGR).

---

# Phase 2 — the mission layer (in progress)

Phase 1 built a substrate that is faithful, validated, and broad — three physics
components on one twin core. But the mission was never "the most faithful physics
library." It was *a CRM for simulations*: a common ground where people from different
domains get familiar with a simulation without becoming an expert in all of it, so a
project's knowledge no longer dies when the project ends and everyone stops having to
become a "learn-everything" generalist to be useful.

Measured against that mission, Phase 1 optimised the wrong axis on purpose — depth and
breadth of physics — because the accessible layer is worthless on top of physics no one
trusts. Phase 2 turns the substrate outward. The guiding shift:

> **Phase 1 asked "is the physics faithful?" Phase 2 asks "can someone who didn't build
> it understand it, reuse it, and work on it with others?"**

Almost none of the *CRM primitives* exist yet — the substrate is single-player, expert-only,
and starts fresh each time. The components below add them. They are ordered by leverage
on the mission, not by dependency; each is independently useful, in the Phase-1 spirit.

**Scope note — Phase 2 ships without hosting.** Every component below is built to run on
the stack that already exists: `pip install -e .`, `docker compose up`, or the Vite dev
server. The hosted, zero-install, public-URL half of the original Phase-2 sketch is
**deferred** and collected in [Deferred — hosting & deployment](#deferred--hosting--deployment)
at the end of this document. Nothing in Components 15–19 depends on it: the mission layer
must stand complete on a laptop, exactly as the substrate does today.

## Component 15 — The front door 🚧 (planned)

**Goal.** Make "everyone" able to physically get in. Today every entry point —
`pip install`, Python examples, `docker compose`, Modbus connectors — targets the
simulation engineer, i.e. the exact generalist the mission says shouldn't have to exist.
A non-expert can't reach a running twin.

- [ ] **A five-minute first simulation** for someone who has never opened the repo —
  a guided path from landing to a running, breakable system, with no reading required.
  This is the whole of Component 15 that ships locally, and it is the part that actually
  changes whether a newcomer gets anywhere.
- [ ] **A guided-tour surface in the dashboard** — the landing page hands you a system
  instead of a menu, and the first run is scripted end to end: build, run, break, read.
- ⏸️ **Zero-install, hosted Simura** — deferred, see
  [Deferred — hosting & deployment](#deferred--hosting--deployment).
- ⏸️ **The 3D sandbox as primary entry** — the sandbox is Component 13, developed
  separately and not part of this repository. The open front door must work without it,
  so promoting it is tracked with the sandbox, not here.

## Component 16 — The "get familiar" layer ✅ (v0.17)

**Goal.** Deliver the literal crux of the mission: *get familiar with a simulation
without becoming an expert in all of it.* The dashboard **reported** telemetry to
experts; it did not **teach** newcomers. This was the largest gap between what was built
and what was promised.

### The design decision everything follows from

**An explanation is *attributed*, never asserted.** Nothing in the code says "high
current makes a pack hot," or "long runs drop voltage," or "a dirty lens costs you lux."
The explainer evaluates each term of the model's *own* governing equation at the live
operating point, ranks the terms by how much they actually contribute, and the sentence
follows from whichever term won. Change the physics and the explanation changes with it,
because the explanation **is** the physics read out loud — the same commitment that made
efficacy computed, never looked up, in Component 14.

### Physics comes in two shapes, so there are exactly two decompositions

That is the whole architecture. *Things that add* — a cell's heat balance, a conductor's
heat balance, a terminal-voltage law, a split-flux illuminance field: the terms carry the
outcome's unit and sum to it, and the interesting cases are the ones where they cancel.
*Things that multiply* — a resistance, a lumen-method illuminance, a lamp's efficacy: no
factor has the outcome's unit, and shares come from `|ln factor|`, the only measure of
"how much did this move the answer" that does not depend on the order the factors are
written in. Every explanation in the project is one of those two.

### What was built

- [x] **`simura.explain`** — a standalone package, no new dependencies. `attribution`
  (the two decompositions), `battery` / `wires` / `lights` (the decompositions themselves,
  read out of the real models), `cards` + `glossary` (the plain-language layer),
  `domains` + `levels` (the two lenses), and `narrate` (grammar only — the physics
  decides the claim, this decides the verb).
- [x] **Exact, and inferred — and the difference is reported.** `explain_pack` reads the
  running solver, including each cell's own manufacturing spread and the fault and
  weather coefficients telemetry deliberately cannot carry. `explain_frame` has only a
  telemetry frame, so it recovers the internal states by **inverting the model** — the
  chemistry's curve gives OCV at the reported charge and the terminal law gives
  polarisation as the residual. That path is marked `exact=False` and carries the reason,
  including the useful consequence: if a cell sits well above the equilibrium the balance
  predicts, *that gap is the size of the heat source the frame cannot see*. Getting the
  exact path required one line in `simura.sim.simulator` — the applied `FaultEffect` is
  now kept, because a bare pack cannot see fault heat and explaining a faulted pack
  without it reports the cell shedding heat it is still making.
- [x] **Plain-language model cards** — 21 cards over 58 parameters, written for someone
  from another domain, each carrying its equation, its assumptions, a "reads like, if
  your field is…" restatement per domain, and — non-negotiably — **what it cannot tell
  you**. `coverage()` reflects over the real dataclasses and option registries and
  reports drift in both directions; the suite asserts both lists are empty and
  `GET /api/explain/coverage` serves the report, so the anti-drift claim is checkable
  from outside. A new parameter without a card is a failing build.
- [x] **A 33-entry glossary** with aliases, underlined in place wherever explanation
  prose shows a term — because a link to a glossary is a page nobody visits mid-sentence.
- [x] **Two separate knobs.** Seven **domain** lenses (newcomer, battery, thermal,
  safety, operations, electrical, lighting) choosing vocabulary and priority, and three
  **disclosure levels** (overview / working / physics). Separate because a lighting
  designer reading a battery wants *their own* words and *more* depth, which one
  beginner-to-expert slider cannot express. A lens reorders and never drops.
- [x] **Progressive disclosure that adds and never contradicts** — the headline is
  byte-identical at all three depths and every figure quoted at the top reappears
  unrounded at the bottom. A caveat is the one thing that does *not* vary with depth:
  trustworthiness is not a detail a deeper level reveals.
- [x] **API** — `GET /api/explain/{cards,cards/{id},glossary,lenses,coverage}`,
  `POST /api/explain/{battery,wires,lights}` (pure compute, and taking the *same body* as
  the check they explain, so the two can never describe different systems), and
  `GET /api/systems/{id}/explain`, which reports `source: model | telemetry`.
- [x] **Dashboard** — an explanation panel *above* the stat tiles on every running
  system, the same panel beside the wiring-planner and lighting-planner results, a
  **Learn** landing card browsing every model card and the glossary, and glossary
  tooltips in the prose.
- [x] **CLI + example** — `python -m simura.explain --battery --short --domain safety`
  and `examples/explain_a_fault.py`, which runs one pack healthy and one shorted and
  shows the fault-heat term appearing in the ranking.
- [x] **Explaining a single luminaire, and counterfactual chains.** `POST
  /api/explain/lamp` takes one entry of `/api/lights/operate`'s body — the shape a
  caller solving a *site* has, rather than a room — and answers the question a real
  fitting poses: it is rated for so many lumens and is producing fewer, so which of
  dimming, supply voltage, ambient, wear and faults did it? Those are conditions
  rather than separable terms, so each factor comes from **re-running the lamp model
  with exactly one condition changed**, chained from the rated point to the real one
  so the product telescopes exactly. It is the decomposition that makes the
  cable-dims-the-lamp coupling legible: the same 10% supply sag costs a filament a
  third of its light and a driven LED nothing at all, and neither number is written
  down anywhere.
- [x] **Explanations that cannot contradict the panel beside them.** `at_temp_c` on
  `POST /api/explain/wires` pins the conductor temperature a network solve already
  owns — it reflects the rest of the circuit, the weather and any faults, none of
  which a conductor spec carries. Being slightly wrong is recoverable; sitting one
  click from a number you quietly disagree with is not, because the reader has no
  way to tell which to believe.
- [x] **A zero factor takes the whole share.** The logarithm does not reach zero but
  the physics does, and without the rule a burnt-out lamp is reported as dark
  because of its supply voltage — true of the arithmetic, absurd as an explanation.
- [x] **Reusable by optional modules.** `ExplainPanel` takes a `bare` prop so a
  module with its own surface embeds it without nested card chrome. The 3D sandbox
  (Component 13, developed separately) uses it for a **Why** tab on its
  right-click inspect panel, so a rack, a cable and a luminaire in the world are
  each explained by the same computation the dashboard uses — built from the solve
  already on screen, so the two tabs agree.

### Verified

`test_explain` (86) is built around the one thing worth testing: that the sentences are
downstream of the physics. **Fidelity** — every attribution reproduces the number the
physics library itself reports, to that library's own precision: the heat balance against
`simura.sim.pack`'s derivative, the voltage sag against the terminal law, the wire drop
against `evaluate_run`, the illuminance against the lumen method, and lamp efficacy
against the model across all four source families over a 15× efficacy range.
**Responsiveness** — perturb the model and the ranking must move: a short adds a
fault-heat term that was not there and splits the charge rate into useful and wasted; the
same cell is generation-dominated cold and cooling-dominated warm; length beats gauge on
a long run and loses on a short one; a filament beats an LED on radiant efficiency and
loses tenfold on spectrum; dirtying the luminaires moves the dominant factor to dirt.
**Honesty** — inferred attributions carry their caveat at every depth, and a bare pack is
shown reporting less heat than the simulator does. **Rendering** — the headline is
identical across depths, the physics level hides nothing the ranking called negligible,
a directional verb is never contradicted by a negative number, and a lens never drops an
attribution. Plus a **vocabulary lint** that catches the class of bug that actually
happened during the build: a replacement phrase that reads fine alone and turns "Rated
ampacity" into "Rated the safe current for this cable".

`test_explain_api` (24) covers the routes: 4xx rather than 5xx on a bad lens, unknown
card, unsizeable conductor or unknown lamp; plain-JSON serialisation everywhere; and that
the live route takes the exact path when the twin core owns the model and the inferred
path when it does not, and says which.

One test earns its place by having caught a live bug rather than guarding a
hypothetical: a lamp past its rated life produces zero lumens, and ranking by
logarithm alone blamed its *supply voltage* for the darkness.

Full suite **413 pass**. The dashboard type-checks and builds.

### Backlog
- Trajectory attribution — everything here explains one operating point, so "it has been
  getting worse for ten minutes" is not yet sayable.
- Cross-cell ranking in the battery explainer (today one cell at a time, plus pack-wide
  imbalance); the anomaly layer covers the peer comparison separately.
- Counterfactuals — "what would this be at AWG 10" is a re-run the panel could offer
  rather than a number the reader has to go and produce.

## Component 17 — Memory that survives the project ✅ (v0.18)

**Goal.** Cure the origin wound directly. The pain that started Simura was that every
new project repeated from zero. Phase 1 could *export a spec JSON*, which solves the
smallest part of it — the numbers travel — and loses the part that actually cost somebody
a month: why those are the numbers, what was tried and rejected, and which of the three
racks in the folder was the one that was right.

### The design decision everything follows from

**What changed is computed; only why it changed is written down.** No entry in the
library stores a human-typed account of how it differs from its parent. That account is
*derived* from the two specs on every read, labelled in the vocabulary Component 16
already owns, and the reason a person types is bound automatically to exactly the fields
that moved. A changelog somebody maintains by hand is wrong within a month and nobody
finds out; a diff cannot be. It is Component 16's commitment applied to memory: an
attributed record rather than an asserted one.

The consequence is the part worth having. Because the reason is bound to the spec keys it
justifies, the library can answer a question no folder of spec files can — **which changes
has nobody explained?** It cannot make anyone explain a change, but it can refuse to
pretend the explanation is there, which tells the next person which question to go and ask.

### What was built

- [x] **`simura.library`** — a standalone package, no new dependencies. `record` (the
  entry, and the only four ways to make one), `diff` (what changed, and the join back to
  the reasons), `lineage` (walked from `parent_id`, never stored), `store` (an in-memory
  reference implementation and a one-JSON-file one) and `templates` (the starter set).
- [x] **A shared system library** — saved systems with provenance, notes and, above all,
  **decisions**: why a number is the number it is, *with the options considered and
  rejected* — the row absent from every spec format there is, and the first thing the next
  person re-derives from scratch. Entries are immutable, and their ids are content hashes,
  so saving the same thing twice is one entry and an entry keeps its identity across an
  export and an import.
- [x] **Versioning and lineage** — `revise` (the next version of one design) and `fork`
  (a second design that started from the first) are separate because the distinction is
  the *reader's*: a revision chain is a story about one design. Both **refuse to run
  without a reason**. `trace` walks the chain and pairs every computed step with the
  reason given for it; `inherited_context` hands a fork every note and decision from
  above, which is what "starting from project N" actually means.
- [x] **Reusable templates** — `promote` makes a system a starting point and, unlike a
  fork, copies the notes and decisions forward: a starting point stripped of the reasons
  behind it is just a spec file again.
- [x] **A starter set, held to the same rules.** Five bundled entries — two designs, a
  fork of each, one of those promoted — so day one is not a blank builder. They are built
  through the same constructors a user goes through, so the suite asserts every bundled
  spec validates and runs, each fork's diff matches what its reason claims, and no bundled
  change is unexplained. A starter set that cheated past the rules would teach people to.
- [x] **The loop back from a running twin.** `instantiate` records which entry a live
  system came from, and `capture` files a system that has since been tuned as that entry's
  *next version* rather than as another orphan spec. That loop is what makes the library
  accumulate rather than collect snapshots; it needed one new column on `systems`.
- [x] **A deletion that does not cascade.** Deleting a design leaves its forks standing,
  with their lineage honestly stopping at the id that is gone — losing somebody else's
  system because the design it came from was tidied away is the exact failure this
  component exists to prevent.
- [x] **API** — `GET/POST /api/library`, `/{id}`, `/{id}/trace`, `/tree`,
  `/{id}/{fork,revise,promote,notes,decisions,validated,instantiate}`, `/capture`,
  `/seed`, and `POST /api/library/diff`, which is pure compute so a form can show what an
  edit would change before anything is saved.
- [x] **Dashboard** — a **Library** section listing every saved system with its computed
  one-line diff; a detail panel showing what changed with the reason under it, grouped
  because one reason usually covers several fields, and an unexplained change rendered
  loudly with a form that binds a new reason to the fields you tick. "Open in builder"
  loads an entry into the Component-9 builder, which then shows the live diff against it
  as you type and offers two saves — *as v n+1* or *as a fork* — both requiring the reason
  and neither asking you to describe the change.
- [x] **Works with nothing running.** `python -m simura.library --seed --list --show
  --trace --tree --fork --note --diff` over a single JSON file. A library you can only
  read while a database is up is not memory that survives the project; it is memory that
  survives the container. The twin core persists the same entries in the TimescaleDB it
  already runs, and seeds the starter set into an **empty** library only — a library that
  keeps handing back a starter system its owner deleted is not memory either.
- [x] **A caller may supply a site, and nothing else.** Most of a spec is the design;
  `weather`, `profile` and `duration_s` describe *this run of it*. `simura.library.site`
  states that split once and both directions read it: `instantiate` accepts those three
  and refuses anything else, and `capture` takes them back off — from the parent entry, or
  from the builder's defaults when there is no parent — before recording anything. Without
  the rule a caller with a place of its own either cannot use the library at all, or fills
  every capture with "weather source none → synthetic" as a design change somebody has to
  justify, burying the change that matters under a note about the sky.
- [x] **A fault now reaches the registry.** Injecting or repairing one changed the
  running simulation's spec and nothing else, so the `systems` row went on describing a
  rack nobody had broken — which meant restarting the twin core silently repaired every
  faulted pack, and capturing one found nothing to record. The three fault routes write
  the live spec back. Found by building the capture loop, not by looking for it.
- [x] **Reusable by optional modules.** The 3D sandbox (Component 13, developed
  separately) puts every saved design in the player's hands: the inventory's first group is
  the library, placing an entry stands *that design* up — through `instantiate`, so the
  link back is derived by the twin core rather than asserted by the module — and the rack's
  right-click panel gains a **Library** tab reading back the decisions, what they rejected,
  and the notes. It writes, too: a note left in front of a rack that has just cooked goes on
  the *design*, and a rack somebody has broken can be saved as that design's next version,
  with the fault travelling and the weather staying behind.
- [x] **Example** — `examples/inherit_a_system.py`: three engineers, one library file, no
  services. Ana designs a rack, Ben inherits it for Phoenix and types one sentence, Cass
  reads the whole argument back six months later — and the last section shows, on purpose,
  what a change with no reason on file looks like.

### Verified

`test_library` (42) is built around the two halves of the claim. **Fidelity** — the diff
reports what the specs actually differ in and nothing else: a partial spec differs from a
complete one in nothing (an omitted field *is* its default), a field arrives labelled from
its model card with its unit and the reason it matters, a fault that appears reads as one
change rather than the four columns that store it while a fault that is *tuned* reads as
the fields that moved, and switching a load profile borrows the reasoning of the type
chosen. **Honesty** — a fork made through the constructors starts fully explained, and an
entry that arrived some other way is shown incomplete rather than assumed fine; a reason
covers only what it was bound to, so tuning a field afterwards is reported. Plus the rules
themselves: a fork or revision with no reason is refused, a spec that would not run is
refused, a deleted parent ends a chain instead of breaking the fork, and the bundled set
validates, runs, and comes out complete.

`test_library_api` (27) covers the wiring: 4xx rather than 5xx on a missing reason, an
unknown entry or an unrunnable spec; plain-JSON everywhere; and the loop that matters —
running a saved system records the entry it came from, capturing it after it drifts files
a *revision* of that entry with the running system re-pointed at the new version, and
capturing one that has not changed adds nothing at all. The site split is tested from both
ends: a caller cannot launder a design change through it, a rack captured back out of a
sandbox reports the fault somebody injected and *not* the weather it was standing in, and
a sandbox system the library has never seen starts a record with the builder's defaults
rather than that sandbox's sky. One test walks the whole sandbox loop — place a saved
design, break it where you are standing, save what you found as its next version — and it
earns its place by having caught the stale-registry bug above rather than a hypothetical.

Full suite **482 pass**. The dashboard type-checks and builds.

### Backlog
- Comparing two arbitrary entries side by side; today the diff is always against a parent
  or against a spec you already hold.
- Attaching a validation run or a fleet outcome to an entry, so `validated` can point at
  *what* it was checked against rather than only recording that somebody says it was.
- Merging a change back up a lineage — today a fork diverges and stays diverged, which is
  honest but leaves the "we all fixed the same thing separately" case to a human.
- Import/export between two people's libraries is a JSON file and a content-addressed id;
  it works, but there is no conflict story beyond "the same content is the same entry".

## Component 18 — Multiplayer 🚧 (planned)

**Goal.** A CRM is multiplayer by definition; the substrate is single-player (one
optional API key, one dashboard, no accounts). Make a simulation something people work on
*together, across domains*.

- [ ] **Accounts, roles, and a shared workspace** — more than one person on the same twin,
  with a notion of who they are and what they do. Local-first: an instance on one machine
  or one LAN serves a whole team.
- [ ] **Role- and domain-based views onto one model** — the same system shown differently
  to different people: the battery engineer sees electro-thermal detail, the safety lead
  sees alarms and margins, operations sees fleet health. One model, many legible faces.
  This reuses Component 16's domain lenses rather than inventing a second vocabulary.
- [ ] **Sharing and annotation** — comments on a model, and a way for a domain-A person to
  hand a domain-B person a view they can actually read.
- ⏸️ **Public share links to a live twin** — deferred with the hosting work; a link is
  only shareable once there is somewhere to host it.

## Component 19 — Breadth from the community 🚧 (planned)

**Goal.** Reach "simulate everything" without personally building every domain — and
relieve the "depth forever" pressure where breadth only ever means *another physics
component you write*.

- [ ] **A contribution path for physics components** — the plumbing already exists (the
  standalone-library shape, the optional dashboard-module slot); make it a documented,
  first-class way for others to add a domain.
- [ ] **A local component catalog** — discover and install community physics parts from a
  plain manifest, so the LFP curves, the sodium-arc spectra, and the next domain family
  come from the people who know them best. Git-and-a-file, not a service.
- ⏸️ **A hosted marketplace/registry** — deferred with the hosting work.

---

# Phase 2.1 — the world outside the model (in parallel)

Phase 2 asks whether somebody who did not build a model can understand it, reuse it, and
work on it with others. Phase 2.1 asks a question that sits beside that one rather than
after it:

> **Phase 1 asked "is the physics faithful?" Phase 2 asks "can someone else understand
> it?" Phase 2.1 asks "does the model know where it is standing?"**

Until now it did not. A rack had an ambient temperature somebody typed, a cable had a
length somebody estimated, a lighting design had a room somebody measured off a drawing,
and a weather source had coordinates somebody looked up — four numbers, four chances to be
wrong, and no way for anyone downstream to tell which had been measured and which had been
remembered.

The precedent is Component 11. Weather was not a new physics component; it was the
recognition that the environment a system sits in is *already described somewhere*, and
that reading it beats asking somebody to type it. A building is described somewhere too,
in far more detail, in a file the project already has — and it answers all four questions
at once.

This runs as its own track because it is orthogonal to the mission layer. Nothing in
Components 15–19 needs it, and it needs nothing from them.

## Component 20 — The building ✅ (v0.19)

**Goal.** Import somebody else's BIM model as a 2D layout that every other component can
simulate against, and that the 3D sandbox can be walked through — coupled the way weather
is coupled, through the terms the models already had.

`simura.space` is a reusable, domain-agnostic package: a building file in, a **floor plan**
out. No new dependencies — IFC, gbXML and DXF are parsed in pure Python, for the same
reason every texture in the sandbox is drawn in code. See [the building](space.md).

**The commitment it is built on: an import declares what it could not read.** Every
importer fills in — it picks 2.7 m, it assumes millimetres, it skips the entity and moves
on — and that is correct. Doing it *silently* is not, because the guess becomes
indistinguishable from a measurement one function call later, and a lux figure somebody
designs against then rests on it. So every value the importer supplied rather than read is
recorded with the basis it came from, and the couplings carry that through: a lighting
design for a room whose ceiling height was assumed says so, next to the number. It is
Component 16's commitment (attributed, not asserted) and Component 17's (computed, not
claimed) applied to the one place a twin meets somebody else's file.

- [x] **The canonical floor plan** — one small JSON document: georeference, levels, spaces
  with real polygons, walls with axis and thickness, openings, and a fidelity record.
  Metres always; the source unit recorded, because a factor-of-1000 error is the
  characteristic BIM failure. Content-hashed id, so a re-imported model is a *new* plan
  rather than a silent replacement of the old one.
- [x] **Importers, all pure Python** — IFC STEP (the 2D-relevant subset: spaces, walls,
  storeys, site, units, and the composed placement chain), gbXML, ASCII DXF, plus a saved
  plan and a generated example building. An optional `simura[bim]` extra runs the same job
  through `ifcopenshell` for models whose geometry the subset declines to guess about —
  optional exactly as SciPy is for `.mat` datasets.
- [x] **Occupancy classification** — a room is what it is *for*, onto the vocabulary
  `simura.lights` already speaks, from the most structured source available and with its
  basis recorded. It refuses rather than guesses: defaulting is how a plant room ends up
  designed to 500 lux.
- [x] **Weather coupling** — a georeferenced model configures its own `open_meteo` source,
  and carries true north, which decides which facade takes morning sun. Importing a
  building configures the sky over it with nothing typed in.
- [x] **Lights coupling** — every room becomes a `recommend_lamp` call with its real
  extents and its own task target, and a whole-building installed-power rollup. Plus a
  genuine physics improvement: `Layout(outline=...)` solves the illuminance field over a
  room's **real polygon**, masking points outside it, so an L-shaped room stops being lit
  as its bounding box (54 lux and U0 0.66 became 68 lux and U0 0.80 on the same fittings —
  a fifth of the "room" was never floor).
- [x] **Wires coupling** — cable length *computed* from the building: the drop to the tray,
  the shortest path through the rooms and the openings that join them, the drop back down,
  and stated slack. The run reports its legs, so the total is checkable, and the rooms it
  crossed, so it is derated for the hottest one — a conductor is rated by its worst metre.
- [x] **Batteries coupling** — `SystemSpec.space`, the same two-field shape as `weather`,
  because it answers the neighbouring question: weather says what the sky is doing, the
  room says whether the sky reaches the equipment. Standing indoors *drops* the weather
  source rather than damping it, which is the truthful model and needs no new coefficient.
  Same rack, same 34 °C day: 22.7 °C hottest cell in a conditioned office, 39.7 °C in an
  unconditioned plant room.
- [x] **`space` added to the library's site allowlist** — which room a rack was put in says
  nothing about the rack, so it must not travel as a design change. Without it, dropping a
  saved design into an imported building would report "space: none → gbxml #412" as
  something somebody has to justify.
- [x] **Two model cards** (`twin.space`, `twin.routing`) — the enforced coverage check
  means a new parameter surface fails the build until it is explained, which is how the
  building layer arrived legible rather than as a second undocumented vocabulary.
- [x] **`/api/space/*`, all pure compute** — the client holds the plan and posts it back,
  as it does for `/api/wires/network`. A floor plan is an artifact somebody keeps, not a
  session on a server. Only the import itself needs the file.
- [x] **Dashboard: a Building section** — import a model, draw the plan, and show the
  fidelity record *beside* it, because showing one without the other is showing half the
  answer. Click a room for its lighting design; click two points to trace a cable.
- [x] **The world walks the same plan** — the sandbox extrudes the identical floor-plan
  document into walls and rooms rather than importing a mesh, so the building you walk
  through and the building the lighting planner designed for cannot disagree.

### What is deliberately not in it

- **It is a 2D layout.** No ceiling voids, no structure, no services, and no risers other
  than where two storeys' rooms overlap in plan.
- **It does not validate the model against the building as built.** A plan is as right as
  the file is, and nothing here can tell you whether the file is right.
- **Routing is room-to-room through openings.** Not around furniture, structure or other
  services.

### Where it could go next

- [ ] **Round-tripping** — write a lighting design or a cable schedule back out as IFC or
  gbXML, so the result of a simulation lands in the model it came from.
- [ ] **Re-import as a diff** — a changed model is already a *new* plan with a new hash;
  the missing half is computing what moved between two plans, which is Component 17's
  machinery pointed at geometry rather than at specs.
- [ ] **Occupancy and schedules** — gbXML carries them and nothing reads them yet; they
  are what would let a lighting design be simulated over a working day rather than at an
  instant.

---

### What "done" looks like for Phase 2

A person who has never written a line of simulation code opens Simura, is handed a system
someone else built, understands what it is doing and why without becoming an expert in it,
changes something, breaks it on purpose to learn, and leaves a note the next person will
find. When that is true, "anybody can simulate" is no longer a mantra — it is the product.

---

## Deferred — hosting & deployment

**Why deferred:** the project has no hosting budget. Every item here needs a paid,
always-on service — a cluster, a managed database, a public domain, a registry — that no
one is funding, and none of them make the software better on the machine of the person
running it; they only change *where* it runs. So they are parked, in full, until there is
both a reason and a means to run infrastructure.

**Rule this imposes on the rest of Phase 2:** hosting is never a prerequisite. Anything
that would only work once deployed is either redesigned to work locally or moved to this
list. Components 15–19 are written to that rule.

- [ ] **Zero-install, hosted Simura** *(was Component 15)* — reach a live twin in a
  browser with no `pip` and no Docker.
- [ ] **Helm charts / Kubernetes manifests** *(was the Component 7 backlog)* — the
  deployment work Component 15 was going to absorb.
- [ ] **A public demo instance** with seeded systems, and a landing page that points at it.
- [ ] **Public share links to a live twin** *(was Component 18)* — hand someone a URL, not
  a `docker compose` command.
- [ ] **A hosted component marketplace/registry** *(was Component 19)* — the served half of
  the catalog. The local, manifest-driven half stays in Component 19.
- [ ] **Multi-tenant hardening** — the isolation, quotas and abuse controls a shared public
  instance would need, which a laptop or a team LAN does not.
- [ ] **Managed TimescaleDB / object storage** for anything the above persists.

None of these block a single checkbox in Components 15–19.
