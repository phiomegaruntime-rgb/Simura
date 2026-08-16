"""Declarative builders: turn plain JSON-serializable dicts into light objects.

This is what makes lighting *declarative* -- a luminaire, a fault, a control or a
whole installation can live in a JSON spec, an env var, or an API body and be
turned into live objects here. Mirrors :mod:`simura.wires.config` and
:func:`simura.weather.config.build_provider` in spirit.
"""

from __future__ import annotations

from typing import Any

from .catalog import FAMILIES, LAMP_CATALOG, TECHNOLOGIES
from .environment import DaylightHarvesting, LightEnvironmentCoupling, PhotocellControl
from .faults import (
    Burnout,
    DriverFault,
    Fault,
    Flicker,
    HeatsinkLoss,
    LensFouling,
    LumenDepreciation,
    PhosphorDegradation,
    SupplyVoltageFault,
)
from .lamp import LightSpec
from .photometry import TASK_ILLUMINANCE_LUX
from .profiles import (
    ConstantDrive,
    DriveProfile,
    OccupancyCycle,
    PwmDrive,
    Ramp,
    Schedule,
)

# Exposed for UIs / documentation / API enumerations.
LIGHT_TECHNOLOGIES = tuple(TECHNOLOGIES.keys())

# The injectable lighting failure modes, keyed by the id a spec/API body uses.
LIGHT_FAULT_TYPES = (
    "lumen_depreciation",
    "phosphor_degradation",
    "heatsink_loss",
    "driver_fault",
    "supply_voltage",
    "flicker",
    "lens_fouling",
    "burnout",
)

LIGHT_PROFILE_TYPES = ("constant", "schedule", "ramp", "pwm", "occupancy")

LIGHT_CONTROL_TYPES = ("none", "photocell", "daylight_harvesting")


def build_light(spec: dict[str, Any]) -> LightSpec:
    """Build a :class:`LightSpec` from a dict (ignoring unknown keys)."""
    return LightSpec.from_dict(spec)


def build_fault(spec: dict[str, Any]) -> Fault:
    """Build one :class:`~simura.lights.faults.Fault` from ``{"type", ...params}``.

    Mirrors :func:`simura.wires.config.build_fault`, so a failure mode can be named
    in a JSON body (an API call, a saved scenario) rather than constructed in code.
    """
    p = {k: v for k, v in spec.items() if k != "type"}
    window = {k: float(p[k]) for k in ("start_s", "end_s") if k in p}
    t = str(spec.get("type", ""))

    if t == "lumen_depreciation":
        return LumenDepreciation(
            rate_per_h=float(p.get("rate_per_h", 2e-4)),
            floor=float(p.get("floor", 0.2)),
            **window,
        )
    if t == "phosphor_degradation":
        return PhosphorDegradation(
            loss_frac=float(p.get("loss_frac", 0.25)),
            cct_shift_k=float(p.get("cct_shift_k", 600.0)),
            **window,
        )
    if t == "heatsink_loss":
        return HeatsinkLoss(r_th_mult=float(p.get("r_th_mult", 2.5)), **window)
    if t == "driver_fault":
        return DriverFault(
            current_mult=float(p.get("current_mult", 1.35)),
            efficiency_loss_frac=float(p.get("efficiency_loss_frac", 0.1)),
            **window,
        )
    if t == "supply_voltage":
        return SupplyVoltageFault(supply_mult=float(p.get("supply_mult", 0.9)), **window)
    if t == "flicker":
        return Flicker(
            depth=float(p.get("depth", 0.4)), freq_hz=float(p.get("freq_hz", 8.0)), **window
        )
    if t == "lens_fouling":
        return LensFouling(
            rate_per_h=float(p.get("rate_per_h", 1e-4)),
            max_loss_frac=float(p.get("max_loss_frac", 0.5)),
            **window,
        )
    if t == "burnout":
        return Burnout(**window)
    raise ValueError(
        f"unknown light fault type '{t}' (use one of {', '.join(LIGHT_FAULT_TYPES)})"
    )


def build_profile(spec: dict[str, Any]) -> DriveProfile:
    """Build a drive profile from ``{"type", ...params}``."""
    p = {k: v for k, v in spec.items() if k != "type"}
    t = str(spec.get("type", "constant"))

    if t == "constant":
        return ConstantDrive(level=float(p.get("level", 1.0)))
    if t == "schedule":
        return Schedule(
            start_s=float(p.get("start_s", 0.0)),
            on_s=float(p.get("on_s", 43200.0)),
            period_s=float(p.get("period_s", 86400.0)),
            level=float(p.get("level", 1.0)),
        )
    if t == "ramp":
        return Ramp(
            start_level=float(p.get("start_level", 0.0)),
            end_level=float(p.get("end_level", 1.0)),
            duration_s=float(p.get("duration_s", 60.0)),
            start_s=float(p.get("start_s", 0.0)),
        )
    if t == "pwm":
        return PwmDrive(
            duty=float(p.get("duty", 0.5)), freq_hz=float(p.get("freq_hz", 1000.0))
        )
    if t == "occupancy":
        return OccupancyCycle(
            interval_s=float(p.get("interval_s", 1800.0)),
            hold_s=float(p.get("hold_s", 600.0)),
            level=float(p.get("level", 1.0)),
        )
    raise ValueError(
        f"unknown drive profile '{t}' (use one of {', '.join(LIGHT_PROFILE_TYPES)})"
    )


def build_control(spec: dict[str, Any]):
    """Build an environment-driven control (``None`` for "none")."""
    if not spec:
        return None
    t = str(spec.get("type", "none"))
    p = {k: v for k, v in spec.items() if k != "type"}

    if t in ("none", ""):
        return None
    if t == "photocell":
        return PhotocellControl(
            switch_on_lux=float(p.get("switch_on_lux", 55.0)),
            hysteresis_frac=float(p.get("hysteresis_frac", 1.6)),
            level=float(p.get("level", 1.0)),
        )
    if t == "daylight_harvesting":
        return DaylightHarvesting(
            target_lux=float(p.get("target_lux", 500.0)),
            full_output_lux=float(p.get("full_output_lux", 500.0)),
            min_level=float(p.get("min_level", 0.0)),
            max_level=float(p.get("max_level", 1.0)),
        )
    raise ValueError(
        f"unknown light control '{t}' (use one of {', '.join(LIGHT_CONTROL_TYPES)})"
    )


def build_coupling(spec: dict[str, Any]) -> LightEnvironmentCoupling:
    """Build a :class:`LightEnvironmentCoupling` from a dict."""
    if not spec:
        return LightEnvironmentCoupling()
    known = {
        "outdoor", "wind_cooling_gain", "max_cooling_mult", "solar_absorptivity",
        "housing_area_m2", "window_transmission", "daylight_efficacy_lm_per_w",
    }
    return LightEnvironmentCoupling(**{k: v for k, v in spec.items() if k in known})


def catalog_options() -> dict[str, Any]:
    """Enumerations for a UI: technologies, lamps, faults, profiles, controls, tasks."""
    return {
        "families": list(FAMILIES),
        "technologies": [t.to_dict() for t in TECHNOLOGIES.values()],
        "lamp_types": [lamp.to_dict() for lamp in LAMP_CATALOG],
        "fault_types": list(LIGHT_FAULT_TYPES),
        "profile_types": list(LIGHT_PROFILE_TYPES),
        "control_types": list(LIGHT_CONTROL_TYPES),
        "tasks": {k: v for k, v in sorted(TASK_ILLUMINANCE_LUX.items())},
    }
