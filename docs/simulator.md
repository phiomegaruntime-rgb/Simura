# Simulator

The simulator *is* a stand-in physical asset. It models a battery pack's
electro-thermal dynamics and yields one telemetry frame per timestep — the same
`PackTelemetry` contract everything downstream consumes. The physics can evolve
freely behind that contract.

## What's modeled

- **Electrical** — a 1st-order Thevenin equivalent circuit per cell (OCV–SoC
  curve, ohmic resistance `R0`, and an `R1`/`C1` polarization branch), with
  **exact** parallel-group current sharing solved as a small linear system.
- **Thermal** — lumped per-cell heat generation (`I²R` + fault heat) and cooling
  to ambient.
- **State of charge** — coulomb counting with charge/discharge efficiency.
- **Imbalance** — manufacturing spread in capacity, resistance, and initial SoC,
  so cell-to-cell differences and single-cell faults are physically meaningful.

State lives as `(series, parallel)` NumPy arrays in `BatteryPack`, so a
hundreds-of-cells rack steps in one vectorized pass.

## Putting a run together

```python
from simura.sim import Simulator, PackConfig, SimConfig, ChargeDischargeCycle, InternalShort

sim = Simulator(
    PackConfig(series=12, parallel=2, initial_soc=0.9),      # 12S2P NMC pack
    SimConfig(dt_s=1.0, duration_s=2400.0),
    profile=ChargeDischargeCycle(discharge_a=20, charge_a=15),
    faults=[InternalShort(cell=(3, 0), r_short_ohm=2.0, start_s=600)],
)
for tel in sim.run():                # one PackTelemetry per timestep
    print(tel.time_s, tel.pack_soc, tel.max_temp_c)
```

`Simulator.run()` is a generator, so the same loop can feed a printout, an MQTT
publisher, or a training-data dump unchanged.

## Configuration

Config dataclasses are inert and serializable — store them, version them, ship
them over the wire:

- **`CellParams`** — per-cell electro-thermal parameters (capacity, `R0`/`R1`/`C1`,
  thermal capacity and cooling conductance, safe envelope). Defaults approximate
  a 21700 NMC cell.
- **`PackConfig`** — topology (`series` × `parallel`), manufacturing spreads,
  initial SoC, ambient temperature, and a `seed` for reproducibility.
- **`SimConfig`** — timestep and total duration.

## Load profiles

A profile is anything with `current(t, pack_voltage_v) -> amps` (positive =
discharge). Built-ins: `ConstantCurrent`, `ConstantPower`, `ChargeDischargeCycle`,
and `sinusoidal`. Plugging in your own is a one-class job — see
[`examples/custom_profile.py`](https://github.com/simura/simura/blob/main/examples/custom_profile.py).

## Faults

Each fault is targetable to any cell, on any schedule, and faults **compose** via
a `FaultEffect` accumulator:

| Fault | Signature |
|-------|-----------|
| `InternalShort` | parasitic self-discharge current + local heat |
| `ResistanceGrowth` | elevated internal resistance (aging / bad connector) |
| `CoolingFault` | degraded heat rejection |
| `ThermalRunaway` | exothermic runaway once a cell crosses a trigger temperature |
| `SensorDrift` | biases *reported* telemetry, not the physics (a lying sensor) |

These are exactly the failure modes the [analytics](analytics.md) layer learns to
tell apart.

## Cell chemistry

The OCV–SoC curve is a chemistry's electrical fingerprint. The default is an
illustrative NMC table; swap it with `make_ocv(your_table)` to model LFP, NCA,
etc. LFP's famously flat plateau is why voltage-only SoC estimation is hard —
[`examples/ocv_chemistry.py`](https://github.com/simura/simura/blob/main/examples/ocv_chemistry.py)
demonstrates both the curve comparison and how to inject a chemistry into a run.

## The telemetry contract

`snapshot()` produces a `PackTelemetry` (pack-level aggregates + a list of
`CellTelemetry`) each step; sensor biases are applied here. This envelope is the
only thing that crosses the boundary to the twin — which is what lets real
hardware ([connectors](connectors.md)) drop in without touching anything
downstream.
