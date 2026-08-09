"""Health status levels for the fleet rollup.

A deliberate Python mirror of the dashboard's ``dashboard/src/lib/status.ts``:
the *thresholds* are the single source of truth, and both sides re-derive a
level from them so the fleet API and the browser agree on what "critical" means.
Keep the two in sync when a threshold moves.

Status colours are reserved and always paired with a label + icon in the UI --
never carried by colour alone -- so only the ordering matters here.
"""

from __future__ import annotations

from typing import Literal

Level = Literal["good", "warning", "serious", "critical"]

# Worst-to-best ordering so ``worst()`` can pick the most severe.
LEVEL_ORDER: dict[str, int] = {"good": 0, "warning": 1, "serious": 2, "critical": 3}


def temp_level(max_temp_c: float) -> Level:
    """Cell temperature -> level. Cell safe max is 60 C in the default config."""
    if max_temp_c >= 58:
        return "critical"
    if max_temp_c >= 52:
        return "serious"
    if max_temp_c >= 45:
        return "warning"
    return "good"


def imbalance_level(imbalance_v: float) -> Level:
    """Pack voltage imbalance -> level."""
    if imbalance_v >= 0.12:
        return "serious"
    if imbalance_v >= 0.07:
        return "warning"
    return "good"


def anomaly_level(score: float) -> Level:
    """Anomaly score -> level. Mirrors the detector's thresholds."""
    if score >= 6:
        return "critical"
    if score >= 4.5:
        return "serious"
    if score >= 3:
        return "warning"
    return "good"


def safety_level(state: str) -> Level:
    """Assessment safety state -> display level."""
    if state == "alarm":
        return "critical"
    if state == "warning":
        return "warning"
    return "good"


def worst(*levels: Level) -> Level:
    """The most severe of the given levels (``good`` if none given)."""
    result: Level = "good"
    for level in levels:
        if LEVEL_ORDER[level] > LEVEL_ORDER[result]:
            result = level
    return result


FAULT_LABEL: dict[str, str] = {
    "none": "No fault",
    "unknown": "Unclassified anomaly",
    "internal_short": "Internal short",
    "cooling_fault": "Cooling fault",
    "resistance_growth": "Resistance growth",
    "sensor_fault": "Sensor fault",
    "thermal_runaway": "Thermal runaway",
}


def fault_label(fault: str) -> str:
    return FAULT_LABEL.get(fault, fault)
