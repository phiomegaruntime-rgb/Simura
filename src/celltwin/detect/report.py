"""Anomaly report data structures -- the output contract of the detector.

Like the telemetry contract, this is the only thing downstream (twin core,
dashboard) consumes, so the detection internals can evolve behind it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class CellAnomaly:
    series_index: int
    parallel_index: int
    score: float           # smoothed anomaly score (robust z, EWMA), 0 = nominal
    level: str             # good | warning | serious | critical
    driver: str            # which signal drives the score (temperature/voltage/...)
    temp_z: float          # peer-consensus z of temperature (signed)
    volt_z: float          # ... of voltage
    soc_z: float           # ... of state of charge


@dataclass
class AnomalyReport:
    time_s: float
    max_score: float
    flagged_count: int
    worst_series: int
    worst_parallel: int
    worst_driver: str
    cells: list[CellAnomaly] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
