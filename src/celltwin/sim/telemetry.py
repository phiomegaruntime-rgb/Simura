"""Telemetry: the observable output of the twin.

This is deliberately the *only* thing downstream components (MQTT transport,
time-series store, dashboard, ML) will consume. Keeping a stable, serializable
telemetry contract here means the physics core can evolve without breaking the
rest of the system. Sensor-drift faults are applied at this boundary, because a
faulty sensor changes what you *measure*, not what the battery *does*.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

import numpy as np


@dataclass
class CellTelemetry:
    series_index: int
    parallel_index: int
    voltage_v: float
    current_a: float
    temp_c: float
    soc: float


@dataclass
class PackTelemetry:
    time_s: float
    pack_voltage_v: float
    pack_current_a: float
    pack_power_w: float
    pack_soc: float
    max_temp_c: float
    min_cell_voltage_v: float
    max_cell_voltage_v: float
    voltage_imbalance_v: float          # max - min cell voltage (balance health)
    cells: list[CellTelemetry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PackTelemetry":
        """Rebuild a PackTelemetry from its serialized form (e.g. off MQTT)."""
        cells = [CellTelemetry(**c) for c in d.get("cells", [])]
        names = {f.name for f in fields(cls) if f.name != "cells"}
        return cls(cells=cells, **{k: v for k, v in d.items() if k in names})


def snapshot(pack, t: float, pack_current_a: float) -> PackTelemetry:
    """Build a :class:`PackTelemetry` from the pack's current state.

    Applies any stashed sensor biases from the last fault step so reported
    voltage/temperature reflect what a (possibly faulty) sensor would report.
    """
    v_bias = getattr(pack, "_voltage_bias", np.zeros(pack.shape))
    t_bias = getattr(pack, "_temp_bias", np.zeros(pack.shape))
    measured_v = pack.cell_voltage_v + v_bias
    measured_t = pack.temp_c + t_bias

    cells: list[CellTelemetry] = []
    s_n, p_n = pack.shape
    for s in range(s_n):
        for p in range(p_n):
            cells.append(
                CellTelemetry(
                    series_index=s,
                    parallel_index=p,
                    voltage_v=round(float(measured_v[s, p]), 4),
                    current_a=round(float(pack.cell_current_a[s, p]), 4),
                    temp_c=round(float(measured_t[s, p]), 3),
                    soc=round(float(pack.soc[s, p]), 4),
                )
            )

    return PackTelemetry(
        time_s=round(t, 3),
        pack_voltage_v=round(float(pack.pack_voltage_v), 4),
        pack_current_a=round(float(pack_current_a), 4),
        pack_power_w=round(float(pack.pack_voltage_v * pack_current_a), 3),
        pack_soc=round(pack.pack_soc, 4),
        max_temp_c=round(float(measured_t.max()), 3),
        min_cell_voltage_v=round(float(measured_v.min()), 4),
        max_cell_voltage_v=round(float(measured_v.max()), 4),
        voltage_imbalance_v=round(float(measured_v.max() - measured_v.min()), 4),
        cells=cells,
    )
