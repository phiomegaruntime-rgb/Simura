# Simura

**An open, physics-based digital-twin platform — built component by component.**

Simura models real physical systems from first principles and serves them as
live digital twins. Each **component** is an independent, physically faithful
simulation; they share one framework — a twin core (REST + WebSocket API), a live
dashboard, and a "replay against real reference data" validation approach — so a
new component plugs its own physics into machinery that already exists.

Four components exist today:

- **🔋 Batteries (BESS)** — the flagship. Simulate a battery from a single cell to
  a full rack with real electro-thermal dynamics, cell-to-cell imbalance, and
  *injectable faults*, streamed as the same telemetry a real Battery Management
  System (BMS) would emit — then detect anomalies, diagnose faults, and estimate
  state-of-health across a whole fleet.
- **🔌 Wires** — a reusable, battery-agnostic conductor library: resistance,
  voltage drop, ohmic loss and electro-thermal heating, a catalog of real wire
  types, a wiring planner (ampacity / voltage-drop / gauge sizing), a multi-node
  network solver, and validation against published conductor standards.
- **🏢 Building** — import somebody else's BIM model (IFC, gbXML, DXF) as a 2D
  floor plan the other three simulate against: rooms with real outlines and a
  purpose, walls, doorways, and where on Earth the building stands. Every value
  the importer had to assume is recorded with the basis it came from, so no
  number downstream silently rests on a guess.
- **💡 Lights** — every light source from an LED to a sodium arc, simulated from
  its spectrum up. Planck's law and the CIE observer *compute* each lamp's
  efficacy rather than looking it up, so a dimmed filament goes orange as its
  efficacy collapses, and a cold fluorescent tube goes dim while a cold LED goes
  bright. Plus a lighting planner, an illuminance-field solver, daylight-linked
  controls, and validation against published photometry **and the live sky**.

Clone it and you have living hardware on your laptop: no lab, no rig, no fire.

## Why

The market is already full of simulation platforms, so why build another? Because they
are almost all **deeply domain-specific**, and that quietly puts everyone at a
disadvantage the moment they try to collaborate: each person has to become a
"learn-everything" generalist just to be useful, and when the project ends the next one
starts again from zero.

Simura's mission is to fix that. Think of how a CRM created a common ground between a
company and its customers; Simura is meant to be a **CRM for simulations** — one place
where people from different domains get familiar with a simulation without having to
become an expert in all of it. The goal is simple: **anybody can simulate.**

Getting there runs in **two phases**. **Phase 1 (largely done)** builds the un-fakeable
part — a faithful, validated physics substrate — because "anybody can simulate" is
worthless on top of physics no one trusts. A physics-based digital twin (a software model
you can run, break, and learn from without touching real hardware) is one of the
highest-value tools in industrial software, and Simura makes them **open and
approachable**: the core of every component is pure Python + NumPy, unit-tested with no
broker, database, or hardware required. Batteries came first because battery health and
safety is worth real money and prevents real fires — you can't safely prototype on a real
1 MWh rack. But the architecture is deliberately **general**: each component (batteries,
wires, and lights today; more later) is an independent physics library that plugs into
the same twin core, dashboard, and validation approach.

**Phase 2 (in progress)** turns that substrate outward, which is where the mission
actually lives. Two pieces are built. A layer that lets a non-expert **get familiar**
with a model: ask what a running system is doing and why, in your own field's terms and
at whichever of three depths you want, and the answer is *computed* — Simura decomposes
the model's own governing equation at the operating point in front of you and builds the
sentence from whichever term actually won, so an explanation cannot drift away from the
physics it describes. And a **system library**, so a project inherits the last one
instead of starting from zero: saved systems carry the *reason* behind each choice and
the lineage back to what they were forked from, and — the same commitment again — what
changed between two systems is computed from the specs themselves, so the only thing
anybody types is why. Still to come: a five-minute first simulation, multiplayer
collaboration across domains, and community-contributed physics. See
[getting familiar](docs/explain.md), [the system library](docs/library.md) and the
[roadmap](docs/roadmap.md).

## Quick start

**A component's library alone** (just needs numpy):

```bash
pip install -e .

# Batteries
python examples/run_basic.py            # healthy pack, daily charge/discharge cycle
python examples/run_basic.py --fault    # inject an internal short + thermal runaway

# Wires
python examples/wire_planning.py        # check a run, size a gauge, solve a network
python examples/wire_thermal.py         # watch an undersized conductor overheat

# Lights
python examples/light_planning.py       # light a room, then see where the light falls
python examples/light_spectrum.py       # where efficacy comes from, and what dimming costs
python examples/light_weather.py        # photocells, daylight harvesting, cold tubes

# The library: memory that survives the project
python examples/inherit_a_system.py     # three engineers, one file, and why the numbers are the numbers
python -m simura.library --seed --list  # a library in one JSON file, no services

# The building: somebody else's BIM model, and what it tells the rest
python examples/import_a_building.py    # four simulations standing inside one file
python -m simura.space --demo --rooms-table --route 3,3.8 21,3.8
```

