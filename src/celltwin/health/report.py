"""Assessment report structures -- the output contract of Component 5.

Combines prognosis (state-of-health, remaining-useful-life), diagnosis (which
fault), and a safety state into one per-frame assessment that the twin core
stores and the dashboard renders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class CellHealth:
    series_index: int
    parallel_index: int
    soh: float                              # state of health, 0..1 (1 = as new)
    dcir_ohm: float                         # estimated DC internal resistance
    r_ratio_peer: float                     # DCIR relative to the pack median
    heating_rate_c_per_min: float           # smoothed dT/dt
    time_to_critical_s: Optional[float]     # projected time to the temp limit


@dataclass
class Diagnosis:
    fault_type: str        # none | internal_short | cooling_fault | resistance_growth | sensor_fault | thermal_runaway
    confidence: float      # 0..1
    cell_series: int       # implicated cell (-1 if none)
    cell_parallel: int
    rationale: str


@dataclass
class AssessmentReport:
    time_s: float
    pack_soh: float
    worst_cell_soh: float
    diagnosis: Diagnosis
    safety_state: str      # nominal | warning | alarm
    min_time_to_critical_s: Optional[float]
    cells: list[CellHealth] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
