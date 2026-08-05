"""Format loaders: a user's own downloaded dataset file -> one :class:`ReferenceRun`.

Each real dataset ships in its own layout (MATLAB structs, per-cycle CSVs, ...).
A loader knows how to pull the three essentials -- time, current, terminal
voltage (plus temperature when present) -- out of one file and normalize them to
the discharge-positive convention the rest of CellTwin uses.

We do **not** bundle the real data. The ``.mat`` loaders need SciPy, imported
lazily so the base install stays dependency-light: ``pip install celltwin[validate]``.
The CSV loaders use only the standard library and NumPy.
"""

from __future__ import annotations

import csv
from importlib.resources import files
from pathlib import Path
from typing import Optional

import numpy as np

from .catalog import DatasetSpec, get_dataset
from .reference import ReferenceRun


def _require_scipy():
    try:
        from scipy.io import loadmat  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only w/o scipy
        raise ModuleNotFoundError(
            "reading MATLAB (.mat) datasets needs SciPy. "
            "Install it with:  pip install celltwin[validate]"
        ) from exc
    return loadmat


def sample_path(spec: DatasetSpec) -> Path:
    """Absolute path to a catalog entry's bundled sample (only the synthetic demo)."""
    if not spec.sample:
        raise ValueError(f"dataset '{spec.id}' has no bundled sample; download it instead")
    return Path(files("celltwin.validate").joinpath("data", spec.sample))


def load_generic_csv(
    path: str | Path,
    *,
    time_col: str = "time_s",
    current_col: str = "current_a",
    voltage_col: str = "voltage_v",
    temp_col: Optional[str] = "temperature_c",
    discharge_positive: bool = True,
    current_scale: float = 1.0,
    dataset_id: str = "csv",
    chemistry: str = "unknown",
    nominal_capacity_ah: float = 5.0,
    cell_id: str = "cell",
) -> ReferenceRun:
    """Load a plain CSV with named columns into a :class:`ReferenceRun`.

    This is the escape hatch for any dataset: export one cell to a CSV with
    time/current/voltage columns and point this at it. Set
    ``discharge_positive=False`` if the source logs charge as positive (we flip
    it), and ``current_scale`` to convert units (e.g. mA -> A is ``0.001``).
    """
    path = Path(path)
    rows: list[dict[str, str]] = []
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        for required in (time_col, current_col, voltage_col):
            if required not in header:
                raise ValueError(
                    f"column '{required}' not in {path.name} (has: {', '.join(header)})"
                )
        has_temp = bool(temp_col) and temp_col in header
        rows = list(reader)

    def col(name: str) -> np.ndarray:
        return np.array([float(r[name]) for r in rows], dtype=float)

    current = col(current_col) * current_scale
    if not discharge_positive:
        current = -current

    return ReferenceRun(
        dataset_id=dataset_id,
        time_s=col(time_col),
        current_a=current,
        voltage_v=col(voltage_col),
        temperature_c=col(temp_col) if has_temp else None,
        cell_id=cell_id,
        chemistry=chemistry,
        nominal_capacity_ah=nominal_capacity_ah,
    )


def load_nasa_mat(
    path: str | Path,
    *,
    cycle_type: str = "discharge",
    cycle_index: int = 0,
    nominal_capacity_ah: float = 2.0,
) -> ReferenceRun:
    """Load one cycle from a NASA PCoE ``.mat`` file.

    NASA cells store a top-level struct whose ``cycle`` array holds charge /
    discharge / impedance operations; each discharge cycle exposes
    ``Voltage_measured``, ``Current_measured``, ``Temperature_measured`` and
    ``Time``. NASA logs discharge current as negative, so we flip it.
    """
    loadmat = _require_scipy()
    mat = loadmat(str(path), simplify_cells=True)
    # The struct is stored under the file's base name (e.g. "B0005").
    key = next(k for k in mat if not k.startswith("__"))
    cycles = mat[key]["cycle"]
    matching = [c for c in cycles if c.get("type") == cycle_type]
    if not matching:
        raise ValueError(f"no '{cycle_type}' cycles in {Path(path).name}")
    data = matching[cycle_index]["data"]
    current = -np.asarray(data["Current_measured"], dtype=float)  # -> discharge positive
    return ReferenceRun(
        dataset_id="nasa-pcoe",
        time_s=np.asarray(data["Time"], dtype=float),
        current_a=current,
        voltage_v=np.asarray(data["Voltage_measured"], dtype=float),
        temperature_c=np.asarray(data["Temperature_measured"], dtype=float),
        cell_id=str(key),
        chemistry="LCO",
        nominal_capacity_ah=nominal_capacity_ah,
    )


