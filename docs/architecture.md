# Architecture

Simura is a physics-based digital-twin **platform** built from independent
simulation **components**. Each component is a self-contained physics library;
they share one framework — a twin core (REST + WebSocket API over MQTT +
TimescaleDB), a live dashboard, hardware connectors, and a validation approach.

## Guiding principles

1. **Depth first, then breadth.** A component earns trust by being faithful before
   the next one is started, so each is built out deeply and left runnable + tested
   before Simura grows sideways. Breadth comes from *adding* components, never from
   thinning any one of them into a shallow "generic platform."
2. **Each component is an independent physics library.** `simura.sim` (batteries),
   `simura.wires` (conductors) and `simura.weather` have **no** cross-component
   dependencies — that independence is what lets them be reused or composed
   freely, and unit-tested with no infrastructure.
3. **A stable telemetry contract is each component's spine.** Everything
   downstream of the battery component consumes `PackTelemetry`; the wire
   component's is `WireTelemetry`. Nothing downstream reaches past the contract, so
   the physics behind it can evolve freely.
4. **The simulator and the twin are separate things.** A simulator *is* a stand-in
   physical asset. The twin ingests telemetry — it must not care whether that came
   from the simulator or real hardware. This is what lets Component 6 (real BMS
   connectors) drop in without rewrites.

## Build order

Simura is built one component at a time (see the [roadmap](roadmap.md)). The
sections below trace that order. **Components 1–7** built out the **Batteries**
component together with the shared framework (twin core, dashboard, analytics,
connectors, fleet). **Components 8–11** extended batteries — validation against
open datasets, a system [builder](builder.md), fleet [lifecycle](dashboard.md)
control, and [weather](weather.md) coupling — each documented on its own page.
**Component 12** is the first *second* component: [Wires](wires.md), covered at
the end of this doc.

## The Batteries component

## Component 1 — Simulator (implemented)

```
                 ┌─────────────────────────────────────────────┐
                 │                 Simulator                    │
  LoadProfile ──▶│  current(t, V)                               │
                 │        │                                     │
   Fault[] ─────▶│  accumulate(faults) ──▶ FaultEffect          │
                 │        │                     │               │
                 │        ▼                     ▼               │
                 │   BatteryPack.step(I, dt, effect)            │
                 │   • solve parallel node voltages             │
                 │   • coulomb counting (SoC)                   │
                 │   • RC polarization                          │
                 │   • lumped thermal                           │
                 │        │                                     │
                 │        ▼                                     │
                 │   snapshot() ──▶ PackTelemetry ──────────────┼──▶ (consumer)
                 └─────────────────────────────────────────────┘
```

### Modules (`src/simura/sim/`)

| File | Responsibility |
|------|----------------|
| `config.py` | `CellParams`, `PackConfig`, `SimConfig` — serializable description of *what* to simulate (no state). |
| `ocv.py` | OCV–SoC curve (NMC default), pluggable per chemistry. |
| `pack.py` | `BatteryPack` — vectorized `(series, parallel)` state + the integrator. The physics lives here. |
| `faults.py` | `Fault` base + implementations; `FaultEffect` accumulator so faults compose. |
| `profiles.py` | Load profiles mapping `(t, voltage) → pack current`. |
| `telemetry.py` | `PackTelemetry` / `CellTelemetry` contract + `snapshot()`; sensor biases applied here. |
| `simulator.py` | `Simulator` — a generator yielding one telemetry frame per step. |

### State vs. config vs. output

- **Config** (dataclasses) is inert and serializable — store it, version it, ship it.
- **State** lives in `BatteryPack` as NumPy arrays and is stepped in place.
- **Output** is `PackTelemetry` — the only thing that crosses the boundary.

At construction, the battery state is solved at zero external pack current
using the same parallel-node equations as a simulation step, without advancing
charge, polarization or temperature. Each parallel group starts at one terminal
voltage; only the series module voltages are summed for the pack. Imbalanced
cells can have nonzero balancing currents even while their module's net current
is zero. These initial diagnostics are available before a load profile first
reads the pack voltage.

### Why NumPy arrays, not `Cell` objects

A rack is hundreds of cells. Holding state as `(series, parallel)` arrays lets
the whole pack step in one vectorized pass and keeps the parallel-group solve a
few lines of linear algebra instead of an object graph.

## Component 2 — Twin core (implemented)