**The full twin** (broker + TimescaleDB + twin core + a simulated asset):

```bash
docker compose -f deploy/docker-compose.yml up --build
```

Then open:

- **Dashboard** — <http://localhost:8080> — opens on a landing of **component
  cards** (Batteries / Wires / Lights). Pick **Batteries** for the fleet
  overview (every system rolled up worst-first; click a card to drill into a
  pack's live cell heatmap, trends, and fault timeline), **Wires** for the wiring
  planner and conductor-model validation, or **Lights** for the lighting planner,
  lamp spectra and photometric validation ([docs](docs/lights.md)).
  **Building** imports a BIM model as a floor plan the other three simulate
  against ([docs](docs/space.md)), **Learn** explains every model in plain
  language ([docs](docs/explain.md)), and **Library** holds every saved system
  with the reasoning and lineage behind it ([docs](docs/library.md)).
- **API docs** — <http://localhost:8000/docs>

> First run after a rename or a DB name change? Postgres only initializes its user
> and database on a **fresh** volume, so wipe the old one once:
> `docker compose -f deploy/docker-compose.yml down -v` before `up`.

```bash
curl localhost:8000/api/fleet                         # whole-fleet rollup (batteries)
curl localhost:8000/api/systems                       # twin registry
curl localhost:8000/api/systems/bess-01/state         # latest frame
curl "localhost:8000/api/systems/bess-01/history?minutes=10&bucket_s=5"
curl localhost:8000/api/wires/catalog                 # wire component (pure compute)
curl localhost:8000/api/lights/catalog                # lights component (pure compute)
curl localhost:8000/api/library                       # saved systems, with a computed diff per row
# live stream:  ws://localhost:8000/ws/systems/bess-01
```

**Optional API key.** Auth is off by default. Set `SIMURA_API_KEY` on the twin
core and every `/api/*` route and the WebSocket require it (`/health` stays open
for probes):

```bash
curl -H "X-API-Key: $SIMURA_API_KEY" localhost:8000/api/fleet
# or:  Authorization: Bearer <key>   ·   ws://…/ws/systems/bess-01?api_key=<key>
```

For the whole stack, set it once — nginx injects the key on the dashboard's
`/api` + `/ws` upstream hop, so the browser never handles it:

```bash
SIMURA_API_KEY=your-secret docker compose -f deploy/docker-compose.yml up --build
```

To develop the dashboard with hot reload (against a running twin core):

```bash
cd dashboard && npm install && npm run dev   # http://localhost:5173
```

### Batteries: use the library directly

```python
from simura.sim import Simulator, PackConfig, ChargeDischargeCycle, InternalShort

sim = Simulator(
    PackConfig(series=12, parallel=2, initial_soc=0.9),   # 12S2P NMC pack
    profile=ChargeDischargeCycle(discharge_a=20, charge_a=15),
    faults=[InternalShort(cell=(3, 0), r_short_ohm=2.0, start_s=600)],
)
for telemetry in sim.run():          # one PackTelemetry per timestep
    print(telemetry.pack_soc, telemetry.max_temp_c)
```

**Connect real hardware** — point a connector at a device with a config file (no
code). To try it without hardware, run a simulated Modbus BMS first:

```bash
python -m simura.connect.devsim --protocol modbus --port 5020
python -m simura.connect --config examples/connectors/modbus.yaml
```

Connectors for **Modbus TCP**, **OPC-UA**, and an **MQTT bridge** (foreign JSON
schema) all emit the same telemetry envelope, so the twin treats real hardware
and the simulator identically. The default `docker compose` stack includes a
Modbus device + connector as the `bess-modbus-01` system.

**Validate the battery physics** against open, publicly-licensed datasets (NASA,
Oxford, CALCE, Sandia, Stanford–MIT–TRI, …). Simura ships a *catalog* (with
licenses + citations) and format loaders, plus a bundled **synthetic** sample so
it runs offline:

```bash
python -m simura.validate --list                       # browse the catalog
python -m simura.validate --dataset demo-synthetic --fit   # offline demo
python -m simura.validate --dataset oxford-degradation --file cell1.mat --fit
```

The right OCV curve is picked per chemistry (NMC / LFP / LCO / NCA). Or upload
your own download straight into the dashboard's **Validation** tab.

**Build your own battery system** — design chemistry, topology, load profile and
faults, preview it offline, then stream it into the twin:

```bash
python -m simura.builder --example > my-system.json   # edit it (or use the Build tab)
python -m simura.builder --preview my-system.json      # SoC, peak temp, energy, safety
python -m simura.publisher --spec my-system.json --speed 10 --loop   # go live
```

### Wires: plan and validate conductors

```python
from simura.wires import WireSpec, evaluate_run, recommend_gauge

evaluate_run(WireSpec(awg=12, length_m=20), current_a=15,
             system_voltage_v=12, round_trip=True)   # ampacity / drop / temp check
recommend_gauge(current_a=15, length_m=20, system_voltage_v=12, max_drop_pct=3)
```

```bash
python -m simura.wires --recommend --current 15 --length 20 --voltage 12 --max-drop 3
python -m simura.wires.validation --standard copper-annealed-20c   # vs a published standard
```

### Lights: design and validate lighting

```python
from simura.lights import Light, LightSpec, recommend_lamp

Light(LightSpec(lamp_type="inc-60-e27")).operating_point(0.5)   # dim it: 3 lm/W, 2183 K
recommend_lamp(length_m=12, width_m=9, task="office")           # lamp + count + alternatives
```

Every lamp's efficacy is computed from the spectrum it radiates, so the model
*predicts* the catalog rather than repeating it — and reports by how much it
missed:

```bash
python -m simura.lights --spectrum --lamp led-9-e27      # the SPD and what it is worth
python -m simura.lights --dim --lamp inc-60-e27          # what a dimmer really costs
python -m simura.lights.validation --all                 # vs published photometry
python -m simura.lights.validation --live --lat 51.5 --lon -0.13   # vs the live sky
```

## What's modeled

### Batteries component

- **Electrical** — 1st-order Thevenin equivalent circuit (OCV–SoC curve, ohmic +
  polarization resistance) per cell, with *exact* parallel-group current sharing.
- **Thermal** — lumped per-cell heat generation and cooling to ambient.
- **State of charge** — coulomb counting with charge/discharge efficiency.
- **Imbalance** — manufacturing spread in capacity, resistance, and initial SoC.
- **Faults** — internal short, resistance growth, cooling loss, thermal runaway,
  sensor drift — each targetable to any cell, on any schedule, and composable.
- **Anomaly detection** — peer-consensus robust z-scores flag a cell drifting from
  its siblings *before* it crosses any absolute limit (early warning).
- **Diagnosis & prognosis** — classifies the fault type, estimates state-of-health
  and time-to-critical, and raises a safety alarm.
- **Validation** — replays real open-dataset current through the model and reports
  terminal-voltage error (RMSE/MAE). See [docs/validation.md](docs/validation.md).
- **System builder** — design a battery system as a spec, preview it offline, then
  stream it live. See [docs/builder.md](docs/builder.md).
- **Lifecycle control** — the twin core runs simulations itself and
  **start / pause / resume / delete**s them from the fleet; real-time feeds are
  ingest-only. Choose sim or real-time per system.
- **Weather** — drive a pack's ambient temperature, wind cooling and solar heat
  load from real ([Open-Meteo](https://open-meteo.com), no API key) or synthetic
  weather, as a reusable package (`simura.weather`). See [docs/weather.md](docs/weather.md).

### Wires component

- **Conductor physics** — `R(T) = ρ₂₀·(1 + α·(T−20))·L/A`, voltage drop `I·R`,
  ohmic loss `I²R`, and a lumped electro-thermal node, with a catalog of real
  materials, gauges and insulation classes.
- **Wiring planner** — check a run against ampacity, voltage drop and the
  insulation's temperature rating, or size the smallest adequate gauge.
- **Network solver** — connect nodes with wire segments and solve the DC operating
  point by nodal analysis, iterating resistance ↔ temperature to a fixed point.
- **Validation** — check predicted DC resistance against published standards
  (annealed copper, hard-drawn aluminium) or your own measured-resistance CSV.
- **Reusable & battery-agnostic** (`simura.wires`) — knows conductors and
  electrical physics, not batteries. See [docs/wires.md](docs/wires.md).

### Lights component

- **Spectral physics** — Planck's law and the CIE 1931 observer give luminous
  efficacy, chromaticity and colour temperature from the spectrum a source
  actually radiates. Efficacy is never tabulated, so dimming, colour temperature
  and temperature derating all follow from one place.
- **Every source family** — thermal radiators (incandescent, halogen), solid state
  (LED, high-CRI LED, laser diode), low-pressure discharge (fluorescent, CFL,
  induction, low-pressure sodium, neon) and high-pressure discharge (metal halide,
  high-pressure sodium, mercury vapour, xenon arc), each with its own electrical
  law, warm-up, restrike and ageing behaviour.
- **Photometry & planning** — inverse-square illuminance, the lumen method, task
  illuminance targets, colour-rendering and installed-power checks, and a
  recommender that ranks every catalog lamp by installed power at the *end* of a
  maintenance cycle rather than on day one.
- **Layouts** — a split-flux illuminance field over a room, reporting the
  uniformity an average hides, with per-luminaire fault injection.
- **Weather & daylight** — ambient, wind and solar coupling (which moves LED and
  fluorescent output in opposite directions), plus daylight illuminance driving
  photocell and daylight-harvesting controls.
- **Validation** — against the CIE observer, the Planckian locus, published lamp
  efficacy, both derating curves, and **live measured irradiance** from Open-Meteo.
- **Reusable & battery-agnostic** (`simura.lights`) — knows light and the human
  eye, not batteries. See [docs/lights.md](docs/lights.md).

### The platform (shared across components)

- **Twin core** — a FastAPI service: live state + history (REST), a per-system
  live stream (WebSocket), MQTT ingest into TimescaleDB, and optional API-key auth.
- **Dashboard** — a React + TypeScript + Recharts SPA that opens on component
  cards and scopes its navigation to the component you pick.
- **Connectors** — Modbus / OPC-UA / MQTT bridges that emit the same telemetry
  envelope as the simulator, so real hardware and simulation are interchangeable.
- **Dashboard modules** — the dashboard discovers optional modules in
  `dashboard/src/modules/` at build time and merges them into its landing cards
  and navigation. A module talks to the twin only through the same public API,
  and the app builds unchanged with none installed.
- **Component shape** — every component is an independent, unit-tested physics
  library first, then thin wiring into the twin core and dashboard.

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

Development runs in **two phases**.

**Phase 1 — the physics substrate (largely done).** The **Batteries** component is built
out end to end (physics → twin core → dashboard → anomaly detection →
diagnosis/RUL/safety → hardware connectors → fleet, validation, builder, lifecycle,
weather); **Wires** adds a reusable conductor library with planning and validation; and
**Lights** adds spectral physics and lighting design across every source family.

**Phase 2 — the mission layer (in progress).** Turn the substrate into the *CRM for
simulations* the mission describes. The **"get familiar" layer is done** (Component 16):
`simura.explain` answers *what is this system doing, and why* in your own field's terms,
at whichever of three depths you want — and it does it by decomposing the model's own
governing equation at the live operating point rather than by storing sentences about
what usually happens. See [docs/explain.md](docs/explain.md). **Memory that survives the
project is done** (Component 17): `simura.library` keeps saved systems with their
decisions, their notes, and their lineage, so project N+1 starts from project N — and
because a diff between two specs is computed rather than remembered, the record cannot
drift from the systems it describes, and a change nobody explained is *reported* instead
of assumed fine. See [docs/library.md](docs/library.md). Still to come: a
five-minute first simulation, multiplayer collaboration across domains, and
community-contributed physics.

**Phase 2.1 — the world outside the model (in parallel).** A second track, on a
question neither phase had asked: every simulation Simura runs *stands
somewhere*, and it did not know where. **The building is done** (Component 20):
`simura.space` imports an IFC, gbXML or DXF model as a 2D floor plan, and four
things that used to be typed from memory become computed — where the weather is,
how big each room is and what it is for, how long the cable between two rooms
actually runs, and whether the sun reaches a rack at all. The commitment it is
built on is the one BIM interoperability usually breaks: **an import declares
what it could not read**, so a lux figure resting on an assumed ceiling height
says so instead of looking exactly like a measurement. Parsed in pure Python —
no plug-in, no geometry kernel. See [docs/space.md](docs/space.md).
Everything in Phase 2 runs locally — the hosted, public-URL half is parked under
*Deferred — hosting & deployment*. Full detail in [docs/roadmap.md](docs/roadmap.md);
design in [docs/architecture.md](docs/architecture.md).

## Contributing

Issues and PRs welcome. Good first areas span both components — new cell
chemistries (LFP OCV curves), fault types, and load profiles on the battery side;
new conductor materials, insulation classes, and reference resistance standards on
the wire side; new lamp types, spectral recipes, and photometric reference data on
the lighting side — each slots into an [example](examples/README.md). See
[CONTRIBUTING.md](CONTRIBUTING.md). Licensed under **Apache-2.0**.
