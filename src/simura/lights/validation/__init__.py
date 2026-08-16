"""Validate the Simura lighting model against published data and live measurements.

The lighting counterpart to :mod:`simura.validate` (battery model vs open lab
datasets) and :mod:`simura.wires.validation` (conductor model vs published
resistance standards).

Lighting is validated at five depths, because a light source is judged on more
than one number:

* :mod:`~simura.lights.validation.standards` -- bundled published references: the
  CIE observer, the Planckian locus, real lamps' catalogue efficacy, and the two
  temperature-derating curves.
* :mod:`~simura.lights.validation.reference` -- the normalized
  :class:`LightReference` those standards (and user uploads) produce.
* :mod:`~simura.lights.validation.engine` -- replay every point through Simura's
  own :class:`simura.lights.Light` and spectral code, and report the error.
* :mod:`~simura.lights.validation.loaders` -- do the same against the user's own
  measured CSV.
* :mod:`~simura.lights.validation.live` -- and against **live** measured solar
  irradiance from Open-Meteo, which is the one reference here that is different
  every time you run it.

    python -m simura.lights.validation --list
    python -m simura.lights.validation --standard lamp-efficacy-published
    python -m simura.lights.validation --live --lat 51.5 --lon -0.13
"""

from .engine import QUANTITIES, LightValidationReport, validate_reference
from .live import LiveDaylightReport, validate_daylight_live
from .loaders import UPLOAD_QUANTITIES, load_upload_csv
from .reference import LightReference, LightRefRow
from .standards import STANDARDS, LightStandardSpec, get_standard, list_standards

__all__ = [
    "STANDARDS",
    "LightStandardSpec",
    "list_standards",
    "get_standard",
    "LightReference",
    "LightRefRow",
    "validate_reference",
    "LightValidationReport",
    "QUANTITIES",
    "load_upload_csv",
    "UPLOAD_QUANTITIES",
    "validate_daylight_live",
    "LiveDaylightReport",
]
