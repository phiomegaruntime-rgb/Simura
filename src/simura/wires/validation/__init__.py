"""Validate the Simura wire model against published conductor standards.

The wiring counterpart to :mod:`simura.validate` (which validates the battery
model against open lab datasets). A conductor's authoritative reference is a
compact, public table -- DC resistance per unit length by gauge -- so the whole
pipeline runs offline out of the box:

* :mod:`~simura.wires.validation.standards` -- bundled resistance standards
  (annealed copper at 20 °C and 75 °C, hard-drawn aluminium) with citations.
* :mod:`~simura.wires.validation.reference` -- the normalized
  :class:`WireReference` table those standards (and user uploads) produce.
* :mod:`~simura.wires.validation.engine` -- replay each gauge through
  Simura's own :class:`simura.wires.Wire` and report the percent error.

    python -m simura.wires.validation --list
    python -m simura.wires.validation --standard copper-annealed-20c
"""

from .engine import WireValidationReport, validate_reference
from .loaders import load_upload_csv
from .reference import WireReference, WireRefRow
from .standards import (
    STANDARDS,
    WireStandardSpec,
    get_standard,
    list_standards,
)

__all__ = [
    "STANDARDS",
    "WireStandardSpec",
    "list_standards",
    "get_standard",
    "WireReference",
    "WireRefRow",
    "validate_reference",
    "WireValidationReport",
    "load_upload_csv",
]
