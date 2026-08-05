"""Fleet rollup: aggregate every system's twin into one at-a-glance view.

Pure library (no infra) so it is unit-tested standalone and reused by the twin
core's ``/api/fleet`` endpoint.
"""

from .levels import Level, anomaly_level, fault_label, imbalance_level, safety_level, temp_level, worst
from .summary import build_fleet, roll_up_system

__all__ = [
    "build_fleet",
    "roll_up_system",
    "Level",
    "temp_level",
    "imbalance_level",
    "anomaly_level",
    "safety_level",
    "fault_label",
    "worst",
]
