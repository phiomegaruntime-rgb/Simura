"""State-of-health and thermal-trajectory estimation.

Two online estimators, both from telemetry the twin already has:

* **State of health** from **DC internal resistance (DCIR)**. Under load the
  overpotential ``OCV(SoC) - V`` divided by current is the cell's effective
  resistance; resistance growth is the classic aging signature, so
  ``SoH = 1 - (R/R_nom - 1)/(eol_factor - 1)`` maps a fresh cell to 1.0 and a
  cell at end-of-life resistance to 0.0. Estimated only while current is flowing,
  and slowly smoothed.

* **Time to critical** from the smoothed heating rate: ``(T_limit - T) / dT/dt``.
  A live "how long until this cell reaches its limit" -- the number an operator
  actually wants during a thermal event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..sim.ocv import make_ocv
from ..sim.telemetry import PackTelemetry
from .report import CellHealth


@dataclass
class HealthConfig:
    nominal_dcir_ohm: float = 0.031     # DCIR of a fresh cell (R0 + polarization)
    dcir_eol_factor: float = 2.0        # end-of-life DCIR = factor x nominal
    r_alpha: float = 0.05               # slow EWMA for resistance
    temp_alpha: float = 0.3             # EWMA for heating rate
    min_current_a: float = 3.0          # only estimate DCIR above this |current|
    temp_critical_c: float = 60.0       # limit used for time-to-critical
    min_heating_rate: float = 0.1       # C/min below which we don't project


class HealthEngine:
    def __init__(self, config: HealthConfig | None = None) -> None:
        self.c = config or HealthConfig()
        self.ocv = make_ocv()
        self._r: dict[tuple[int, int], float] = {}          # smoothed DCIR
        self._temp_prev: dict[tuple[int, int], float] = {}
        self._rate: dict[tuple[int, int], float] = {}       # smoothed dT/dt
        self._t_prev_s: Optional[float] = None

    def update(self, tel: PackTelemetry) -> dict[tuple[int, int], CellHealth]:
        cells = tel.cells
        keys = [(c.series_index, c.parallel_index) for c in cells]
        soc = np.array([c.soc for c in cells], dtype=float)
        volt = np.array([c.voltage_v for c in cells], dtype=float)
        temp = np.array([c.temp_c for c in cells], dtype=float)
        curr = np.array([c.current_a for c in cells], dtype=float)
        ocv = self.ocv(soc)

        dt_min = None
        if self._t_prev_s is not None and tel.time_s > self._t_prev_s:
            dt_min = (tel.time_s - self._t_prev_s) / 60.0
        self._t_prev_s = tel.time_s

        # --- DCIR / SoH ---
        r_est: dict[tuple[int, int], float] = {}
        for i, key in enumerate(keys):
            prev = self._r.get(key, self.c.nominal_dcir_ohm)
            if abs(curr[i]) >= self.c.min_current_a:
                r_inst = float((ocv[i] - volt[i]) / curr[i])
                if r_inst > 0:  # ignore transient/negative artifacts
                    prev = self.c.r_alpha * r_inst + (1 - self.c.r_alpha) * prev
            self._r[key] = prev
            r_est[key] = prev

        median_r = float(np.median(list(r_est.values())))

        out: dict[tuple[int, int], CellHealth] = {}
        span = self.c.nominal_dcir_ohm * (self.c.dcir_eol_factor - 1.0)
        for i, key in enumerate(keys):
            r = r_est[key]
            soh = 1.0 - (r - self.c.nominal_dcir_ohm) / span
            soh = float(min(1.0, max(0.0, soh)))
            r_ratio_peer = r / median_r if median_r > 0 else 1.0

            # --- heating rate & time-to-critical ---
            rate = self._rate.get(key, 0.0)
            if dt_min is not None and key in self._temp_prev:
                inst_rate = (temp[i] - self._temp_prev[key]) / dt_min
                rate = self.c.temp_alpha * inst_rate + (1 - self.c.temp_alpha) * rate
            self._temp_prev[key] = float(temp[i])
            self._rate[key] = rate

            ttc: Optional[float] = None
            if rate > self.c.min_heating_rate and temp[i] < self.c.temp_critical_c:
                ttc = float((self.c.temp_critical_c - temp[i]) / rate * 60.0)

            out[key] = CellHealth(
                series_index=key[0],
                parallel_index=key[1],
                soh=round(soh, 4),
                dcir_ohm=round(r, 5),
                r_ratio_peer=round(r_ratio_peer, 3),
                heating_rate_c_per_min=round(rate, 3),
                time_to_critical_s=round(ttc, 1) if ttc is not None else None,
            )
        return out