def load_oxford_mat(
    path: str | Path,
    *,
    cell: str = "Cell1",
    cycle: str = "cyc0000",
    step: str = "C1dc",
    nominal_capacity_ah: float = 0.74,
) -> ReferenceRun:
    """Load one characterization step from an Oxford Degradation ``.mat`` file.

    Oxford stores nested structs keyed by cell, cycle, and step (e.g. the C/1
    discharge ``C1dc``), each exposing ``t``, ``I``, ``v``, ``T``. Oxford logs
    discharge current as negative, so we flip it.
    """
    loadmat = _require_scipy()
    mat = loadmat(str(path), simplify_cells=True)
    key = next(k for k in mat if not k.startswith("__"))
    node = mat[key][cell][cycle][step]
    current = -np.asarray(node["I"], dtype=float)
    return ReferenceRun(
        dataset_id="oxford-degradation",
        time_s=np.asarray(node["t"], dtype=float),
        current_a=current,
        voltage_v=np.asarray(node["v"], dtype=float),
        temperature_c=np.asarray(node["T"], dtype=float) if "T" in node else None,
        cell_id=cell,
        chemistry="NMC/LCO",
        nominal_capacity_ah=nominal_capacity_ah,
    )


def load_calce_csv(path: str | Path, *, nominal_capacity_ah: float = 1.1) -> ReferenceRun:
    """Load a CALCE per-cycle CSV (columns ``Test_Time(s)``, ``Current(A)``, ``Voltage(V)``).

    CALCE logs discharge current as negative, so we flip it.
    """
    return load_generic_csv(
        path,
        time_col="Test_Time(s)",
        current_col="Current(A)",
        voltage_col="Voltage(V)",
        temp_col="Temperature (C)_1",
        discharge_positive=False,
        dataset_id="calce",
        chemistry="LCO",
        nominal_capacity_ah=nominal_capacity_ah,
    )


def load_sandia_csv(path: str | Path, *, nominal_capacity_ah: float = 3.0) -> ReferenceRun:
    """Load a Sandia / Battery-Archive normalized CSV (``Test_Time (s)``, ``Current (A)``,
    ``Voltage (V)``). Battery Archive logs discharge current as negative."""
    return load_generic_csv(
        path,
        time_col="Test_Time (s)",
        current_col="Current (A)",
        voltage_col="Voltage (V)",
        temp_col="Cell_Temperature (C)",
        discharge_positive=False,
        dataset_id="sandia",
        chemistry="NMC",
        nominal_capacity_ah=nominal_capacity_ah,
    )


_LOADERS = {
    "generic_csv": load_generic_csv,
    "nasa_mat": load_nasa_mat,
    "oxford_mat": load_oxford_mat,
    "calce_csv": load_calce_csv,
    "sandia_csv": load_sandia_csv,
}


def loader_for(spec: DatasetSpec):
    """Return the loader callable for a catalog entry's ``loader`` key."""
    try:
        return _LOADERS[spec.loader]
    except KeyError:
        raise KeyError(f"no loader named '{spec.loader}' for dataset '{spec.id}'") from None


def load_upload(
    path: str | Path,
    *,
    dataset_id: str | None = None,
    chemistry: str | None = None,
    **generic_kwargs,
) -> ReferenceRun:
    """Load a user-uploaded dataset file into a :class:`ReferenceRun`.

    Dispatches like the CLI does, but for a file that arrived over HTTP:

    * If ``dataset_id`` names a catalog entry with a **format-specific** loader
      (``.mat``, CALCE, Sandia), that loader is used with its own field defaults.
    * Otherwise the **generic CSV** loader is used with the caller's column
      mapping (``time_col``/``current_col``/``voltage_col``/...), so any exported
      single-cell CSV works.

    ``chemistry`` overrides the chemistry label (which selects the OCV curve);
    it defaults to the dataset's chemistry, or ``"unknown"`` for a bare CSV.
    """
    if dataset_id:
        spec = get_dataset(dataset_id)
        loader = loader_for(spec)
        if loader is load_generic_csv:
            return load_generic_csv(
                path,
                dataset_id=dataset_id,
                chemistry=chemistry or spec.chemistry,
                **generic_kwargs,
            )
        # Format-specific loaders own their field layout; ignore generic columns.
        ref = loader(path)
        if chemistry:
            ref.chemistry = chemistry
        return ref
    return load_generic_csv(path, chemistry=chemistry or "unknown", **generic_kwargs)


def load_sample(spec: DatasetSpec) -> ReferenceRun:
    """Load a catalog entry's bundled sample (only the synthetic demo has one)."""
    run = load_generic_csv(
        sample_path(spec),
        dataset_id=spec.id,
        chemistry=spec.chemistry,
    )
    run.notes = spec.notes
    return run
