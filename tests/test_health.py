"""Tests for the assessment engine (diagnosis + SoH + RUL + safety).

The classifier must tell the fault types apart, state-of-health must track
resistance growth (and only that), and time-to-critical must appear when a cell
is heating. All pure-library, driven by the simulator's fault scenarios.
"""

from __future__ import annotations

from celltwin.detect import AnomalyEngine
from celltwin.health import AssessmentEngine
from celltwin.sim import (
    ChargeDischargeCycle,
    CoolingFault,
    InternalShort,
    PackConfig,
    ResistanceGrowth,
    SensorDrift,
    SimConfig,
    Simulator,
    ThermalRunaway,
)


def _run(faults, duration=1400.0):
    pack = PackConfig(series=12, parallel=2, initial_soc=0.9)
    sim = SimConfig(dt_s=1.0, duration_s=duration)
    profile = ChargeDischargeCycle(discharge_a=20.0, charge_a=15.0)
    anomaly = AnomalyEngine()
    engine = AssessmentEngine()
    rows = []
    for tel in Simulator(pack, sim, profile, faults).run():
        a = anomaly.update(tel)
        rows.append((tel.time_s, tel.max_temp_c, engine.update(tel, a)))
    return rows


def _diagnoses(rows, after_s=800.0):
    return {r[2].diagnosis.fault_type for r in rows if r[0] >= after_s}


def test_healthy_has_no_diagnosis():
    rows = _run([])
    assert all(r[2].diagnosis.fault_type == "none" for r in rows)
    assert all(r[2].safety_state == "nominal" for r in rows)
    # SoH stays high for a fresh pack.
    assert rows[-1][2].pack_soh > 0.95


def test_internal_short_diagnosed():
    rows = _run([
        InternalShort(cell=(3, 0), r_short_ohm=2.0, start_s=600.0),
        ThermalRunaway(cell=(3, 0), trigger_c=70.0, start_s=600.0),
    ])
    final = rows[-1][2].diagnosis
    assert final.fault_type == "internal_short"
    assert (final.cell_series, final.cell_parallel) == (3, 0)


def test_cooling_fault_diagnosed_and_not_confused_with_short():
    rows = _run([CoolingFault(cell=(3, 0), effectiveness=0.12, start_s=600.0)])
    diags = _diagnoses(rows)
    assert "cooling_fault" in diags
    assert "internal_short" not in diags  # no drain => never a short


def test_resistance_growth_diagnosed_and_lowers_soh():
    rows = _run([ResistanceGrowth(cell=(3, 0), multiplier=3.5, start_s=600.0)])
    final = rows[-1][2]
    assert final.diagnosis.fault_type == "resistance_growth"
    # The degraded cell drags worst-cell SoH well down; a short would not.
    assert final.worst_cell_soh < 0.5


def test_sensor_drift_diagnosed_without_soh_hit():
    rows = _run([SensorDrift(signal="voltage", cell=(3, 0), rate_per_s=0.0004, start_s=600.0)])
    diags = _diagnoses(rows, after_s=900.0)
    assert "sensor_fault" in diags
    # A lying sensor must not be mistaken for real aging.
    assert rows[-1][2].pack_soh > 0.9


def test_time_to_critical_appears_when_heating():
    rows = _run([
        InternalShort(cell=(3, 0), r_short_ohm=2.0, start_s=600.0),
        ThermalRunaway(cell=(3, 0), trigger_c=70.0, start_s=600.0),
    ])
    # Somewhere during the fault ramp, a finite time-to-critical is projected.
    assert any(r[2].min_time_to_critical_s is not None for r in rows if r[0] > 600)
