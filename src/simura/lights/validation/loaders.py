"""Load a user's own photometric measurements into a :class:`LightReference`.

The lighting analog of :func:`simura.wires.validation.loaders.load_upload_csv`.
Anyone with an integrating sphere, a lux meter and a thermocouple, or simply a
stack of datasheets, can validate Simura against *their* numbers rather than the
bundled ones.

Three shapes of file, matching three of the bundled quantities:

* ``luminous_efficacy`` -- a lamp id column and a measured lm/W column. The lamp
  ids must be ones the catalog knows, since the model has to build the same lamp
  to predict against.
* ``flux_vs_junction_temp`` / ``flux_vs_ambient_temp`` -- a temperature column and
  a relative-output column. If the values look like percentages (anything above
  2.0) they are divided by 100, and the whole series is renormalised so that its
  value at the reference temperature is exactly 1.0 -- otherwise a file
  normalised at 40 °C would be compared against a model normalised at 25 °C and
  the mismatch would be reported as error.
* ``photopic_response`` -- a wavelength column and a relative-response column, for
  checking against a different observer (the 10° observer, or the scotopic curve).
"""

from __future__ import annotations

import csv
from pathlib import Path

from .reference import LightReference, LightRefRow

# The quantities a user file can carry, and the reference point each is
# normalised at (None = no renormalisation).
UPLOAD_QUANTITIES: dict[str, float | None] = {
    "luminous_efficacy": None,
    "flux_vs_junction_temp": 25.0,
    "flux_vs_ambient_temp": 25.0,
    "photopic_response": 555.0,
}


def load_upload_csv(
    path: str | Path,
    *,
    quantity: str = "luminous_efficacy",
    x_col: str = "x",
    value_col: str = "value",
    key_col: str | None = None,
    standard_id: str = "user-file",
    unit: str = "",
) -> LightReference:
    """Parse a measured-photometry CSV into a :class:`LightReference`.

    ``x_col`` is the independent variable (a lamp's rated power, a temperature, a
    wavelength) and ``value_col`` the measured quantity. For
    ``luminous_efficacy``, ``key_col`` must name the column holding catalog lamp
    ids, because the model needs to know *which lamp* to predict.
    """
    if quantity not in UPLOAD_QUANTITIES:
        raise ValueError(
            f"unknown quantity '{quantity}' "
            f"(use one of {', '.join(sorted(UPLOAD_QUANTITIES))})"
        )
    if quantity == "luminous_efficacy" and not key_col:
        raise ValueError(
            "validating luminous efficacy needs a `key_col` naming the column of "
            "catalog lamp ids, so the model can build the same lamp"
        )

    path = Path(path)
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        required = [x_col, value_col] + ([key_col] if key_col else [])
        for column in required:
            if column not in header:
                raise ValueError(
                    f"column '{column}' not in {path.name} (has: {', '.join(header)})"
                )

        raw: list[tuple[str, float, float]] = []
        for line in reader:
            try:
                x = float(line[x_col])
                value = float(line[value_col])
            except (TypeError, ValueError):
                continue
            key = str(line[key_col]).strip() if key_col else f"{x:g}"
            raw.append((key, x, value))

    if len(raw) < 2:
        raise ValueError("need at least two valid rows to validate")

    # Percent-style relative columns -> fractions.
    normalise_at = UPLOAD_QUANTITIES[quantity]
    if normalise_at is not None and max(v for _, _, v in raw) > 2.0:
        raw = [(k, x, v / 100.0) for k, x, v in raw]

    # Renormalise so the series is 1.0 at the reference point, matching the model.
    if normalise_at is not None:
        nearest = min(raw, key=lambda r: abs(r[1] - normalise_at))
        if nearest[2] > 0:
            raw = [(k, x, v / nearest[2]) for k, x, v in raw]

    rows = [
        LightRefRow(
            key=key,
            x=x,
            published=value,
            context=key if quantity == "luminous_efficacy" else None,
        )
        for key, x, value in raw
    ]

    return LightReference(
        standard_id=standard_id,
        quantity=quantity,
        rows=rows,
        unit=unit or _default_unit(quantity),
        x_label=_default_x_label(quantity),
        x_unit=_default_x_unit(quantity),
        data_source="user-upload",
        notes=f"User-supplied measurements ({path.name}).",
    )


def _default_unit(quantity: str) -> str:
    return {
        "luminous_efficacy": "lm/W",
        "flux_vs_junction_temp": "relative to 25 °C",
        "flux_vs_ambient_temp": "relative to 25 °C",
        "photopic_response": "relative",
    }.get(quantity, "")


def _default_x_label(quantity: str) -> str:
    return {
        "luminous_efficacy": "rated power",
        "flux_vs_junction_temp": "junction temperature",
        "flux_vs_ambient_temp": "ambient temperature",
        "photopic_response": "wavelength",
    }.get(quantity, "x")


def _default_x_unit(quantity: str) -> str:
    return {
        "luminous_efficacy": "W",
        "flux_vs_junction_temp": "°C",
        "flux_vs_ambient_temp": "°C",
        "photopic_response": "nm",
    }.get(quantity, "")
