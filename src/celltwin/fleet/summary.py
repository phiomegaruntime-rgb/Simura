"""Fleet rollup: many per-system twins -> one at-a-glance view.

Pure functions over the plain envelope dicts the twin core already holds in its
live caches (telemetry / anomaly / assessment) plus the ``systems`` registry
rows. No DB, no broker, no FastAPI here -- so the whole rollup is unit-tested
against hand-built envelopes and the simulator's fault scenarios, exactly like
:mod:`celltwin.detect` and :mod:`celltwin.health`.

The per-system ``status`` combines the same signals the single-system dashboard
does (temperature, imbalance, anomaly, safety), and ``status_reason`` follows the
same precedence (safety alarm > diagnosis > early warning > nominal), so the
fleet card and the detail view never disagree.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .levels import (
    Level,
    LEVEL_ORDER,
    anomaly_level,
    fault_label,
    imbalance_level,
    safety_level,
    temp_level,
    worst,
)


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _cell_label(series: Any, parallel: Any) -> Optional[str]:
    if series is None or parallel is None:
        return None
    return f"module {series} · slot {parallel}"


def roll_up_system(
    system_id: str,
    name: Optional[str],
    telemetry_env: Optional[dict[str, Any]],
    anomaly_env: Optional[dict[str, Any]],
    assessment_env: Optional[dict[str, Any]],
    now: datetime,
    stale_after_s: float,
    source: str = "realtime",
    run_state: str = "running",
) -> dict[str, Any]:
    """Condense one system's latest envelopes into a single status row."""
    tel = (telemetry_env or {}).get("telemetry") or {}
    anomaly = (anomaly_env or {}).get("anomaly") or {}
    assessment = (assessment_env or {}).get("assessment") or {}
    diag = assessment.get("diagnosis") or {}

    ts = _parse_timestamp((telemetry_env or {}).get("timestamp"))
    age_s = (now - ts).total_seconds() if ts is not None else None
    # Live if we have a fresh telemetry frame. If the timestamp is unparseable we
    # fall back to "present in cache" rather than wrongly marking it offline.
    if telemetry_env is None:
        live = False
    elif age_s is None:
        live = True
    else:
        live = age_s <= stale_after_s

    row: dict[str, Any] = {
        "system_id": system_id,
        "name": name,
        "source": source,
        "run_state": run_state,
        "live": live,
        "age_s": age_s,
        "updated_at": ts.isoformat() if ts is not None else None,
        "pack_soc": tel.get("pack_soc"),
        "pack_power_w": tel.get("pack_power_w"),
        "max_temp_c": tel.get("max_temp_c"),
        "voltage_imbalance_v": tel.get("voltage_imbalance_v"),
        "anomaly_score": anomaly.get("max_score"),
        "flagged_count": anomaly.get("flagged_count"),
        "worst_cell": _cell_label(anomaly.get("worst_series"), anomaly.get("worst_parallel")),
        "pack_soh": assessment.get("pack_soh"),
        "fault_type": diag.get("fault_type"),
        "confidence": diag.get("confidence"),
        "safety_state": assessment.get("safety_state"),
        "min_time_to_critical_s": assessment.get("min_time_to_critical_s"),
    }

    if telemetry_env is None:
        row["status"] = "good"
        row["status_reason"] = "No telemetry received yet."
        return row

    # Overall status: the worst of the signals we actually have. Absent analytics
    # simply don't contribute (a system with telemetry but no assessment yet
    # still rolls up on temperature and balance).
    levels: list[Level] = []
    if tel.get("max_temp_c") is not None:
        levels.append(temp_level(tel["max_temp_c"]))
    if tel.get("voltage_imbalance_v") is not None:
        levels.append(imbalance_level(tel["voltage_imbalance_v"]))
    anom_score = anomaly.get("max_score")
    anom_lvl: Level = anomaly_level(anom_score) if anom_score is not None else "good"
    if anom_score is not None:
        levels.append(anom_lvl)
    if assessment.get("safety_state") is not None:
        levels.append(safety_level(assessment["safety_state"]))
    row["status"] = worst(*levels)

    row["status_reason"] = _status_reason(assessment, diag, anomaly, anom_lvl)
    return row


def _status_reason(
    assessment: dict[str, Any],
    diag: dict[str, Any],
    anomaly: dict[str, Any],
    anom_lvl: Level,
) -> str:
    """Human-readable one-liner, same precedence as the single-system banner."""
    cell = _cell_label(diag.get("cell_series"), diag.get("cell_parallel"))
    if assessment.get("safety_state") == "alarm":
        where = f" at {cell}" if cell else ""
        return f"SAFETY ALARM — thermal-runaway conditions{where}"
    fault = diag.get("fault_type")
    if fault and fault != "none":
        conf = diag.get("confidence")
        pct = f" ({conf * 100:.0f}% confidence)" if isinstance(conf, (int, float)) else ""
        where = f" at {cell}" if cell else ""
        return f"{fault_label(fault)}{where}{pct}"
    if anomaly and anom_lvl != "good":
        worst_cell = _cell_label(anomaly.get("worst_series"), anomaly.get("worst_parallel"))
        driver = anomaly.get("worst_driver")
        score = anomaly.get("max_score")
        sigma = f" ({score:.1f} σ)" if isinstance(score, (int, float)) else ""
        where = f"{worst_cell} " if worst_cell else ""
        return f"Early warning: {where}deviating on {driver}{sigma}"
    return "All cells within nominal temperature, balance, and peer behavior."


def build_fleet(
    systems: list[dict[str, Any]],
    telemetry_live: dict[str, dict[str, Any]],
    anomaly_live: dict[str, dict[str, Any]],
    assessment_live: dict[str, dict[str, Any]],
    now: datetime,
    stale_after_s: float,
) -> dict[str, Any]:
    """Roll the whole fleet up into ``{"summary": ..., "systems": [...]}``.

    ``systems`` are the registry rows (``system_id``/``name``/...); the three
    ``*_live`` maps are ``{system_id: envelope}`` from the live caches. Systems
    are ordered worst-first (then by id) so the ones needing attention lead.
    """
    rows = [
        roll_up_system(
            s["system_id"],
            s.get("name"),
            telemetry_live.get(s["system_id"]),
            anomaly_live.get(s["system_id"]),
            assessment_live.get(s["system_id"]),
            now,
            stale_after_s,
            source=s.get("source", "realtime"),
            run_state=s.get("run_state", "running"),
        )
        for s in systems
    ]
    rows.sort(key=lambda r: (-LEVEL_ORDER[r["status"]], r["system_id"]))

    counts = {"good": 0, "warning": 0, "serious": 0, "critical": 0}
    total_power = 0.0
    alarms = 0
    live = 0
    worst_status: Level = "good"
    worst_system: Optional[str] = None
    for r in rows:
        counts[r["status"]] += 1
        if r["live"]:
            live += 1
        if isinstance(r["pack_power_w"], (int, float)):
            total_power += r["pack_power_w"]
        if r["safety_state"] == "alarm":
            alarms += 1
        if LEVEL_ORDER[r["status"]] > LEVEL_ORDER[worst_status]:
            worst_status = r["status"]
            worst_system = r["system_id"]

    summary = {
        "total": len(rows),
        "live": live,
        "counts": counts,
        "worst_status": worst_status,
        "worst_system": worst_system,
        "total_power_w": total_power,
        "alarms": alarms,
    }
    return {"summary": summary, "systems": rows}
