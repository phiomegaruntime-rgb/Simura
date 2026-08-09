"""The wire validation engine: replay a resistance standard through Simura's model.

Given a :class:`~simura.wires.validation.reference.WireReference` (a published
DC-resistance-by-gauge table), build the *same* :class:`simura.wires.Wire` the
twin uses for each gauge, ask it for its predicted resistance at the reference
temperature, and compare against the published value. The gap -- as a percentage,
because resistance spans two orders of magnitude across the gauges -- is the
validation result: how faithful the conductor physics is against the standard.

We deliberately reuse ``Wire`` (rather than re-deriving ``rho·L/A``) so there is a
single source of physics truth, exactly as the battery engine reuses
``BatteryPack``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..wire import Wire, WireSpec
from .reference import WireReference


@dataclass
class WireValidationReport:
    """The outcome of validating the wire model against one reference standard."""

    standard_id: str
    material: str
    ref_temp_c: float
    n_points: int
    quantity: str
    unit: str
    data_source: str                 # "bundled-standard" | "user-upload"
    metrics: dict[str, float]        # rmse_pct / mae_pct / max_abs_pct / mean_bias_pct
    overlay: dict[str, list[float]]  # awg / area_mm2 / published / model / error_pct
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _model_ohm_per_km(material: str, awg: int, ref_temp_c: float) -> float:
    """Simura's predicted DC resistance (Ω/km) for one gauge at ``ref_temp_c``."""
    # One metre of conductor at the reference temperature -> Ω/m, scaled to Ω/km.
    wire = Wire(WireSpec(material=material, awg=awg, length_m=1.0, ambient_temp_c=ref_temp_c))
    return wire.resistance_ohm(ref_temp_c) * 1000.0


def validate_reference(ref: WireReference) -> WireValidationReport:
    """Validate the Simura wire model against one published resistance table.

    Replays every gauge in ``ref`` through a Simura :class:`Wire` and reports the
    per-gauge percent error plus RMSE / MAE / max / mean-bias summaries (all in
    percent). The overlay carries the published and modelled curves for plotting.
    """
    awg: list[float] = []
    area: list[float] = []
    published: list[float] = []
    model: list[float] = []
    error_pct: list[float] = []

    for row in ref.rows:
        m = _model_ohm_per_km(ref.material, row.awg, ref.ref_temp_c)
        err = (m - row.published_ohm_per_km) / row.published_ohm_per_km * 100.0
        awg.append(float(row.awg))
        area.append(float(row.area_mm2))
        published.append(float(row.published_ohm_per_km))
        model.append(float(m))
        error_pct.append(float(err))

    n = len(error_pct)
    abs_err = [abs(e) for e in error_pct]
    rmse = (sum(e * e for e in error_pct) / n) ** 0.5
    metrics = {
        "rmse_pct": round(rmse, 4),
        "mae_pct": round(sum(abs_err) / n, 4),
        "max_abs_pct": round(max(abs_err), 4),
        "mean_bias_pct": round(sum(error_pct) / n, 4),
    }

    return WireValidationReport(
        standard_id=ref.standard_id,
        material=ref.material,
        ref_temp_c=ref.ref_temp_c,
        n_points=n,
        quantity=ref.quantity,
        unit=ref.unit,
        data_source=ref.data_source,
        metrics=metrics,
        overlay={
            "awg": awg,
            "area_mm2": area,
            "published_ohm_per_km": [round(v, 5) for v in published],
            "model_ohm_per_km": [round(v, 5) for v in model],
            "error_pct": [round(v, 4) for v in error_pct],
        },
        notes=ref.notes,
    )
