"""Peer-consensus anomaly engine.

Every cell in a pack sees essentially the same load, so its siblings are the best
possible baseline: no training data, no per-asset tuning. For each metric we take
the pack's **median** as the consensus and the **MAD** (median absolute deviation)
as the robust spread -- both resistant to a single misbehaving cell -- and score
each cell by how many robust standard deviations it sits from consensus in the
*bad* direction (hot, drained, or off-voltage). An EWMA over frames means only
*sustained* deviation raises the score, so sensor noise doesn't trip it.

The result: the internal-short cell is flagged while it is still only slightly
warmer than its neighbours -- long before it trips any absolute temperature limit.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..sim.telemetry import PackTelemetry
from .report import AnomalyReport, CellAnomaly

_MAD_TO_SIGMA = 1.4826  # scales MAD to a normal-consistent standard deviation


@dataclass
class AnomalyConfig:
    # EWMA smoothing: alpha in (0,1]; smaller = slower, steadier (more persistence).
    alpha: float = 0.25

    # Deviation "floors": a spread below this is treated as noise, not signal.
    # They set the scale of a *meaningful* per-metric deviation, and are the main
    # defense against false positives. Calibrated so a healthy pack (with normal
    # manufacturing spread and SoC drift) peaks well under `warning`, while the
    # internal-short cell is flagged ~5 min before it trips any absolute limit.
    temp_floor_c: float = 0.5
    volt_floor_v: float = 0.02
    soc_floor: float = 0.03

    # Voltage deviates in either direction under a fault; weight it a touch lower
    # since healthy imbalance also lives here.
    volt_weight: float = 0.8

    # Score thresholds (in robust-sigma units) -> severity level.
    warning: float = 3.0
    serious: float = 4.5
    critical: float = 6.0


def _robust_z(x: np.ndarray, floor: float) -> np.ndarray:
    median = np.median(x)
    mad = np.median(np.abs(x - median))
    sigma = max(_MAD_TO_SIGMA * float(mad), floor)
    return (x - median) / sigma


def _level(score: float, c: AnomalyConfig) -> str:
    if score >= c.critical:
        return "critical"
    if score >= c.serious:
        return "serious"
    if score >= c.warning:
        return "warning"
    return "good"


class AnomalyEngine:
    """Stateful per-system detector. Feed it telemetry frames in order."""

    def __init__(self, config: AnomalyConfig | None = None) -> None:
        self.c = config or AnomalyConfig()
        self._ewma: dict[tuple[int, int], float] = {}

    def update(self, tel: PackTelemetry) -> AnomalyReport:
        cells = tel.cells
        keys = [(c.series_index, c.parallel_index) for c in cells]
        temp = np.array([c.temp_c for c in cells], dtype=float)
        volt = np.array([c.voltage_v for c in cells], dtype=float)
        soc = np.array([c.soc for c in cells], dtype=float)

        zt = _robust_z(temp, self.c.temp_floor_c)
        zv = _robust_z(volt, self.c.volt_floor_v)
        zs = _robust_z(soc, self.c.soc_floor)

        out: list[CellAnomaly] = []
        max_score = -1.0
        worst = (0, 0, "none")

        for i, key in enumerate(keys):
            # Bad-direction contributions: hotter than peers, drained vs peers,
            # or off-voltage in either direction.
            contribs = {
                "temperature": max(float(zt[i]), 0.0),
                "state-of-charge": max(float(-zs[i]), 0.0),
                "voltage": self.c.volt_weight * abs(float(zv[i])),
            }
            driver = max(contribs, key=contribs.get)
            instantaneous = contribs[driver]

            prev = self._ewma.get(key, 0.0)
            score = self.c.alpha * instantaneous + (1.0 - self.c.alpha) * prev
            self._ewma[key] = score

            out.append(
                CellAnomaly(
                    series_index=key[0],
                    parallel_index=key[1],
                    score=round(score, 3),
                    level=_level(score, self.c),
                    driver=driver,
                    temp_z=round(float(zt[i]), 2),
                    volt_z=round(float(zv[i]), 2),
                    soc_z=round(float(zs[i]), 2),
                )
            )
            if score > max_score:
                max_score = score
                worst = (key[0], key[1], driver)

        flagged = sum(1 for a in out if a.level != "good")
        return AnomalyReport(
            time_s=round(tel.time_s, 3),
            max_score=round(max(max_score, 0.0), 3),
            flagged_count=flagged,
            worst_series=worst[0],
            worst_parallel=worst[1],
            worst_driver=worst[2],
            cells=out,
        )
