"""Real-time validation: the daylight model against live measured irradiance.

Every other standard in this package is a *bundled* table -- reference data that
sits in the repository and never changes. This one is different: it validates the
model against **what the sky is actually doing right now**, over a real place,
using the same free [Open-Meteo](https://open-meteo.com) source
:mod:`simura.weather` already provides. No API key, no download, no fixture.

What is being validated
-----------------------

The daylight chain in :mod:`simura.lights.environment` is three steps of pure
physics with no fitted parameters::

    sun elevation   h    = f(latitude, longitude, timestamp)     [astronomy]
    clear-sky GHI        = 1098 * sin(h) * exp(-0.059 / sin(h))  [Haurwitz]
    illuminance          = GHI * 110 lm/W                        [daylight efficacy]

Open-Meteo reports the measured/analysed shortwave radiation for the same place
and hours, which converts to illuminance the same way. Comparing them tests
whether the geometry and the efficacy constant are right.

Reading the result honestly
---------------------------

A clear-sky model has no way to know about clouds, so on an overcast day it will
over-predict badly -- and that is not a defect, it is the definition of the model.
The report is therefore built to separate the two things:

* **clearness index** ``kt = measured / clear-sky`` per hour. Near 1.0 is a clear
  hour; 0.2 is heavy overcast.
* **the clear-hour metrics** restrict the error to the clearest hours in the
  window, which is the honest test of the geometry and the efficacy constant.
* **the envelope check** counts hours where the measurement *exceeded* the
  clear-sky ceiling by more than a tolerance. Those should be rare -- cloud
  edge-brightening does it occasionally -- and a lot of them would mean the
  clear-sky model is systematically too low.
* **all-hours metrics** are reported too, and are dominated by weather rather
  than by the model. They are the number that shows how cloudy the window was.

So: judge the model on the clear-hour metrics and the envelope violations; read
the all-hours error as a measurement of the sky, not of the code.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from ...weather.providers import OpenMeteoProvider
from ..environment import (
    K_DAYLIGHT_LM_PER_W,
    clear_sky_ghi_w_m2,
    daylight_illuminance_lux,
    solar_elevation_deg,
)

# Sun elevations below this are twilight or night: the clear-sky model is not
# meaningful there and the illuminances involved are irrelevant to lighting.
MIN_ELEVATION_DEG = 5.0

# A measured hour counts as "clear" above this clearness index.
CLEAR_KT = 0.75

# How far a measurement may exceed the clear-sky ceiling before it counts as a
# violation. Cloud edge-brightening genuinely does push global horizontal
# irradiance a little above the clear-sky value for short periods.
ENVELOPE_TOLERANCE = 1.10


@dataclass
class LiveDaylightReport:
    """The outcome of validating the daylight model against live measurements."""

    latitude: float
    longitude: float
    source: str
    n_hours: int                     # daylight hours in the window
    n_clear_hours: int
    window_start: float              # epoch seconds
    window_end: float
    metrics: dict[str, float]
    overlay: dict[str, list]         # timestamp / elevation / measured / model / kt
    envelope_violations: int
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


def validate_daylight_live(
    latitude: float,
    longitude: float,
    hours: int = 48,
    provider: Optional[OpenMeteoProvider] = None,
    now_epoch: float | None = None,
    daylight_efficacy_lm_per_w: float = K_DAYLIGHT_LM_PER_W,
) -> LiveDaylightReport:
    """Validate the clear-sky daylight model against live Open-Meteo irradiance.

    Fetches the last ``hours`` of measured/analysed shortwave radiation for
    ``latitude``/``longitude``, computes the sun's elevation for each of those
    hours from first principles, predicts the clear-sky illuminance, and compares.

    ``provider`` is injectable so this is unit-testable against a saved payload
    with no network call -- the same seam
    :class:`~simura.weather.providers.OpenMeteoProvider` uses everywhere else.
    """
    now = time.time() if now_epoch is None else now_epoch
    wx = provider or OpenMeteoProvider(
        latitude=latitude, longitude=longitude, mode="forecast",
        past_days=max(1, hours // 24 + 1), forecast_days=1,
    )

    start = now - hours * 3600.0
    timestamps: list[float] = []
    elevations: list[float] = []
    measured: list[float] = []
    model: list[float] = []
    clearness: list[float] = []
    source = ""

    for i in range(hours):
        ts = start + i * 3600.0
        elevation = solar_elevation_deg(latitude, longitude, ts)
        if elevation < MIN_ELEVATION_DEG:
            continue                        # night and twilight are not the test

        sample = wx.at(ts)
        source = sample.source or source
        measured_lux = daylight_illuminance_lux(
            sample.solar_w_m2, efficacy_lm_per_w=daylight_efficacy_lm_per_w
        )
        clear_ghi = clear_sky_ghi_w_m2(elevation)
        model_lux = daylight_illuminance_lux(
            clear_ghi, efficacy_lm_per_w=daylight_efficacy_lm_per_w
        )
        if model_lux <= 0:
            continue

        timestamps.append(ts)
        elevations.append(elevation)
        measured.append(measured_lux)
        model.append(model_lux)
        clearness.append(sample.solar_w_m2 / clear_ghi if clear_ghi > 0 else 0.0)

    n = len(model)
    if n < 2:
        raise ValueError(
            "not enough daylight hours in the window to validate — widen `hours` "
            "or pick a place where the sun rises above 5°"
        )

    clear_idx = [i for i in range(n) if clearness[i] >= CLEAR_KT]
    violations = sum(1 for i in range(n) if clearness[i] > ENVELOPE_TOLERANCE)

    metrics = {
        **_error_metrics(measured, model, prefix=""),
        **_error_metrics(
            [measured[i] for i in clear_idx],
            [model[i] for i in clear_idx],
            prefix="clear_",
        ),
        "mean_clearness_index": round(sum(clearness) / n, 4),
        "clear_hour_frac": round(len(clear_idx) / n, 4),
    }

    return LiveDaylightReport(
        latitude=latitude,
        longitude=longitude,
        source=source or "open-meteo",
        n_hours=n,
        n_clear_hours=len(clear_idx),
        window_start=round(timestamps[0], 1),
        window_end=round(timestamps[-1], 1),
        metrics=metrics,
        overlay={
            "timestamp": [round(t, 1) for t in timestamps],
            "elevation_deg": [round(e, 3) for e in elevations],
            "measured_lux": [round(v, 1) for v in measured],
            "model_lux": [round(v, 1) for v in model],
            "clearness_index": [round(v, 4) for v in clearness],
        },
        envelope_violations=violations,
        notes=(
            "Clear-sky model against measured irradiance. Judge it on the "
            "clear-hour metrics and the envelope violations; the all-hours error "
            "measures how cloudy the window was, not how good the model is."
        ),
    )


def _error_metrics(measured: list[float], model: list[float], prefix: str) -> dict[str, float]:
    """RMSE / MAE / bias, absolute and relative, for one subset of hours."""
    n = len(model)
    if n == 0:
        return {
            f"{prefix}rmse_lux": 0.0, f"{prefix}mae_lux": 0.0,
            f"{prefix}mean_bias_lux": 0.0, f"{prefix}rmse_pct": 0.0,
            f"{prefix}mean_bias_pct": 0.0, f"{prefix}n": 0,
        }
    errs = [model[i] - measured[i] for i in range(n)]
    pcts = [
        (errs[i] / measured[i] * 100.0) if measured[i] > 0 else 0.0 for i in range(n)
    ]
    return {
        f"{prefix}rmse_lux": round((sum(e * e for e in errs) / n) ** 0.5, 1),
        f"{prefix}mae_lux": round(sum(abs(e) for e in errs) / n, 1),
        f"{prefix}mean_bias_lux": round(sum(errs) / n, 1),
        f"{prefix}rmse_pct": round((sum(p * p for p in pcts) / n) ** 0.5, 2),
        f"{prefix}mean_bias_pct": round(sum(pcts) / n, 2),
        f"{prefix}n": n,
    }
