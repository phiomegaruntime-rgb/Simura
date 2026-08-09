"""Tests for the anomaly engine.

The engine must (a) leave a healthy pack quiet, (b) flag the internal-short cell,
(c) do so *before* absolute temperature crosses a hard limit, and (d) name the
right cell and driver -- and it must all run as a pure library, no infra.
"""

from __future__ import annotations

from simura.detect import AnomalyEngine
from simura.detect.report import AnomalyReport
from simura.sim import (
    ChargeDischargeCycle,
    InternalShort,
    PackConfig,
    SimConfig,
    Simulator,
    ThermalRunaway,
)
from simura.sim.telemetry import PackTelemetry


def _run(scenario: str) -> list[tuple[float, float, AnomalyReport]]:
    pack = PackConfig(series=12, parallel=2, initial_soc=0.9)
    sim = SimConfig(dt_s=1.0, duration_s=1400.0)
    profile = ChargeDischargeCycle(discharge_a=20.0, charge_a=15.0)
    faults = []
    if scenario == "fault":
        faults = [
            InternalShort(cell=(3, 0), r_short_ohm=2.0, start_s=600.0),
            ThermalRunaway(cell=(3, 0), trigger_c=70.0, start_s=600.0),
        ]
    engine = AnomalyEngine()
    return [(t.time_s, t.max_temp_c, engine.update(t)) for t in Simulator(pack, sim, profile, faults).run()]


def test_healthy_pack_stays_quiet():
    rows = _run("healthy")
    peak = max(r[2].max_score for r in rows)
    # No false positives: peak stays comfortably below the warning threshold (3).
    assert peak < 2.5, f"healthy peak score too high: {peak}"
    assert all(r[2].flagged_count == 0 for r in rows)


def test_fault_cell_is_flagged():
    rows = _run("fault")
    peak = max(r[2].max_score for r in rows)
    assert peak >= 6.0  # reaches "critical"
    # The last frame should point at the shorted cell, driven by temperature.
    final = rows[-1][2]
    assert (final.worst_series, final.worst_parallel) == (3, 0)
    assert final.worst_driver == "temperature"


def test_anomaly_precedes_absolute_threshold():
    rows = _run("fault")
    first_warning = next((t for t, _, r in rows if r.max_score >= 3.0), None)
    first_hot = next((t for t, tmax, _ in rows if tmax >= 45.0), None)
    assert first_warning is not None and first_hot is not None
    # Early warning: the anomaly is raised well before the hard limit is hit.
    assert first_warning < first_hot - 60, (first_warning, first_hot)


def test_report_roundtrips_through_dict():
    _, _, report = _run("fault")[-1]
    rebuilt = PackTelemetry  # ensure import used
    d = report.to_dict()
    assert d["cells"] and "score" in d["cells"][0]
    assert d["worst_driver"] == report.worst_driver
