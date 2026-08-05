"""Turn a raw :class:`SourceFrame` into the twin's telemetry contract.

This is the protocol-independent core of Component 6. Every connector -- MQTT,
Modbus, OPC-UA -- funnels through here, so a real device speaks the exact same
``PackTelemetry`` the simulator does, and the entire twin/analytics/dashboard
stack works on real data unchanged.

It also bridges the *sparsity* gap: a real BMS reports per-cell voltage plus a
handful of temperatures and pack-level current/SoC, so we derive the per-cell
current and SoC the contract expects (series cells share the string current;
SoC is taken from the pack, or estimated from voltage).
"""

from __future__ import annotations

import numpy as np

from ..sim.ocv import make_soc_from_ocv
from ..sim.telemetry import CellTelemetry, PackTelemetry
from .frame import DeviceMapping, SourceFrame

_soc_from_ocv = make_soc_from_ocv()


def _expand_temps(raw: list[float], mapping: DeviceMapping) -> np.ndarray:
    """Expand a temperature array to one value per cell, per ``temp_mode``."""
    s, p, n = mapping.series, mapping.parallel, mapping.n_cells
    arr = np.array(raw, dtype=float) * mapping.temp_scale

    mode = mapping.temp_mode
    if mode == "auto":
        mode = "per_cell" if arr.size == n else "per_series" if arr.size == s else "broadcast"

    if mode == "per_cell":
        if arr.size != n:
            raise ValueError(f"temp per_cell expects {n} values, got {arr.size}")
        return arr
    if mode == "per_series":
        if arr.size != s:
            raise ValueError(f"temp per_series expects {s} values, got {arr.size}")
        return np.repeat(arr, p)  # each module's temperature shared by its parallel cells
    # broadcast
    return np.full(n, float(arr.flat[0]))


def build_telemetry(frame: SourceFrame, mapping: DeviceMapping) -> PackTelemetry:
    s, p, n = mapping.series, mapping.parallel, mapping.n_cells

    volts = np.array(frame.arrays.get("cell_voltage", []), dtype=float) * mapping.voltage_scale
    if volts.size != n:
        raise ValueError(f"cell_voltage expects {n} values, got {volts.size}")
    temps = _expand_temps(frame.arrays.get("cell_temp", []), mapping)

    pack_current = float(frame.scalars.get("pack_current", 0.0)) * mapping.current_scale
    pack_soc_raw = frame.scalars.get("pack_soc")
    pack_soc = float(pack_soc_raw) * mapping.soc_scale if pack_soc_raw is not None else None

    # Per-cell current.
    if mapping.current_mode == "array":
        currents = np.array(frame.arrays["cell_current"], dtype=float) * mapping.current_scale
    else:  # a series string shares the pack current; a parallel group splits it
        currents = np.full(n, pack_current / p)

    # Per-cell SoC.
    if mapping.soc_mode == "array":
        socs = np.array(frame.arrays["cell_soc"], dtype=float) * mapping.soc_scale
    elif mapping.soc_mode == "from_voltage":
        socs = _soc_from_ocv(volts)
    else:  # pack: broadcast the pack SoC (fall back to a voltage estimate)
        socs = np.full(n, pack_soc if pack_soc is not None else float(_soc_from_ocv(volts).mean()))

    cells: list[CellTelemetry] = []
    for si in range(s):
        for pi in range(p):
            idx = si * p + pi
            cells.append(
                CellTelemetry(
                    series_index=si,
                    parallel_index=pi,
                    voltage_v=round(float(volts[idx]), 4),
                    current_a=round(float(currents[idx]), 4),
                    temp_c=round(float(temps[idx]), 3),
                    soc=round(float(np.clip(socs[idx], 0.0, 1.0)), 4),
                )
            )

    # Pack aggregates. Pack voltage = sum over series modules of the module's
    # (mean parallel) voltage.
    module_v = volts.reshape(s, p).mean(axis=1)
    pack_voltage = float(module_v.sum())
    final_soc = pack_soc if pack_soc is not None else float(np.mean(socs))
    time_s = float(frame.scalars.get("sim_time", 0.0))

    return PackTelemetry(
        time_s=round(time_s, 3),
        pack_voltage_v=round(pack_voltage, 4),
        pack_current_a=round(pack_current, 4),
        pack_power_w=round(pack_voltage * pack_current, 3),
        pack_soc=round(final_soc, 4),
        max_temp_c=round(float(temps.max()), 3),
        min_cell_voltage_v=round(float(volts.min()), 4),
        max_cell_voltage_v=round(float(volts.max()), 4),
        voltage_imbalance_v=round(float(volts.max() - volts.min()), 4),
        cells=cells,
    )
