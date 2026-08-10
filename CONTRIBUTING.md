# Contributing to Simura

Thanks for your interest! Simura is an open, physics-based **digital-twin
platform**, built from independent simulation **components** — a full Batteries
(BESS) twin and a reusable Wires (conductor) library today, with more to come.
It's built to be approachable: the core of every component is pure Python + NumPy,
unit-tested with no infrastructure, so you can be productive without a broker, a
database, or real hardware.

By participating you agree to uphold a respectful, harassment-free environment.
Be kind, assume good faith, and keep discussion technical.

## How the project is built

Simura is built **one component at a time**, and each component leaves the repo
in a runnable, tested state (see the [roadmap](docs/roadmap.md)). Three principles
shape almost every design decision — please keep them in mind when contributing:

1. **Each component is an independent physics library first.** A component
   (`simura.sim`, `simura.wires`, `simura.weather`, …) is a self-contained,
   domain-focused library with no cross-component dependencies — that
   independence is what lets components be composed or reused freely. Wiring it
   into the twin core and dashboard comes *after* the library stands on its own.
2. **A stable telemetry contract is each component's spine.** Everything
   downstream of the battery component consumes `PackTelemetry`; the wire
   component's is `WireTelemetry`. Nothing downstream reaches past the contract,
   so the physics behind it can evolve freely.
3. **The interesting logic lives in a pure library.** Detection, health, fleet
   rollup, hardware decoding, wiring planning, and validation are all pure
   functions over plain data, unit-tested against the simulators' scenarios.
   Infrastructure (FastAPI, MQTT, asyncpg) is thin wiring on top. New logic should
   follow the same shape so it's testable without standing anything up.

The [architecture doc](docs/architecture.md) walks through each component.

## Development setup

Requires Python 3.10+.

```bash
git clone <your-fork-url>
cd mdigital
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"        # simulator + pytest
```

Optional extras, installed as needed:

| Extra | Pulls in | For |
|-------|----------|-----|
| `dev` | pytest | running the tests |
| `server` | fastapi, uvicorn, asyncpg, aiomqtt, pydantic-settings | the twin core |
| `connect` | aiomqtt, pymodbus, asyncua, pyyaml | hardware connectors |
| `examples` | matplotlib | plotting in your own examples |
| `docs` | mkdocs-material | building the docs site |

Install several at once: `pip install -e ".[dev,server,connect]"`.

> **pymodbus is pinned** to `>=3.6,<3.8` — 3.14 rewrote the datastore API. Keep
> the pin unless you're deliberately migrating the connector.

The **dashboard** is a separate React app:

```bash
cd dashboard
npm install
npm run dev        # http://localhost:5173 (proxies to a running twin core)
npm run build      # production bundle
npx tsc --noEmit   # type-check
```

## Running the tests

```bash
pytest -q                       # everything you have extras for
pytest tests/test_fleet.py -q   # a single module
```

The pure-library tests (`test_pack`, `test_detect`, `test_health`, `test_fleet`,
`test_auth`, `test_wires`, `test_wire_validation`) need only the `dev` extra.
`test_connect` and `test_transport` additionally need the `connect`/`server`
extras — if you haven't installed them, those two modules will fail to import,
which is expected.

A change that touches a pure library **must** come with tests. The existing tests
are the model: drive the simulator through a scenario and assert on the outcome
(see [`tests/test_health.py`](tests/test_health.py)), or replay a reference
through the model and assert on the error (see
[`tests/test_wire_validation.py`](tests/test_wire_validation.py)).

## Good first areas

Each component's extension points are designed to be easy first contributions —
most slot into an existing [example](examples/README.md).

**Batteries:**

- **New cell chemistry.** Add a measured OCV–SoC table (LFP, NCA, …) alongside
  `NMC_OCV_TABLE` in [`src/simura/sim/ocv.py`](src/simura/sim/ocv.py). See
  [`examples/ocv_chemistry.py`](examples/ocv_chemistry.py).
- **New load profile** from a real duty cycle — anything with
  `current(t, v) -> amps`. See [`examples/custom_profile.py`](examples/custom_profile.py).
- **New fault type** in [`src/simura/sim/faults.py`](src/simura/sim/faults.py)
  (subclass `Fault`, contribute to the `FaultEffect` accumulator). If it has a
  distinct signature, add a fingerprint to the diagnosis engine and a test.
- **New connector** (CAN bus, Modbus RTU) — implement a `SourceFrame` producer;
  the decode core does the rest. See [`examples/connectors/`](examples/connectors/README.md).

**Wires:**

- **New conductor material or insulation class** in
  [`src/simura/wires/catalog.py`](src/simura/wires/catalog.py) (a resistivity +
  temperature coefficient, or a temperature-rated insulation), plus a catalog
  `WireType`.
- **New wiring fault** in [`src/simura/wires/faults.py`](src/simura/wires/faults.py),
  following the same `FaultEffect`-accumulator pattern as the battery side.
- **New reference resistance standard** in
  [`src/simura/wires/validation/standards.py`](src/simura/wires/validation/standards.py)
  so the conductor model can be validated against another published table.

Bigger items — including whole new physics **components** — live on the
[roadmap](docs/roadmap.md). A new component starts as a standalone, domain-focused
library modelled on `simura.wires` / `simura.weather` (pure, unit-tested, no
cross-component dependencies), and is wired into the twin core and dashboard only
once it stands on its own.

## Code style

- **Python**: standard library formatting conventions; `from __future__ import
  annotations` at the top of modules; type hints on public functions; module and
  function docstrings that explain the *why*, not just the *what*. Match the
  voice of the surrounding code — it's written to be read.
- **TypeScript/React**: follows the existing dashboard patterns. Status meaning
  is **never carried by color alone** — always pair a reserved status color with
  an icon and a label (see [`dashboard/src/lib/status.ts`](dashboard/src/lib/status.ts)
  and the [data-viz conventions](docs/dashboard.md)).
- Keep examples and scripts ASCII-only in printed output where practical, or
  reconfigure stdout to UTF-8 — Windows consoles default to cp1252.

## Submitting a pull request

1. **Open an issue first** for anything non-trivial, so we can agree on the
   approach before you invest time.
2. Branch off `main`; keep the PR focused on one thing.
3. Make sure `pytest -q` passes and, for dashboard changes, `npx tsc --noEmit`
   and `npm run build`.
4. Update docs when behavior changes: the [roadmap](docs/roadmap.md), the
   [architecture doc](docs/architecture.md), and any affected page under `docs/`.
5. Write a clear PR description: what changed, why, and how you verified it.

## License

Simura is licensed under **Apache-2.0**. By contributing, you agree that your
contributions are licensed under the same terms.
