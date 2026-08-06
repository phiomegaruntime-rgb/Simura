# CellTwin by Simura

**An open, physics-based digital twin for battery energy storage systems (BESS).**

_CellTwin is the first product of **Simura** — building software digital-twin
solutions across industries._

CellTwin simulates a battery — from a single cell to a full rack — with real
electro-thermal dynamics, cell-to-cell imbalance, and *injectable faults*, then
streams the same telemetry a real Battery Management System (BMS) would. Clone
it and you have a living battery on your laptop: no hardware, no lab, no fire.

> ⚠️ Early-stage hobby project with industrial ambitions. Components 1 (physics
> simulator), 2 (twin core: MQTT + TimescaleDB + REST/WebSocket API), 3 (live
> React dashboard), 4 (peer-consensus anomaly detection with early warning), 5
> (fault diagnosis, state-of-health, RUL & safety), and 6 (real-hardware
> connectors: Modbus / OPC-UA / MQTT) are done and tested, as are Component 8
> (validation against open battery datasets), Component 9 (build your own
> system), Component 10 (run/pause/resume/delete systems from the fleet), and
> Component 11 (weather-driven environmental coupling, as a reusable package).
> Component 7 (fleet rollup + optional API-key auth) is underway. See the
> [roadmap](docs/roadmap.md).

## Why

Battery health and safety is one of the most valuable digital-twin use cases in
energy today — state-of-charge, state-of-health, and thermal-runaway early
warning are worth real money and prevent real fires. But you can't learn or
prototype on a real 1 MWh rack. CellTwin gives everyone a physically faithful,
fully controllable battery to build diagnostics, dashboards, and ML on top of.

## Quick start

**The simulator alone** (just needs numpy):

```bash
pip install -e .
python examples/run_basic.py            # healthy pack, daily charge/discharge cycle
python examples/run_basic.py --fault    # inject an internal short + thermal runaway
```

**The full twin** (broker + TimescaleDB + twin core + a simulated asset):

```bash
docker compose -f deploy/docker-compose.yml up --build
```

Then open:

- **Dashboard** — <http://localhost:8080> — opens on a **fleet overview** (every
  system rolled up to one status, worst-first); click a card to drill into that
  pack's live cell heatmap, trends, and fault timeline.
- **API docs** — <http://localhost:8000/docs>

```bash
curl localhost:8000/api/fleet                         # whole-fleet rollup
curl localhost:8000/api/systems                       # twin registry
curl localhost:8000/api/systems/bess-01/state         # latest frame
curl "localhost:8000/api/systems/bess-01/history?minutes=10&bucket_s=5"
# live stream:  ws://localhost:8000/ws/systems/bess-01
```

**Optional API key.** Auth is off by default. Set `CELLTWIN_API_KEY` on the twin
core and every `/api/*` route and the WebSocket require it (`/health` stays open
for probes):

```bash
curl -H "X-API-Key: $CELLTWIN_API_KEY" localhost:8000/api/fleet
# or:  Authorization: Bearer <key>   ·   ws://…/ws/systems/bess-01?api_key=<key>
```

For the whole stack, set it once — nginx injects the key on the dashboard's
`/api` + `/ws` upstream hop, so the browser never handles it:

```bash
CELLTWIN_API_KEY=your-secret docker compose -f deploy/docker-compose.yml up --build
```

To develop the dashboard with hot reload (against a running twin core):

```bash
cd dashboard && npm install && npm run dev   # http://localhost:5173
```

**Connect real hardware** — point a connector at a device with a config file (no
code). To try it without hardware, run a simulated Modbus BMS first:

```bash
python -m celltwin.connect.devsim --protocol modbus --port 5020
python -m celltwin.connect --config examples/connectors/modbus.yaml
```

Connectors for **Modbus TCP**, **OPC-UA**, and an **MQTT bridge** (foreign JSON
schema) all emit the same telemetry envelope, so the twin treats real hardware
and the simulator identically. The default `docker compose` stack includes a
Modbus device + connector as the `bess-modbus-01` system.

