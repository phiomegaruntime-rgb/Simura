"""The normalized lighting reference -- what standards and loaders produce.

The battery side validates predicted *terminal voltage* against a measured
time-series; the wire side validates predicted *DC resistance* against a
published table. Lighting has no single defining quantity: a light source is
judged on how much light it makes, what colour that light is, and how both change
with temperature -- and those are validated against different references
entirely.

So a :class:`LightReference` carries a ``quantity`` naming what is being checked,
and :mod:`simura.lights.validation.engine` dispatches on it:

=============================  ============================================
``photopic_response``          ``V(lambda)`` against the tabulated CIE
                               observer -- validates the analytic fit the
                               whole photometric chain rests on.
``color_temperature``          CCT of a blackbody against its own
                               temperature (which is the definition of the
                               Planckian locus) -- validates the colour maths.
``luminous_efficacy``          Whole-lamp lm/W against published catalogue
                               figures -- validates the entire chain at once.
``flux_vs_junction_temp``      Relative LED output against junction
                               temperature -- validates the solid-state
                               derating law.
``flux_vs_ambient_temp``       Relative fluorescent output against ambient --
                               validates the vapour-pressure response.
``daylight_illuminance``       Predicted daylight against *live* measured
                               irradiance -- see
                               :mod:`simura.lights.validation.live`.
=============================  ============================================

Each row is one point: an independent variable ``x``, a human ``key``, and the
published value. What the engine does with them is the quantity's business.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class LightRefRow:
    """One published data point from a lighting reference."""

    key: str                     # a label: a wavelength, a lamp id, a temperature
    x: float                     # the independent variable, in the quantity's units
    published: float             # the reference value
    context: Optional[str] = None   # anything the engine needs to reproduce it


@dataclass
class LightReference:
    """A normalized lighting reference: one quantity, many points.

    ``data_source`` distinguishes a bundled published standard from a user-supplied
    file or a live measurement, exactly as the battery and wire reports do.
    """

    standard_id: str
    quantity: str
    rows: list[LightRefRow] = field(default_factory=list)
    unit: str = ""
    x_label: str = "x"
    x_unit: str = ""
    data_source: str = "bundled-standard"
    notes: str = ""

    def __post_init__(self) -> None:
        if len(self.rows) < 2:
            raise ValueError("a lighting reference needs at least two points")

    @property
    def n_points(self) -> int:
        return len(self.rows)