```
  publisher (simura.publisher)                 twin core (simura.twincore)
  ┌───────────────────────────┐   MQTT          ┌──────────────────────────────┐
  │ Simulator.run() generator │   simura/     │ ingest loop (aiomqtt)         │
  │  → envelope per frame     │──telemetry/{id}─▶│   → store.insert_* (asyncpg) │
  │  → retained config once   │──config/{id}────▶│   → live-state cache         │
  └───────────────────────────┘   (QoS 1)        │   → ws broadcast             │
                                                  │        │            │        │
                                                  │        ▼            ▼        │
                                                  │  TimescaleDB    FastAPI      │
                                                  │  (hypertables)  REST + WS ───┼─▶ clients
                                                  └──────────────────────────────┘
```

The generator seam from Component 1 paid off exactly as designed: the same
`PackTelemetry` that printed a table now serializes into an MQTT envelope with no
change to the physics core.

### Modules

| Location | Responsibility |
|----------|----------------|
| `transport/topics.py` | MQTT topic conventions shared by publisher and twin core. |
| `publisher/run.py` | Drives a `Simulator`, publishes retained config + per-frame telemetry. Stands in for a real BMS gateway. |
| `twincore/settings.py` | Env-based (`SIMURA_*`) 12-factor config. |
| `twincore/store.py` | `TimescaleStore` — asyncpg pool, schema init, writes, and history/latest queries. |
| `twincore/ingest.py` | MQTT subscribe loop → persist → cache → broadcast, with auto-reconnect. |
| `twincore/state.py` | In-memory latest frame per system + WebSocket fan-out. |
| `twincore/api.py` | REST (`/api/systems`, `/state`, `/cells`, `/history`) + WS (`/ws/systems/{id}`). |
| `twincore/main.py` | App factory; lifespan wires store + ingest task together. |

### The contract that makes hardware swappable

The twin core only ever sees the MQTT **envelope** (`{system_id, timestamp,
telemetry}`) — never the simulator. Component 6 (real connectors) just needs to
publish the same envelope from a real BMS, and the twin core is unchanged.

## Component 3 — Live dashboard (implemented)

A React + TypeScript + Tailwind SPA (`dashboard/`), built with Vite and charted
with Recharts. In production nginx serves the static bundle and reverse-proxies
`/api` and `/ws` to the twin core, so the browser sees a single origin (no CORS);
in dev, Vite's proxy does the same and the twin core also enables CORS.

```
  dashboard/src/
    api/          types.ts · client.ts (REST) · useTelemetry.ts (WS + history seed)
    lib/          color.ts (ramps) · status.ts (thresholds) · events.ts (timeline)
    components/    TopBar · HealthBanner · StatTile · CellHeatmap · TrendChart · EventLog
    App.tsx       fetch systems → subscribe → compose the layout
```

Design follows the data-viz design system: reserved status colors (never
color-alone — always icon + label), an **absolute** thermal scale for the heatmap
so red means genuinely hot, **relative** ramps for voltage/SoC so imbalance shows,
and single-series trend charts (never a dual axis). The dashboard consumes only
the twin core's public API — the same contract real hardware would feed.

## Component 4 — Anomaly detection (implemented)

```
  detector (simura.detect)                    twin core
  ┌────────────────────────────┐  simura/     ┌───────────────────────────┐
  │ subscribe telemetry/+      │  anomaly/{id}  │ ingest anomaly/+          │
  │ AnomalyEngine per system   │───────────────▶│  → anomaly_summary (TSDB) │
  │  peer-consensus robust z    │  (QoS 1)       │  → anomaly live cache     │
  │  + EWMA persistence         │                │  → ws broadcast           │
  └────────────────────────────┘                └───────────────────────────┘
```

The detector consumes the same public telemetry stream any client sees and
produces a derived one — no privileged access, exactly like a real analytics
service. The **engine is a pure library** (`simura/detect/engine.py`), so it is
unit-tested against the simulator's healthy/fault scenarios with no infra, and
Component 5 can reuse it in batch over history.

### Why peer-consensus

