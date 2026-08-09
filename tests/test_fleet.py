"""Tests for the fleet rollup (simura.fleet).

Pure-library, driven by hand-built envelopes for the edge cases and by the
simulator + detection/assessment engines for a realistic end-to-end rollup --
exactly the shapes the twin core's live caches hold.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from simura.detect import AnomalyEngine
from simura.fleet import build_fleet, roll_up_system
from simura.health import AssessmentEngine
from simura.sim import (
    ChargeDischargeCycle,
    InternalShort,
    PackConfig,
    SimConfig,
    Simulator,
)

NOW = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
STALE = 15.0


def _tel_env(system_id, *, when=NOW, **tel):
    return {"system_id": system_id, "timestamp": when.isoformat(), "telemetry": tel}


# -- roll_up_system --------------------------------------------------------
def test_healthy_system_is_good_and_live():
    env = _tel_env("bess-02", pack_soc=0.6, pack_power_w=-500.0, max_temp_c=30.0,
                   voltage_imbalance_v=0.01)
    row = roll_up_system("bess-02", "Pack 2", env, None, None, NOW, STALE)
    assert row["status"] == "good"
    assert row["live"] is True
    assert "nominal" in row["status_reason"]


def test_alarm_system_is_critical():
    tel = _tel_env("bess-01", pack_soc=0.4, pack_power_w=0.0, max_temp_c=61.0,
                   voltage_imbalance_v=0.02)
    anomaly = {"anomaly": {"max_score": 8.0, "flagged_count": 1, "worst_series": 3,
                           "worst_parallel": 0, "worst_driver": "temperature"}}
    assessment = {"assessment": {"pack_soh": 0.8, "safety_state": "alarm",
                                 "diagnosis": {"fault_type": "thermal_runaway",
                                               "confidence": 1.0, "cell_series": 3,
                                               "cell_parallel": 0}}}
    row = roll_up_system("bess-01", "Pack 1", tel, anomaly, assessment, NOW, STALE)
    assert row["status"] == "critical"
    assert row["status_reason"].startswith("SAFETY ALARM")


def test_stale_timestamp_marks_offline():
    env = _tel_env("bess-01", when=NOW - timedelta(seconds=120), pack_soc=0.5,
                   pack_power_w=0.0, max_temp_c=30.0, voltage_imbalance_v=0.01)
    row = roll_up_system("bess-01", None, env, None, None, NOW, STALE)
    assert row["live"] is False
    assert row["age_s"] == 120.0


def test_never_seen_system_has_no_telemetry():
    row = roll_up_system("bess-03", "Pack 3", None, None, None, NOW, STALE)
    assert row["live"] is False
    assert row["status"] == "good"
    assert row["status_reason"] == "No telemetry received yet."


def test_partial_analytics_degrade_gracefully():
    # Telemetry present, no anomaly/assessment yet: still rolls up on temp/balance.
    env = _tel_env("bess-01", pack_soc=0.5, pack_power_w=0.0, max_temp_c=46.0,
                   voltage_imbalance_v=0.01)
    row = roll_up_system("bess-01", None, env, None, None, NOW, STALE)
    assert row["status"] == "warning"  # 46 C -> warning band
    assert row["fault_type"] is None


# -- source / lifecycle (Component 10) -------------------------------------
def test_roll_up_defaults_to_realtime_running():
    env = _tel_env("bess-02", pack_soc=0.6, pack_power_w=0.0, max_temp_c=30.0,
                   voltage_imbalance_v=0.01)
    row = roll_up_system("bess-02", "Pack 2", env, None, None, NOW, STALE)
    assert row["source"] == "realtime"
    assert row["run_state"] == "running"


def test_build_fleet_passes_through_source_and_run_state():
    systems = [
        {"system_id": "sim-1", "name": "Sim", "source": "simulation", "run_state": "paused"},
        {"system_id": "bess-01", "name": "Real"},  # no source keys -> defaults
    ]
    tel = {"sim-1": _tel_env("sim-1", pack_soc=0.5, pack_power_w=0.0, max_temp_c=30.0,
                             voltage_imbalance_v=0.01)}
    fleet = build_fleet(systems, tel, {}, {}, now=NOW, stale_after_s=STALE)
    by_id = {r["system_id"]: r for r in fleet["systems"]}
    assert by_id["sim-1"]["source"] == "simulation"
    assert by_id["sim-1"]["run_state"] == "paused"
    assert by_id["bess-01"]["source"] == "realtime"
    assert by_id["bess-01"]["run_state"] == "running"


# -- build_fleet -----------------------------------------------------------
def test_build_fleet_summary_and_ordering():
    systems = [
        {"system_id": "bess-01", "name": "Pack 1"},
        {"system_id": "bess-02", "name": "Pack 2"},
        {"system_id": "bess-03", "name": "Pack 3"},
    ]
    tel = {
        "bess-01": _tel_env("bess-01", pack_soc=0.4, pack_power_w=-100.0,
                            max_temp_c=61.0, voltage_imbalance_v=0.02),
        "bess-02": _tel_env("bess-02", pack_soc=0.6, pack_power_w=-200.0,
                            max_temp_c=30.0, voltage_imbalance_v=0.01),
        # bess-03 never seen.
    }
    assessment = {
        "bess-01": {"assessment": {"pack_soh": 0.8, "safety_state": "alarm",
                                   "diagnosis": {"fault_type": "thermal_runaway",
                                                 "confidence": 1.0, "cell_series": 3,
                                                 "cell_parallel": 0}}},
    }
    out = build_fleet(systems, tel, {}, assessment, NOW, STALE)
    summary = out["summary"]

    assert summary["total"] == 3
    assert summary["live"] == 2
    assert summary["alarms"] == 1
    assert summary["worst_status"] == "critical"
    assert summary["worst_system"] == "bess-01"
    assert sum(summary["counts"].values()) == summary["total"]
    assert summary["total_power_w"] == -300.0
    # Worst-first ordering: the critical system leads.
    assert out["systems"][0]["system_id"] == "bess-01"


def test_empty_fleet():
    out = build_fleet([], {}, {}, {}, NOW, STALE)
    assert out["summary"]["total"] == 0
    assert out["summary"]["worst_system"] is None
    assert out["summary"]["counts"] == {"good": 0, "warning": 0, "serious": 0, "critical": 0}
    assert out["systems"] == []


# -- realistic, simulator-driven -------------------------------------------
def _final_envelopes(faults, duration=1400.0):
    """Run the sim + engines and return the last (tel, anomaly, assessment) envs."""
    pack = PackConfig(series=12, parallel=2, initial_soc=0.9)
    sim = SimConfig(dt_s=1.0, duration_s=duration)
    profile = ChargeDischargeCycle(discharge_a=20.0, charge_a=15.0)
    anomaly_engine = AnomalyEngine()
    assess_engine = AssessmentEngine()
    tel_dict = anom = asmt = None
    for tel in Simulator(pack, sim, profile, faults).run():
        a = anomaly_engine.update(tel)
        asmt = assess_engine.update(tel, a)
        tel_dict, anom = tel.to_dict(), a
    return (
        {"system_id": "bess-01", "timestamp": NOW.isoformat(), "telemetry": tel_dict},
        {"system_id": "bess-01", "timestamp": NOW.isoformat(), "anomaly": anom.to_dict()},
        {"system_id": "bess-01", "timestamp": NOW.isoformat(), "assessment": asmt.to_dict()},
    )


def test_internal_short_rolls_up_critical():
    tel, anom, asmt = _final_envelopes([InternalShort(cell=(3, 0), r_short_ohm=2.0, start_s=600)])
    row = roll_up_system("bess-01", "Pack 1", tel, anom, asmt, NOW, STALE)
    assert row["fault_type"] == "internal_short"
    assert row["status"] in ("serious", "critical")
    assert "Internal short" in row["status_reason"]


def test_healthy_run_rolls_up_good():
    tel, anom, asmt = _final_envelopes([])
    row = roll_up_system("bess-01", "Pack 1", tel, anom, asmt, NOW, STALE)
    assert row["status"] == "good"
    assert row["fault_type"] == "none"
