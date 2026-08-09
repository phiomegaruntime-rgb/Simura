# Simura

**An open, physics-based digital twin for battery energy storage systems (BESS).**

Simura simulates a battery — from a single cell to a full rack — with real
electro-thermal dynamics, cell-to-cell imbalance, and *injectable faults*, then
streams the same telemetry a real Battery Management System (BMS) would. Clone
it and you have a living battery on your laptop: no hardware, no lab, no fire.

!!! warning "Early-stage hobby project with industrial ambitions"
    Components 1–6 (simulator → twin core → dashboard → anomaly detection →
    diagnosis/SoH/RUL/safety → real-hardware connectors) are done and tested.
    Component 7 (fleet rollup + optional auth) is underway. See the
    [roadmap](roadmap.md).

## Why

Battery health and safety is one of the most valuable digital-twin use cases in
energy today — state-of-charge, state-of-health, and thermal-runaway early
warning are worth real money and prevent real fires. But you can't learn or
prototype on a real 1 MWh rack. Simura gives everyone a physically faithful,
fully controllable battery to build diagnostics, dashboards, and ML on top of.

## What's inside

<div class="grid cards" markdown>

- **[Simulator](simulator.md)** — vectorized electro-thermal pack model with
  composable, targetable faults, emitting a stable telemetry contract.
- **[Twin core & API](twin-api.md)** — MQTT ingest → TimescaleDB history →
  FastAPI REST/WebSocket, single-system and whole-fleet.
- **[Analytics](analytics.md)** — peer-consensus anomaly detection plus fault
  diagnosis, state-of-health, remaining-useful-life, and a safety state.
- **[Hardware connectors](connectors.md)** — Modbus / OPC-UA / MQTT, config-file
  driven, producing the same telemetry envelope as the simulator.
- **[Dashboard](dashboard.md)** — a live React fleet overview that drills into
  per-pack heatmaps, trends, and a diagnosis card.

</div>

## Get going

Head to **[Getting started](getting-started.md)** to run the simulator in one
command, or bring up the whole twin with `docker compose`. Curious how it fits
together first? Read the **[architecture](architecture.md)**.

Licensed under **Apache-2.0**. Contributions welcome — see the
[contributing guide](contributing.md).
