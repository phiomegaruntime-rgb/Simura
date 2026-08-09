"""Load a user's own measured conductor-resistance CSV into a :class:`WireReference`.

The wiring analog of :func:`simura.validate.loaders.load_upload`. A user who
has bench-measured (or datasheet-quoted) the DC resistance of some gauges can
validate Simura against *their* numbers: a CSV with an AWG column and a
resistance column. Uses only the standard library + the resistance value; the
gauge's cross-section is taken from the standard AWG table for display.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .reference import WireReference, WireRefRow
from .standards import _AWG_AREA_MM2

# Accepted resistance units -> multiplier to Ω/km.
_UNIT_TO_OHM_PER_KM = {
    "ohm/km": 1.0,
    "ohm_per_km": 1.0,
    "mohm/m": 1.0,          # 1 mΩ/m == 1 Ω/km
    "ohm/1000ft": 1000.0 / 304.8,   # ohms per 1000 ft -> per km
    "ohm/kft": 1000.0 / 304.8,
}


def load_upload_csv(
    path: str | Path,
    *,
    material: str = "copper",
    awg_col: str = "awg",
    resistance_col: str = "resistance_ohm_per_km",
    ref_temp_c: float = 20.0,
    resistance_unit: str = "ohm/km",
    standard_id: str = "user-file",
) -> WireReference:
    """Parse a measured-resistance CSV into a :class:`WireReference`.

    The file needs an AWG column and a DC-resistance column; ``resistance_unit``
    converts common conventions (Ω/km, mΩ/m, Ω per 1000 ft) to the Ω/km the
    engine works in. Rows whose gauge isn't a standard AWG size are skipped.
    """
    unit = resistance_unit.strip().lower()
    if unit not in _UNIT_TO_OHM_PER_KM:
        raise ValueError(
            f"unknown resistance unit '{resistance_unit}' "
            f"(use one of {', '.join(_UNIT_TO_OHM_PER_KM)})"
        )
    scale = _UNIT_TO_OHM_PER_KM[unit]

    path = Path(path)
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        for required in (awg_col, resistance_col):
            if required not in header:
                raise ValueError(
                    f"column '{required}' not in {path.name} (has: {', '.join(header)})"
                )
        rows: list[WireRefRow] = []
        for raw in reader:
            try:
                awg = int(round(float(raw[awg_col])))
                r = float(raw[resistance_col]) * scale
            except (TypeError, ValueError):
                continue
            if awg not in _AWG_AREA_MM2 or r <= 0:
                continue
            rows.append(
                WireRefRow(awg=awg, area_mm2=_AWG_AREA_MM2[awg], published_ohm_per_km=r)
            )

    if len(rows) < 2:
        raise ValueError("need at least two valid AWG/resistance rows to validate")

    return WireReference(
        standard_id=standard_id,
        material=material,
        ref_temp_c=ref_temp_c,
        rows=rows,
        data_source="user-upload",
        notes=f"User-supplied measured resistance ({path.name}).",
    )
