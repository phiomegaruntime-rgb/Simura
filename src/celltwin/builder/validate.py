"""Validate a :class:`~celltwin.builder.spec.SystemSpec` before building it.

Returns a list of human-readable problems (empty == valid). This is deliberately
separate from construction so the dashboard can show errors *as the user types*
without ever instantiating a simulator, and the API can reject a bad spec with a
clear message instead of a stack trace.
"""

from __future__ import annotations

from ..sim import chemistry_key_for
from ..weather import WEATHER_TYPES
from .build import FAULT_TYPES, PROFILE_TYPES
from .spec import SystemSpec

# Guardrail so a runaway spec (tiny dt, huge duration) can't lock up a preview.
MAX_STEPS = 200_000


def validate_spec(spec: SystemSpec) -> list[str]:
    """Return a list of validation errors (empty means the spec is runnable)."""
    errors: list[str] = []

    if not spec.system_id.strip():
        errors.append("system_id must not be empty")

    # Topology.
    if spec.series < 1:
        errors.append("series must be >= 1")
    if spec.parallel < 1:
        errors.append("parallel must be >= 1")

    # Cell parameters.
    if spec.capacity_ah <= 0:
        errors.append("capacity_ah must be > 0")
    if spec.r0_ohm <= 0:
        errors.append("r0_ohm must be > 0")
    if spec.r1_ohm < 0:
        errors.append("r1_ohm must be >= 0")
    if spec.c1_farad <= 0:
        errors.append("c1_farad must be > 0")
    if not 0 < spec.coulombic_eff <= 1:
        errors.append("coulombic_eff must be in (0, 1]")
    if spec.thermal_capacity_j_per_k <= 0:
        errors.append("thermal_capacity_j_per_k must be > 0")
    if spec.cooling_conductance_w_per_k < 0:
        errors.append("cooling_conductance_w_per_k must be >= 0")
    if spec.v_min >= spec.v_max:
        errors.append("v_min must be < v_max")
    if spec.temp_max_c <= spec.ambient_temp_c:
        errors.append("temp_max_c must be > ambient_temp_c")

    # Initial conditions.
    if not 0 <= spec.initial_soc <= 1:
        errors.append("initial_soc must be in [0, 1]")
    for name in ("capacity_spread", "resistance_spread", "initial_soc_spread"):
        if getattr(spec, name) < 0:
            errors.append(f"{name} must be >= 0")

    # Chemistry (unknown is allowed but warned -- it falls back to NMC).
    if chemistry_key_for(spec.chemistry) is None:
        errors.append(
            f"unknown chemistry '{spec.chemistry}'; use one of NMC, LFP, LCO, NCA "
            "(it would fall back to the NMC curve)"
        )

    # Simulation loop.
    if spec.dt_s <= 0:
        errors.append("dt_s must be > 0")
    if spec.duration_s <= 0:
        errors.append("duration_s must be > 0")
    if spec.dt_s > 0 and spec.n_steps() > MAX_STEPS:
        errors.append(
            f"duration/dt = {spec.n_steps()} steps exceeds the {MAX_STEPS} cap; "
            "increase dt_s or shorten duration_s"
        )
    if spec.dt_s > 0 and spec.n_steps() < 1:
        errors.append("duration_s must be at least one dt_s step")

    # Profile.
    if spec.profile.type not in PROFILE_TYPES:
        errors.append(
            f"unknown profile type '{spec.profile.type}'; use one of {', '.join(PROFILE_TYPES)}"
        )
    else:
        errors.extend(_profile_param_errors(spec))

    # Weather (optional environmental source).
    errors.extend(_weather_errors(spec))

    # Faults.
    for i, f in enumerate(spec.faults):
        where = f"fault[{i}]"
        if f.type not in FAULT_TYPES:
            errors.append(f"{where}: unknown type '{f.type}'")
        if not 0 <= f.series < spec.series:
            errors.append(f"{where}: series {f.series} out of range [0, {spec.series})")
        if not 0 <= f.parallel < spec.parallel:
            errors.append(f"{where}: parallel {f.parallel} out of range [0, {spec.parallel})")
        if f.start_s < 0:
            errors.append(f"{where}: start_s must be >= 0")
        if f.type == "sensor_drift":
            sig = f.params.get("signal", "voltage")
            if sig not in ("voltage", "temp"):
                errors.append(f"{where}: sensor_drift signal must be 'voltage' or 'temp'")

    return errors


def _weather_errors(spec: SystemSpec) -> list[str]:
    w = getattr(spec, "weather", None)
    if w is None:
        return []
    errs: list[str] = []
    if w.type not in WEATHER_TYPES:
        errs.append(
            f"unknown weather type '{w.type}'; use one of {', '.join(WEATHER_TYPES)}"
        )
        return errs
    p = w.params or {}
    if w.type == "open_meteo":
        for coord, lo, hi in (("latitude", -90.0, 90.0), ("longitude", -180.0, 180.0)):
            if coord not in p:
                errs.append(f"weather open_meteo requires '{coord}'")
            else:
                try:
                    val = float(p[coord])
                except (TypeError, ValueError):
                    errs.append(f"weather open_meteo '{coord}' must be a number")
                    continue
                if not lo <= val <= hi:
                    errs.append(f"weather open_meteo '{coord}' must be in [{lo}, {hi}]")
        mode = str(p.get("mode", "forecast"))
        if mode not in ("forecast", "archive"):
            errs.append("weather open_meteo 'mode' must be 'forecast' or 'archive'")
        if mode == "archive" and not (p.get("start_date") and p.get("end_date")):
            errs.append("weather open_meteo archive mode needs 'start_date' and 'end_date'")
    if w.type == "csv" and not str(p.get("path", "")).strip():
        errs.append("weather csv requires a 'path'")
    return errs


def _profile_param_errors(spec: SystemSpec) -> list[str]:
    p = spec.profile.params
    t = spec.profile.type
    errs: list[str] = []
    if t == "constant_power" and float(p.get("watts", 1000.0)) == 0:
        errs.append("profile: constant_power watts should be non-zero")
    if t == "cycle":
        for k in ("discharge_s", "charge_s", "rest_s"):
            if float(p.get(k, 1.0)) < 0:
                errs.append(f"profile: cycle {k} must be >= 0")
    if t == "sinusoidal" and float(p.get("period_s", 600.0)) <= 0:
        errs.append("profile: sinusoidal period_s must be > 0")
    return errs
