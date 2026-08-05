"""The validation engine: replay measured current through CellTwin's own model.

Given a :class:`~celltwin.validate.reference.ReferenceRun` (real measured current
+ terminal voltage), we drive a *single* CellTwin cell -- the exact same
electro-thermal model the twin uses (:class:`celltwin.sim.pack.BatteryPack`,
1x1) -- with the measured current and compare the model's predicted terminal
voltage against what was actually measured. The gap (RMSE / MAE / max / bias) is
the validation result: how faithful the physics is on real data.

We deliberately reuse ``BatteryPack`` rather than re-deriving the equations so
there is a single source of physics truth. The pack's OCV-SoC curve is swapped to
match the cell chemistry (NMC/LFP/LCO/NCA, chosen from the reference's
``chemistry`` label via :func:`celltwin.sim.ocv.ocv_table_for`), so an LFP cell is
validated against the LFP curve rather than the NMC default. The report records
which curve was used in ``ocv_curve``/``notes``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

import numpy as np

from ..sim import (
    BatteryPack,
    CellParams,
    PackConfig,
    chemistry_key_for,
    make_ocv,
    make_soc_from_ocv,
    ocv_table_for,
)

OcvTable = list[tuple[float, float]]


@dataclass
class ValidationReport:
    """The outcome of validating the model against one reference run."""

    dataset_id: str
    cell_id: str
    chemistry: str
    n_samples: int
    duration_s: float
    data_source: str                      # "user-file" | "bundled-synthetic-demo"
    params: dict[str, float]              # model params used (r0, capacity, soc0, ...)
    metrics: dict[str, float]             # rmse/mae/max_abs_err/mean_bias (volts)
    overlay: dict[str, list[float]]       # downsampled t / v_measured / v_model
    fitted: Optional[dict[str, Any]] = None   # present when fit=True
    notes: str = ""
    ocv_curve: str = "NMC"                # which chemistry OCV curve was used

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _initial_soc(ref, table: OcvTable) -> float:
    """Estimate starting SoC from the first sample via the inverse OCV curve.

    Exact only at rest; the datasets we target begin from a rest/soak step, so
    the first terminal voltage is very close to OCV. Uses the chemistry's own OCV
    curve (LFP's flat plateau makes this ill-conditioned mid-charge -- the fit
    scan compensates). Clamped away from the rails.
    """
    soc_from_ocv = make_soc_from_ocv(table)
    soc0 = float(soc_from_ocv(np.asarray([ref.voltage_v[0]]))[0])
    return float(np.clip(soc0, 0.02, 0.98))


def _replay(ref, r0_ohm: float, soc0: float, table: OcvTable) -> np.ndarray:
    """Predict terminal voltage over the run by stepping a 1x1 pack with measured current."""
    cfg = PackConfig(
        series=1,
        parallel=1,
        cell=CellParams(capacity_ah=ref.nominal_capacity_ah, r0_ohm=r0_ohm),
        capacity_spread=0.0,
        resistance_spread=0.0,
        initial_soc=soc0,
        initial_soc_spread=0.0,
        ambient_temp_c=ref.ambient_temp_c,
        seed=0,
    )
    pack = BatteryPack(cfg)
    # Use the chemistry's OCV curve instead of the pack's built-in NMC default,
    # then re-seed the diagnostic voltage so it reflects the swapped curve.
    pack.ocv = make_ocv(table)
    pack.cell_voltage_v = pack.ocv(pack.soc).copy()
    t = ref.time_s
    model_v = np.empty(ref.n_samples, dtype=float)
    for i in range(ref.n_samples):
        dt = (t[i] - t[i - 1]) if i > 0 else (t[1] - t[0])
        if dt <= 0:
            dt = ref.dt_s()
        pack.step(float(ref.current_a[i]), float(dt))
        model_v[i] = float(pack.cell_voltage_v[0, 0])
    return model_v


def _metrics(measured: np.ndarray, model: np.ndarray) -> dict[str, float]:
    err = model - measured
    return {
        "rmse": float(np.sqrt(np.mean(err**2))),
        "mae": float(np.mean(np.abs(err))),
        "max_abs_err": float(np.max(np.abs(err))),
        "mean_bias": float(np.mean(err)),
    }


def _fit(ref, soc0: float, table: OcvTable) -> tuple[dict[str, Any], np.ndarray]:
    """Coarse joint scan over R0 and a small initial-SoC offset, minimizing RMSE.

    Shows how well the model *can* match once its two most sensitive knobs are
    tuned -- a fairer read on the physics than fixed nominal params, reported
    alongside (not instead of) the nominal result.
    """
    best = None
    best_v = None
    for r0 in np.linspace(0.005, 0.060, 12):
        for dsoc in np.linspace(-0.06, 0.06, 7):
            s0 = float(np.clip(soc0 + dsoc, 0.02, 0.98))
            model_v = _replay(ref, float(r0), s0, table)
            m = _metrics(ref.voltage_v, model_v)
            if best is None or m["rmse"] < best["metrics"]["rmse"]:
                best = {"r0_ohm": float(r0), "soc0": s0, "metrics": m}
                best_v = model_v
    return best, best_v


def validate_run(
    ref,
    *,
    r0_ohm: float = 0.020,
    soc0: Optional[float] = None,
    chemistry: Optional[str] = None,
    ocv_table: Optional[OcvTable] = None,
    fit: bool = False,
    data_source: str = "user-file",
    max_overlay_points: int = 400,
) -> ValidationReport:
    """Validate the CellTwin model against one reference run.

    Replays ``ref.current_a`` through a 1x1 CellTwin cell and compares predicted
    terminal voltage to ``ref.voltage_v``. The OCV-SoC curve is chosen to match
    the cell chemistry (``ocv_table`` wins; else ``chemistry``; else
    ``ref.chemistry``), so LFP/LCO/NCA cells validate against the right curve
    rather than the NMC default. With ``fit=True`` it also reports the best-fit
    R0 / initial-SoC result. ``r0_ohm`` and ``soc0`` seed the nominal run.
    """
    chem = chemistry if chemistry is not None else ref.chemistry
    table = ocv_table if ocv_table is not None else ocv_table_for(chem)
    matched_key = None if ocv_table is not None else chemistry_key_for(chem)

    soc_start = _initial_soc(ref, table) if soc0 is None else float(soc0)
    model_v = _replay(ref, r0_ohm, soc_start, table)
    metrics = _metrics(ref.voltage_v, model_v)

    idx = ref._overlay_index(max_overlay_points)
    overlay = {
        "t": ref.time_s[idx].tolist(),
        "v_measured": ref.voltage_v[idx].tolist(),
        "v_model": model_v[idx].tolist(),
    }

    notes = ref.notes
    if ocv_table is not None:
        curve_note = "Using a caller-supplied OCV curve."
    elif matched_key is not None:
        curve_note = f"Using the {matched_key} OCV curve."
    else:
        curve_note = (
            f"No built-in OCV curve for '{chem}'; used the NMC default as a "
            "fallback, so expect larger error until a matching table is supplied."
        )
    notes = f"{notes} {curve_note}".strip()

    fitted = None
    if fit:
        best, best_v = _fit(ref, soc_start, table)
        overlay["v_model_fitted"] = best_v[idx].tolist()
        fitted = best

    return ValidationReport(
        dataset_id=ref.dataset_id,
        cell_id=ref.cell_id,
        chemistry=ref.chemistry,
        n_samples=ref.n_samples,
        duration_s=ref.duration_s,
        data_source=data_source,
        params={
            "r0_ohm": float(r0_ohm),
            "capacity_ah": float(ref.nominal_capacity_ah),
            "soc0": soc_start,
        },
        metrics=metrics,
        overlay=overlay,
        fitted=fitted,
        notes=notes,
        ocv_curve=matched_key or ("custom" if ocv_table is not None else "NMC (fallback)"),
    )
