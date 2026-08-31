# Simura

**An open, physics-based digital-twin platform — built component by component.**

Simura models real physical systems from first principles and serves them as live
digital twins. Each **component** is an independent, physically faithful
simulation; they share one framework — a twin core (REST + WebSocket API), a live
dashboard, and a "replay against real reference data" validation approach.

Two components exist today:

- **🔋 Batteries (BESS)** — the flagship. Simulate a battery from a single cell to
  a full rack with real electro-thermal dynamics, cell-to-cell imbalance, and
  *injectable faults*, streamed as the same telemetry a real Battery Management
  System (BMS) would emit — then detect anomalies, diagnose faults, and estimate
  state-of-health across a whole fleet.
- **🔌 Wires** — a reusable, battery-agnostic conductor library: resistance,
  voltage drop, ohmic loss and electro-thermal heating, a wiring planner, a
  multi-node network solver, and validation against published conductor standards.

Clone it and you have living hardware on your laptop: no lab, no rig, no fire.

!!! warning "Early-stage hobby project with industrial ambitions"
    The **Batteries** component is built out end to end (simulator → twin core →
    dashboard → anomaly detection → diagnosis/SoH/RUL/safety → real-hardware
    connectors, plus validation, a system builder, fleet lifecycle control, and
    weather coupling). The **Wires** component is a reusable library with a wiring
    planner and validation. Fleet rollup + optional auth are underway; more physics
    components are planned. See the [roadmap](roadmap.md).

## Why

A physics-based digital twin — a faithful software model you can run, break, and
learn from without touching real hardware — is one of the highest-value tools in
industrial software. Simura makes them **open and approachable**: the core of
every component is pure Python + NumPy, unit-tested with no broker, database, or
hardware required.

Batteries came first because battery health and safety is worth real money and
prevents real fires — you can't safely prototype on a real 1 MWh rack. But the
architecture is deliberately **general**: each new component (wiring today;
mechanical, thermal, and power-electronics parts later) plugs into the same twin
core, dashboard, and validation approach.

## What's inside

<div class="grid cards" markdown>

- **[Simulator](simulator.md)** — the battery component: a vectorized
  electro-thermal pack model with composable, targetable faults, emitting a stable
  telemetry contract.
- **[Wires](wires.md)** — the conductor component: resistance / drop / heating
  physics, a wiring planner, a network solver, and validation against standards.
- **[Twin core & API](twin-api.md)** — MQTT ingest → TimescaleDB history →
  FastAPI REST/WebSocket, single-system and whole-fleet, shared across components.
- **[Analytics](analytics.md)** — peer-consensus anomaly detection plus fault
  diagnosis, state-of-health, remaining-useful-life, and a safety state.
- **[Hardware connectors](connectors.md)** — Modbus / OPC-UA / MQTT, config-file
  driven, producing the same telemetry envelope as the simulator.
- **[Validation](validation.md)** — replay real reference data (open battery
  datasets; published conductor standards) through the model and report the error.
- **[Getting familiar](explain.md)** — explanations computed from each model's own
  governing equation, in your field's words and at the depth you ask for.
- **[The building](space.md)** — import an IFC, gbXML or DXF model as a 2D floor
  plan the other components simulate against, with every value the importer had
  to assume recorded rather than hidden.
- **[System library](library.md)** — saved systems with the reason behind each
  choice and the lineage back to what they were forked from, so the next project
  starts from the last one.
- **[Dashboard](dashboard.md)** — a live React app that opens on component cards
  and scopes its navigation to the component you pick.

</div>

## Get going

Head to **[Getting started](getting-started.md)** to run a component's library in
one command, or bring up the whole twin with `docker compose`. Curious how it fits
together first? Read the **[architecture](architecture.md)**.

Licensed under **Apache-2.0**. Contributions welcome — see the
[contributing guide](contributing.md).