```python
from celltwin.sim import Simulator, PackConfig, ChargeDischargeCycle, InternalShort

sim = Simulator(
    PackConfig(series=12, parallel=2, initial_soc=0.9),   # 12S2P NMC pack
    profile=ChargeDischargeCycle(discharge_a=20, charge_a=15),
    faults=[InternalShort(cell=(3, 0), r_short_ohm=2.0, start_s=600)],
)
for telemetry in sim.run():          # one PackTelemetry per timestep
    print(telemetry.pack_soc, telemetry.max_temp_c)
```

**Validate against real battery data** — check the physics against open,
publicly-licensed datasets (NASA, Oxford, CALCE, Sandia, Stanford–MIT–TRI, …).
CellTwin ships a *catalog* (with licenses + citations) and format loaders, plus a
bundled **synthetic** sample so it runs offline:

```bash
python -m celltwin.validate --list                       # browse the catalog
python -m celltwin.validate --dataset demo-synthetic --fit   # offline demo
python -m celltwin.validate --dataset oxford-degradation --file cell1.mat --fit
```

The right OCV curve is picked per chemistry (NMC / LFP / LCO / NCA). Or upload your
own download straight into the dashboard's **Validation** tab and see the
measured-vs-model overlay in the browser.

**Build your own system** — design a battery system (chemistry, topology, load
profile, faults), preview it offline, then stream it into the twin:

```bash
python -m celltwin.builder --example > my-system.json   # edit it (or use the Build tab)
python -m celltwin.builder --preview my-system.json      # SoC, peak temp, energy, safety
python -m celltwin.publisher --spec my-system.json --speed 10 --loop   # go live
```

## What's modeled

- **Electrical** — 1st-order Thevenin equivalent circuit (OCV–SoC curve, ohmic +
  polarization resistance) per cell, with *exact* parallel-group current sharing.
- **Thermal** — lumped per-cell heat generation and cooling to ambient.
- **State of charge** — coulomb counting with charge/discharge efficiency.
- **Imbalance** — manufacturing spread in capacity, resistance, and initial SoC.
- **Faults** — internal short, resistance growth, cooling loss, thermal runaway,
  sensor drift — each targetable to any cell, on any schedule, and composable.
- **Anomaly detection** — peer-consensus robust z-scores flag a cell drifting from
  its siblings *before* it crosses any absolute limit (early warning).
- **Diagnosis & prognosis** — classifies the fault type (internal short vs. cooling
  loss vs. resistance growth vs. sensor fault vs. thermal runaway), estimates
  state-of-health and time-to-critical, and raises a safety alarm.
- **Validation** — replays real open-dataset current through the model and reports
  terminal-voltage error (RMSE/MAE), so the physics is checked against measured
  cells rather than taken on faith. See [docs/validation.md](docs/validation.md).
- **System builder** — design your own battery system (chemistry, topology, load
  profile, faults) as a spec, preview it offline, then stream it live with one
  command. See [docs/builder.md](docs/builder.md).
- **Lifecycle control** — the twin core can run simulations itself and
  **start / pause / resume / delete** them from the fleet; real-time feeds are
  ingest-only and Delete-able. Choose sim or real-time per system.
- **Weather** — drive a pack's ambient temperature, wind cooling and solar heat
  load from real ([Open-Meteo](https://open-meteo.com), no API key) or synthetic
  weather. Built as a **reusable, battery-agnostic package** (`celltwin.weather`).
  See [docs/weather.md](docs/weather.md).

## Documentation

Full docs live under [`docs/`](docs/) and build into a site with mkdocs:

```bash
pip install -e ".[docs]"
mkdocs serve            # http://localhost:8000
```

Start with [Getting started](docs/getting-started.md), the
[architecture](docs/architecture.md), or the runnable
[examples](examples/README.md).

## Roadmap

Physics simulator ✅ → twin core + time-series store → live dashboard → anomaly
detection → diagnosis / remaining-useful-life / safety → real-hardware
connectors (MQTT/OPC-UA/Modbus) → fleet & deployment. Full detail in
[docs/roadmap.md](docs/roadmap.md); design in
[docs/architecture.md](docs/architecture.md).

## Contributing

Issues and PRs welcome. Good first areas: new cell chemistries (LFP OCV curves),
new fault types, and load profiles from real duty cycles — each slots into an
[example](examples/README.md). See [CONTRIBUTING.md](CONTRIBUTING.md). Licensed
under **Apache-2.0**.
