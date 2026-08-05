# Contributing

CellTwin is built to be approachable: the core libraries are pure Python + NumPy
and unit-tested with no infrastructure, so you can be productive without a
broker, a database, or real hardware.

The full guide — dev setup, extras, style, and the PR checklist — lives in
[`CONTRIBUTING.md`](https://github.com/celltwin/celltwin/blob/main/CONTRIBUTING.md)
at the repository root. The essentials:

## Two principles

1. **A stable telemetry contract is the spine.** Everything downstream consumes
   `PackTelemetry` and nothing else.
2. **The interesting logic lives in a pure library.** Detection, health, fleet
   rollup, and hardware decoding are pure functions over plain data, unit-tested
   against the simulator's scenarios; infrastructure is thin wiring on top. New
   logic should follow the same shape.

## Setup & tests

```bash
pip install -e ".[dev]"     # simulator + pytest
pytest -q
```

Pure-library tests (`test_pack`, `test_detect`, `test_health`, `test_fleet`,
`test_auth`) need only the `dev` extra; `test_connect` / `test_transport` also
need `".[connect,server]"`. A change to a pure library **must** come with tests —
[`tests/test_health.py`](https://github.com/celltwin/celltwin/blob/main/tests/test_health.py)
is the model.

## Good first areas

Each slots into an existing [example](https://github.com/celltwin/celltwin/tree/main/examples):

- A **new cell chemistry** (measured OCV–SoC table) — see [Simulator](simulator.md#cell-chemistry).
- A **new load profile** from a real duty cycle.
- A **new fault type** (plus a diagnosis fingerprint + test).
- A **new connector** (CAN bus, Modbus RTU) — implement a `SourceFrame` producer.

Bigger items are on the [roadmap](roadmap.md). Open an issue before starting
anything non-trivial so we can agree on the approach. Licensed under Apache-2.0.
