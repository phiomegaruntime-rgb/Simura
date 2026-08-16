# Simura Roadmap

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

