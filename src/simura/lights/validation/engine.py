"""The lighting validation engine: replay a reference through Simura's own model.

Given a :class:`~simura.lights.validation.reference.LightReference`, reproduce
every published point with the *same* code the twin uses, and report the gap.

We deliberately reuse :class:`simura.lights.Light` and
:mod:`simura.lights.spectrum` rather than re-deriving anything, so there is a
single source of physics truth -- exactly as the battery engine reuses
``BatteryPack`` and the wire engine reuses ``Wire``. A validation that runs its
own private copy of the physics validates nothing.

Errors are reported both ways round, because lighting quantities span very
different scales. Percent error is the right measure for efficacy (which ranges
from 10 to 150 lm/W across the catalog) and useless for ``V(lambda)`` in the far
red, where the published value is 0.001 and a rounding difference reads as 50%.
So every report carries absolute *and* relative metrics, and the caller can look
at whichever is honest for the quantity at hand.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..catalog import lamp_type_for
from ..lamp import Light, LightSpec
from ..spectrum import blackbody, photopic
from .reference import LightReference

# Quantities the engine knows how to reproduce.
QUANTITIES = (
    "photopic_response",
    "color_temperature",
    "luminous_efficacy",
    "flux_vs_junction_temp",
    "flux_vs_ambient_temp",
    "daylight_illuminance",
)


@dataclass
class LightValidationReport:
    """The outcome of validating the lighting model against one reference."""

    standard_id: str
    quantity: str
    n_points: int
    unit: str
    x_label: str
    x_unit: str
    data_source: str                 # "bundled-standard" | "user-upload" | "live-measurement"
    metrics: dict[str, float]        # rmse/mae (absolute) + rmse_pct/mae_pct/max/bias
    overlay: dict[str, list]         # x / key / published / model / error / error_pct
    notes: str = ""
    filename: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Per-quantity model evaluation. Each returns Simura's own prediction for one
# published row, using the same objects the twin runs on.
# ---------------------------------------------------------------------------

def _model_photopic(row) -> float:
    """``V(lambda)`` from the analytic colour-matching fit."""
    return photopic(row.x)


def _model_color_temperature(row) -> float:
    """CCT the model assigns to a blackbody at the reference temperature."""
    return blackbody(row.x).cct_k()


def _model_luminous_efficacy(row) -> float:
    """Whole-lamp efficacy, predicted from the physics for one catalog lamp.

    Built exactly as the twin builds it -- catalog lamp, reference ambient, fully
    warmed up, brand new -- and asked what it delivers. The published flux the
    catalog carries is never consulted.
    """
    lamp_id = row.context or row.key
    lamp_type_for(lamp_id)                      # raises on an unknown lamp id
    light = Light(LightSpec(lamp_type=lamp_id))
    light.time_lit_s = 1e9                      # warm-up complete
    return light.operating_point(1.0, 25.0).efficacy_lm_per_w


def _model_flux_vs_junction_temp(row) -> float:
    """Relative LED flux at a junction temperature, normalised to 25 °C."""
    light = Light(LightSpec(technology="led", power_w=10.0))
    ref = light.junction_output_factor(25.0)
    return light.junction_output_factor(row.x) / ref if ref else 0.0


def _model_flux_vs_ambient_temp(row) -> float:
    """Relative fluorescent output at an ambient temperature, normalised to 25 °C."""
    light = Light(LightSpec(technology="fluorescent_t8", power_w=36.0))
    ref = light.ambient_output_factor(25.0)
    return light.ambient_output_factor(row.x) / ref if ref else 0.0


def _model_daylight_illuminance(row) -> float:
    """Clear-sky daylight illuminance predicted from solar geometry alone.

    ``row.x`` is the sun's elevation in degrees; see
    :mod:`simura.lights.validation.live` for where those come from.
    """
    from ..environment import clear_sky_ghi_w_m2, daylight_illuminance_lux

    return daylight_illuminance_lux(clear_sky_ghi_w_m2(row.x))


_MODELS = {
    "photopic_response": _model_photopic,
    "color_temperature": _model_color_temperature,
    "luminous_efficacy": _model_luminous_efficacy,
    "flux_vs_junction_temp": _model_flux_vs_junction_temp,
    "flux_vs_ambient_temp": _model_flux_vs_ambient_temp,
    "daylight_illuminance": _model_daylight_illuminance,
}


def validate_reference(ref: LightReference) -> LightValidationReport:
    """Validate the Simura lighting model against one reference.

    Replays every published point through Simura's own physics and reports the
    per-point error plus RMSE / MAE / max / mean-bias summaries, in both absolute
    units and percent. The overlay carries the published and modelled curves for
    plotting.
    """
    model_fn = _MODELS.get(ref.quantity)
    if model_fn is None:
        raise ValueError(
            f"cannot validate quantity '{ref.quantity}' "
            f"(known: {', '.join(sorted(_MODELS))})"
        )

    xs: list[float] = []
    keys: list[str] = []
    published: list[float] = []
    model: list[float] = []
    error: list[float] = []
    error_pct: list[float] = []

    for row in ref.rows:
        m = float(model_fn(row))
        err = m - row.published
        xs.append(float(row.x))
        keys.append(row.key)
        published.append(float(row.published))
        model.append(m)
        error.append(err)
        error_pct.append(
            (err / row.published * 100.0) if row.published not in (0.0, -0.0) else 0.0
        )

    n = len(error)
    abs_err = [abs(e) for e in error]
    abs_pct = [abs(e) for e in error_pct]
    metrics = {
        "rmse": round((sum(e * e for e in error) / n) ** 0.5, 6),
        "mae": round(sum(abs_err) / n, 6),
        "max_abs": round(max(abs_err), 6),
        "mean_bias": round(sum(error) / n, 6),
        "rmse_pct": round((sum(e * e for e in error_pct) / n) ** 0.5, 4),
        "mae_pct": round(sum(abs_pct) / n, 4),
        "max_abs_pct": round(max(abs_pct), 4),
        "mean_bias_pct": round(sum(error_pct) / n, 4),
    }

    return LightValidationReport(
        standard_id=ref.standard_id,
        quantity=ref.quantity,
        n_points=n,
        unit=ref.unit,
        x_label=ref.x_label,
        x_unit=ref.x_unit,
        data_source=ref.data_source,
        metrics=metrics,
        overlay={
            "x": [round(v, 4) for v in xs],
            "key": keys,
            "published": [round(v, 6) for v in published],
            "model": [round(v, 6) for v in model],
            "error": [round(v, 6) for v in error],
            "error_pct": [round(v, 4) for v in error_pct],
        },
        notes=ref.notes,
    )
