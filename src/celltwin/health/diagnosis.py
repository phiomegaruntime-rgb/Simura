"""Fault diagnosis by fingerprint matching.

Each fault type leaves a distinct signature in the peer-consensus z-scores
(Component 4) plus the health features (Component 5):

    thermal_runaway   fast, accelerating heat -- high heating rate while hot
    internal_short    hot AND draining faster than peers (self-discharge)
    cooling_fault     hot WITHOUT extra drain (heat-rejection loss)
    resistance_growth a cell whose DCIR has climbed well above its peers
    sensor_fault      one signal deviates with no physical corroboration

Signatures are checked in priority order (safety first). The discriminator
between a short and a cooling fault is the *presence* of extra drain, not its
magnitude -- in a cycling pack the differential self-discharge is small against
the duty cycle, but it is real and one-directional, and the "hot" gate keeps a
healthy cell from ever being called a short.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..detect.report import AnomalyReport, CellAnomaly
from ..sim.telemetry import PackTelemetry
from .report import CellHealth, Diagnosis


@dataclass
class DiagnosisConfig:
    min_anomaly_score: float = 3.0      # below this, nothing is diagnosed
    hot_z: float = 2.0                  # temp z that counts as "hot vs peers"
    drain_z: float = 0.6               # soc z (magnitude) that counts as draining
    runaway_rate_c_per_min: float = 2.0
    runaway_temp_c: float = 48.0
    resistance_ratio: float = 1.4       # DCIR vs peer median for aging
    min_confidence: float = 0.15


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


class DiagnosisEngine:
    def __init__(self, config: DiagnosisConfig | None = None) -> None:
        self.c = config or DiagnosisConfig()

    def classify(
        self,
        tel: PackTelemetry,
        anomaly: Optional[AnomalyReport],
        health: dict[tuple[int, int], CellHealth],
    ) -> Diagnosis:
        if anomaly is None or anomaly.max_score < self.c.min_anomaly_score:
            return Diagnosis("none", 0.0, -1, -1, "No cell deviates significantly from its peers.")

        key = (anomaly.worst_series, anomaly.worst_parallel)
        ca = _find_cell(anomaly.cells, key)
        ch = health.get(key)
        if ca is None or ch is None:
            return Diagnosis("none", 0.0, -1, -1, "Insufficient data to diagnose.")

        hot = max(ca.temp_z, 0.0)
        drained = max(-ca.soc_z, 0.0)
        vz = abs(ca.volt_z)
        rate = ch.heating_rate_c_per_min
        temp = _cell_temp(tel, key)

        # 1) Thermal runaway -- safety first.
        if rate >= self.c.runaway_rate_c_per_min and temp >= self.c.runaway_temp_c:
            conf = _clamp(0.5 + (rate - self.c.runaway_rate_c_per_min) / (2 * self.c.runaway_rate_c_per_min))
            return Diagnosis("thermal_runaway", round(conf, 3), key[0], key[1],
                             f"Temperature {temp:.0f} °C rising at {rate:.1f} °C/min (runaway signature).")

        # 2) Resistance growth -- a cell whose DCIR stands out from its peers.
        hi = max(health.values(), key=lambda h: h.r_ratio_peer)
        if hi.r_ratio_peer >= self.c.resistance_ratio:
            conf = _clamp((hi.r_ratio_peer - 1.2) / 0.8)
            return Diagnosis("resistance_growth", round(conf, 3), hi.series_index, hi.parallel_index,
                             f"DCIR {hi.r_ratio_peer:.2f}x the pack median (resistance growth).")

        # 3) Internal short -- hot AND draining faster than peers.
        if hot >= self.c.hot_z and drained >= self.c.drain_z:
            conf = _clamp(0.4 + 0.08 * (hot - self.c.hot_z) + 0.3 * (drained - self.c.drain_z))
            return Diagnosis("internal_short", round(conf, 3), key[0], key[1],
                             f"Cell is {ca.temp_z:.1f}σ hotter and draining {drained:.1f}σ faster than peers.")

        # 4) Cooling fault -- hot WITHOUT extra drain.
        if hot >= self.c.hot_z and drained < self.c.drain_z:
            conf = _clamp(0.4 + 0.1 * (hot - self.c.hot_z))
            return Diagnosis("cooling_fault", round(conf, 3), key[0], key[1],
                             f"Cell is {ca.temp_z:.1f}σ hotter than peers without extra drain (heat-rejection loss).")

        # 5) Sensor fault -- a lone signal with no physical corroboration.
        ss = _sensor_score(ca.temp_z, ca.soc_z, vz, rate)
        if ss >= self.c.min_confidence:
            return Diagnosis("sensor_fault", round(ss, 3), key[0], key[1],
                             "A single signal deviates without physical corroboration (likely sensor).")

        # 6) Anomalous but no fingerprint fits well.
        return Diagnosis("unknown", round(_clamp(anomaly.max_score / 10.0), 3), key[0], key[1],
                         f"Cell deviates on {anomaly.worst_driver} but the signature is unclear.")


def _sensor_score(tz: float, sz: float, vz: float, rate: float) -> float:
    drained = max(-sz, 0.0)
    if vz > 3.0 and abs(tz) < 1.5 and drained < 1.5:
        return _clamp((vz - 3.0) / 4.0 + 0.3)
    if tz > 3.0 and rate < 0.3 and drained < 1.5 and vz < 1.5:
        return _clamp((tz - 3.0) / 4.0 + 0.3)
    return 0.0


def _find_cell(cells: list[CellAnomaly], key: tuple[int, int]) -> Optional[CellAnomaly]:
    for c in cells:
        if (c.series_index, c.parallel_index) == key:
            return c
    return None


def _cell_temp(tel: PackTelemetry, key: tuple[int, int]) -> float:
    for c in tel.cells:
        if (c.series_index, c.parallel_index) == key:
            return c.temp_c
    return 0.0
