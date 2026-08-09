# Connector recipes

Point a connector at a real BMS with a **config file — no code**. Each connector
reads its device over an industrial protocol and republishes the *same*
telemetry envelope the simulator does, so the twin core, analytics, and
dashboard treat real hardware and the simulator identically (Component 6).

| Config | Protocol | System id | Notes |
|--------|----------|-----------|-------|
| [`modbus.yaml`](modbus.yaml) | Modbus TCP | `bess-modbus-01` | Register map; unit scales (mV, deci-°C, deci-A); per-module temperature. |
| [`opcua.yaml`](opcua.yaml) | OPC-UA | `bess-opcua-01` | Node ids; server exposes SI floats (scales = 1.0). |
| [`mqtt.yaml`](mqtt.yaml) | MQTT bridge | `bess-mqtt-01` | Adapts a *foreign* JSON schema via dotted paths. |

## Try it without hardware

Every protocol ships a **device simulator** (the hardware analog of the physics
simulator). Run a device, then a connector pointed at it. You'll also need an
MQTT broker running (the `docker compose` stack starts one, or run
`mosquitto` locally).

**Modbus:**

```bash
python -m simura.connect.devsim --protocol modbus --port 5020 --scenario fault
python -m simura.connect --config examples/connectors/modbus.yaml
```

**OPC-UA:**

```bash
python -m simura.connect.devsim --protocol opcua --port 4840 --scenario fault
python -m simura.connect --config examples/connectors/opcua.yaml
```

The Modbus device + connector are already wired into the default
`docker compose` stack as the `bess-modbus-01` system.

## Mapping cheatsheet

The `mapping:` block turns raw signals into SI telemetry and fills the gaps a
real BMS leaves:

- `series` / `parallel` — pack topology.
- `soc_mode` — `pack` (BMS reports one pack SoC, broadcast to cells),
  `from_voltage` (derive per-cell SoC from the OCV curve), or `array`.
- `temp_mode` — `per_cell`, `per_series` (one sensor per module, expanded), or
  `broadcast`.
- `*_scale` — multiply raw values into SI (e.g. `voltage_scale: 0.001` for
  millivolt registers).

A coarser sensor set (per-module temperature, pack-only SoC) is honest input:
the diagnosis will reflect what can and cannot be observed. Install the
connector dependencies with `pip install -e ".[connect]"`.
