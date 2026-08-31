"""Machine-readable description of what a spec can contain.

Backs ``GET /api/builder/options`` so the dashboard can render the right form
controls (which profile types exist, which params each fault takes, sensible
defaults) without hard-coding them in two places. Keeping this next to the
builders means adding a profile or fault type is a one-file change.
"""

from __future__ import annotations

from typing import Any

from ..space import PLAN_PARAMS, PLAN_TYPES
from ..weather import WEATHER_PARAMS, WEATHER_TYPES
from .build import FAULT_TYPES, PROFILE_TYPES
from .spec import SystemSpec

# param name -> [default, label] for each profile type.
PROFILE_PARAMS: dict[str, dict[str, float]] = {
    "constant_current": {"amps": 10.0},
    "constant_power": {"watts": 1000.0},
    "cycle": {
        "discharge_a": 20.0,
        "charge_a": 15.0,
        "discharge_s": 1200.0,
        "charge_s": 1200.0,
        "rest_s": 300.0,
    },
    "sinusoidal": {"mean_a": 10.0, "amplitude_a": 5.0, "period_s": 600.0},
}

FAULT_PARAMS: dict[str, dict[str, float]] = {
    "internal_short": {"r_short_ohm": 2.0},
    "resistance_growth": {"multiplier": 3.0},
    "cooling_fault": {"effectiveness": 0.2},
    "thermal_runaway": {"trigger_c": 70.0, "scale_w": 5.0, "temp_slope_c": 15.0},
    "sensor_drift": {"offset": 0.1, "rate_per_s": 0.0},  # signal chosen separately
}

CHEMISTRIES = ("NMC", "LFP", "LCO", "NCA")


def builder_options() -> dict[str, Any]:
    """Everything the dashboard needs to render the builder form."""
    return {
        "chemistries": list(CHEMISTRIES),
        "profile_types": list(PROFILE_TYPES),
        "profile_params": PROFILE_PARAMS,
        "fault_types": list(FAULT_TYPES),
        "fault_params": FAULT_PARAMS,
        "sensor_signals": ["voltage", "temp"],
        "weather_types": list(WEATHER_TYPES),
        "weather_params": WEATHER_PARAMS,
        "space_types": list(PLAN_TYPES),
        "space_params": PLAN_PARAMS,
        "default_spec": SystemSpec(
            profile=_default_profile(),
        ).to_dict(),
    }


def _default_profile():
    from .spec import ProfileSpec

    return ProfileSpec(type="cycle", params=dict(PROFILE_PARAMS["cycle"]))