Every cell in a pack sees the same load, so its siblings are a free, always-valid
baseline. For each metric the engine takes the pack **median** as consensus and
the **MAD** as robust spread (a single bad cell can't skew either), scores each
cell by robust z in the bad direction (hot / drained / off-voltage), and smooths
with an EWMA so only *sustained* deviation flags. The internal-short cell trips
"critical" while still ~9 °C below its temperature limit; a healthy pack stays
under score 1.2. Deviation *floors* (the main false-positive defense) set the
scale of a meaningful per-metric deviation and are calibrated in `AnomalyConfig`.

### On the wire

Anomaly frames are a distinct envelope (`{system_id, timestamp, anomaly}`) sharing
the per-system WebSocket; the dashboard tells them apart by shape. Only the
pack-level **summary** is persisted (score/flagged/worst cell) — the full per-cell
report lives in the live cache and is served from `/anomaly`.

## Component 5 — Diagnosis, SoH, RUL & safety (implemented)

The `analytics` service now runs both engines per frame:

```
  telemetry ─▶ AnomalyEngine ─▶ anomaly ─┐
                                          ├─▶ AssessmentEngine ─▶ assessment
              (same frame, aligned) ──────┘   (diagnosis + SoH + RUL + safety)
```

`simura.health` is a pure library, unit-tested against the simulator's five
fault scenarios:

| Piece | Responsibility |
|-------|----------------|
| `health_engine.py` | Online **DCIR → SoH** (`(OCV(SoC)−V)/I` vs nominal) and heating-rate → **time-to-critical**. |
| `diagnosis.py` | **Fault fingerprinting** over the anomaly z-scores + health features, checked in priority (safety) order. |
| `assessment.py` | Combines them into an `AssessmentReport` with a pack **safety state**. |

### Why fingerprints, not a black box

We have no labeled field data — only what the simulator produces — and an
operator needs to trust the call. So each fault is a legible rule over features
that already mean something: *hot AND draining* = internal short; *hot WITHOUT
drain* = cooling loss; *DCIR above peers* = resistance growth; *one signal off
with no physical corroboration* = sensor fault; *fast, accelerating heat* =
runaway. The discriminator between a short and a cooling fault is the mere
*presence* of extra self-discharge (small in a cycling pack, but real and
one-directional), gated by "hot" so a healthy cell is never called a short.

### Contract & storage

Assessment frames are their own envelope (`{system_id, timestamp, assessment}`)
on the shared WebSocket. Only the summary (SoH, fault, confidence, safety,
time-to-critical) is persisted; the full per-cell health report lives in the live
cache behind `/assessment`.

## Component 6 — Real-hardware connectors (implemented)

```
  device (real BMS or devsim)     simura.connect
  ┌───────────────────────┐       ┌──────────────────────────────────────┐
  │ Modbus registers      │──────▶│ read_frame() ─▶ SourceFrame           │
  │ OPC-UA nodes          │──────▶│                    │                  │
  │ foreign MQTT JSON     │──────▶│      build_telemetry(DeviceMapping)   │
  └───────────────────────┘       │                    │                  │
                                   │            PackTelemetry ─▶ envelope ─┼─▶ simura/telemetry/{id}
                                   └──────────────────────────────────────┘
```

The decode core (`decode.py` + `frame.py`) is protocol-independent: a connector's
only job is to produce a `SourceFrame` of raw named signals; the mapping handles
unit scaling and the sparsity gap (a real BMS reports per-cell voltage + a few
temperatures + pack-level current/SoC, so per-cell current/SoC are derived).

| Piece | Responsibility |
|-------|----------------|
| `frame.py` / `decode.py` | `SourceFrame` + `DeviceMapping` → `PackTelemetry`. |
| `base.py` | Publishing + retained config; `PollingConnector` loop. |
| `modbus.py` / `opcua.py` / `mqtt_bridge.py` | The three protocol front-ends. |
| `config.py` | Build a connector from a YAML/JSON config. |
| `devsim.py` | Simulated Modbus/OPC-UA BMS devices for demos and tests. |

Because everything funnels through the same envelope, the twin core, analytics,
and dashboard are **unchanged** — a system fed by Modbus is indistinguishable
from the simulator's, except where the real sensor set is coarser (per-module
temperature, pack SoC), in which case the diagnosis honestly reflects what can
and cannot be observed.

## Component 7 — Fleet scale + auth (in progress)

The twin core has always ingested the whole fleet (the ingest loop subscribes to
wildcard topics); Component 7 makes the fleet *observable and secured* as a
whole.

