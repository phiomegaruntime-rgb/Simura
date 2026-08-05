# Hardware connectors

Real BMS data comes in over industrial protocols and is republished as the
*same* telemetry envelope the simulator produces — so the whole
twin/analytics/dashboard stack works on real data unchanged.

A connector's only job is to produce a `SourceFrame` of raw named signals; a
protocol-independent **decode core** handles the rest: unit scaling, expanding
per-module temperatures to per-cell, and deriving the per-cell current and SoC a
real BMS does not report.

## Protocols

| Protocol | Front-end | Config example |
|----------|-----------|----------------|
| **Modbus TCP** | register map | `examples/connectors/modbus.yaml` |
| **OPC-UA** | node ids | `examples/connectors/opcua.yaml` |
| **MQTT bridge** | dotted paths into a foreign JSON schema | `examples/connectors/mqtt.yaml` |

Connectors are **config-file driven — no code** to point at a device. Install the
dependencies with `pip install -e ".[connect]"`.

## Try it without hardware

Each protocol ships a device simulator (the hardware analog of the physics
simulator). Run a device, then a connector pointed at it — you'll also need an
MQTT broker (the `docker compose` stack starts one):

```bash
python -m celltwin.connect.devsim --protocol modbus --port 5020 --scenario fault
python -m celltwin.connect --config examples/connectors/modbus.yaml
```

The Modbus device + connector are already wired into the default stack as the
`bess-modbus-01` system. Full recipes and a mapping cheatsheet live in the
[connectors example README](https://github.com/celltwin/celltwin/blob/main/examples/connectors/README.md).

## The mapping

The `mapping:` block turns raw signals into SI telemetry and fills the sparsity
gap a real BMS leaves:

- `series` / `parallel` — pack topology.
- `soc_mode` — `pack` (broadcast one pack SoC), `from_voltage` (derive per-cell
  SoC from the OCV curve), or `array`.
- `temp_mode` — `per_cell`, `per_series` (one sensor per module, expanded), or
  `broadcast`.
- `*_scale` — multiply raw values into SI (e.g. `voltage_scale: 0.001` for
  millivolt registers).

A coarser sensor set is honest input: the [diagnosis](analytics.md) reflects what
can and cannot be observed from it.

## On the backlog

CAN bus (python-can), Modbus RTU/serial, and TLS/auth for OPC-UA and MQTT are on
the [roadmap](roadmap.md) — a new connector is a great
[contribution](contributing.md).
