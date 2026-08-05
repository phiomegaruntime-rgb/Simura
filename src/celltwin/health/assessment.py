"""AssessmentEngine: the Component 5 top-level, combining health + diagnosis.

Produces one :class:`AssessmentReport` per telemetry frame: state-of-health,
the diagnosis, a pack-level remaining-useful-life (soonest time-to-critical), and
an overall safety state. It is stateful (SoH and heating-rate estimators carry
across frames) and pure -- no I/O, so it is unit-tested against the simulator.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from ..detect.report import AnomalyReport
from ..sim.telemetry import PackTelemetry
from .diagnosis import DiagnosisConfig, DiagnosisEngine
from .health_engine import HealthConfig, HealthEngine
from .report import AssessmentReport


class AssessmentEngine:
    def __init__(
        self,
        health_config: HealthConfig | None = None,
        diagnosis_config: DiagnosisConfig | None = None,
        soh_warn: float = 0.85,
        alarm_temp_c: float = 50.0,
    ) -> None:
        self.health = HealthEngine(health_config)
        self.diag = DiagnosisEngine(diagnosis_config)
        self.soh_warn = soh_warn
        self.alarm_temp_c = alarm_temp_c

    def update(self, tel: PackTelemetry, anomaly: Optional[AnomalyReport]) -> AssessmentReport:
        health = self.health.update(tel)
        diagnosis = self.diag.classify(tel, anomaly, health)

        cells = list(health.values())
        pack_soh = float(np.mean([c.soh for c in cells])) if cells else 1.0
        worst_soh = float(np.min([c.soh for c in cells])) if cells else 1.0

        ttcs = [c.time_to_critical_s for c in cells if c.time_to_critical_s is not None]
        min_ttc = min(ttcs) if ttcs else None

        safety = _safety_state(
            diagnosis.fault_type, tel.max_temp_c, min_ttc, worst_soh, self.soh_warn, self.alarm_temp_c
        )

        return AssessmentReport(
            time_s=round(tel.time_s, 3),
            pack_soh=round(pack_soh, 4),
            worst_cell_soh=round(worst_soh, 4),
            diagnosis=diagnosis,
            safety_state=safety,
            min_time_to_critical_s=round(min_ttc, 1) if min_ttc is not None else None,
            cells=cells,
        )


def _safety_state(
    fault_type: str,
    max_temp_c: float,
    min_ttc: Optional[float],
    worst_soh: float,
    soh_warn: float,
    alarm_temp_c: float,
) -> str:
    # Alarm: an active runaway diagnosis, or hot with a short time-to-critical.
    if fault_type == "thermal_runaway":
        return "alarm"
    if max_temp_c >= alarm_temp_c and min_ttc is not None and min_ttc <= 300:
        return "alarm"
    # Warning: an active fault, degraded health, or a projected time-to-critical.
    if fault_type not in ("none", "unknown"):
        return "warning"
    if worst_soh < soh_warn:
        return "warning"
    if min_ttc is not None and min_ttc <= 900:
        return "warning"
    return "nominal"