```
  live caches (per system)          simura.fleet (pure)        API
  ┌───────────────────────┐         ┌─────────────────────┐
  │ telemetry / anomaly /  │         │ roll_up_system(...) │
  │ assessment envelopes   │────────▶│   → status + reason │────▶ GET /api/fleet
  │ (LatestState.as_dict)  │         │ build_fleet(...)    │      {summary, systems}
  └───────────────────────┘         │   → summary + order │
   store.list_systems() ───────────▶└─────────────────────┘
```

| Piece | Responsibility |
|-------|----------------|
| `fleet/levels.py` | Status thresholds (temp/imbalance/anomaly/safety) — a Python mirror of the dashboard's `status.ts`, the single source of truth for "critical". |
| `fleet/summary.py` | `roll_up_system` / `build_fleet` — pure functions over the live-cache envelope dicts + registry rows; per-system status + reason, and a fleet summary (counts, worst system, aggregate power, alarms). |
| `twincore/auth.py` | Optional API-key guard: `extract_key` (Bearer / `X-API-Key` / `?api_key=`), constant-time `is_authorized`, and the `require_api_key` dependency. |

Like every prior component, the interesting logic is a **pure library** taking
plain dicts — the exact envelopes the live caches already hold — so the rollup is
unit-tested against the simulator's fault scenarios with no DB or broker, and
`/api/fleet` is just wiring.

**Auth** is off by default (`SIMURA_API_KEY` empty), keeping the demo
frictionless. When set, the REST router is guarded by the `require_api_key`
dependency and the WebSocket self-checks the key on handshake (closing with 1008
if it's wrong); `/health` is mounted directly on the app so liveness probes stay
open either way.

### What's next (remaining Component 7)

The docs site (mkdocs), contribution guide, and expanded examples have landed;
Helm/K8s manifests remain. See the [roadmap](roadmap.md).

## The Wires component

## Component 12 — Wires (implemented)

The first *second* component: conductors, not batteries. `simura.wires` is a
reusable, battery-agnostic library with the same shape as the battery side — a
config-vs-state split, a stable telemetry contract, and pure planning logic — but
it models a wire's electro-thermal behaviour and answers the questions an engineer
asks before pulling cable.

```
   WireSpec ──▶ Wire (state: temperature)          evaluate_run / recommend_gauge
   (config)      • R(T) = ρ₂₀·(1+α·(T−20))·L/A  ─▶   • ampacity / drop / temp check
                 • ΔV = I·R,  loss = I²R              • smallest adequate gauge
                 • dT/dt = (I²R − k_cool·ΔT)/C_th
                       │
                       ├─▶ WireSimulator ─▶ WireTelemetry   (transient, generator)
                       ├─▶ WireNetwork.solve() ─▶ nodal analysis (multi-node DC)
                       └─▶ validation ─▶ % error vs published DC-resistance standards
```

### Modules (`src/simura/wires/`)

| File | Responsibility |
|------|----------------|
| `wire.py` | `WireSpec` (serializable *what*) + `Wire` (temperature state + physics). |
| `catalog.py` | Conductor materials, AWG↔area, insulation classes, and off-the-shelf `WireType`s. |
| `telemetry.py` | `WireTelemetry` contract + `snapshot()`. |
| `faults.py` | Wiring faults (corrosion, loose joint, damage, ageing, ground fault) via the same `FaultEffect` accumulator as the battery side. |
| `profiles.py` / `simulator.py` | Current profiles and a `WireSimulator` generator (mirrors the battery `Simulator`). |
| `planning.py` | `evaluate_run` / `recommend_gauge` — the "is this run OK / what gauge?" checks, as a list of problems (never a crash). |
| `network.py` | `WireNetwork` — multi-node DC operating point by nodal analysis, iterating resistance ↔ temperature to a fixed point. |
| `validation/` | Validate predicted DC resistance against published standards (annealed copper, hard-drawn aluminium) or a user CSV — the conductor analog of the battery [validation](validation.md) pipeline. |

### How it plugs into the framework

The wire library is **pure compute** — it has no running "asset" to stream, so it
doesn't touch MQTT or the database. Instead the twin core exposes it over
stateless endpoints (`/api/wires/catalog`, `/evaluate`, `/recommend`, `/network`,
`/validation/*`), and the dashboard's **Wires** component (a wiring planner and a
validation view) calls them directly. Same FastAPI service, same dashboard shell,
same optional API-key guard as the battery component — the framework is shared,
the physics is the component's own.

