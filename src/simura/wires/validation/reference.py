"""The normalized wire reference -- what standards/loaders produce and the validator consumes.

The battery side validates predicted *terminal voltage* against a measured
time-series (:class:`simura.validate.reference.ReferenceRun`). A conductor has
no interesting time-series to track under a fixed current -- its defining
published quantity is **DC resistance per unit length as a function of gauge**.
So the wire analog of a reference run is a small *table*: for one material at one
reference temperature, the standard's resistance value for each gauge.

:func:`simura.wires.validation.engine.validate_reference` replays each row
through the same :class:`simura.wires.Wire` the twin uses and compares its
predicted resistance to the published number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class WireRefRow:
    """One gauge's published DC resistance (per kilometre) from a standard."""

    awg: int                         # AWG size (0..-3 == 1/0..4/0)
    area_mm2: float                  # standard nominal cross-section for this gauge
    published_ohm_per_km: float      # the standard's DC resistance at the ref temperature
    ampacity_a: Optional[float] = None   # optional published current rating


@dataclass
class WireReference:
    """A normalized conductor-resistance reference: one material, many gauges.

    ``rows`` is the published resistance table at ``ref_temp_c``. ``data_source``
    distinguishes a bundled published standard from a user-supplied file, exactly
    as the battery report does.
    """

    standard_id: str
    material: str
    ref_temp_c: float
    rows: list[WireRefRow] = field(default_factory=list)
    quantity: str = "dc_resistance"
    unit: str = "Ω/km"
    data_source: str = "bundled-standard"
    notes: str = ""

    def __post_init__(self) -> None:
        if len(self.rows) < 2:
            raise ValueError("a wire reference needs at least two gauges")
        for r in self.rows:
            if r.published_ohm_per_km <= 0:
                raise ValueError(f"non-positive published resistance for AWG {r.awg}")

    @property
    def n_points(self) -> int:
        return len(self.rows)
