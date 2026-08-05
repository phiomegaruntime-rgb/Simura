"""The normalized reference run -- the contract loaders produce and the validator consumes.

Every real dataset has its own file format and column names (see
:mod:`celltwin.validate.loaders`). We normalize all of them to a single
:class:`ReferenceRun` so the validation engine only ever sees one shape: a
time-series of measured current, terminal voltage, and (optionally) temperature
for one cell, plus enough metadata to configure a comparable model.

Sign convention matches the simulator (:mod:`celltwin.sim.pack`): **current > 0
is discharge**. Loaders are responsible for flipping a charge-positive source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class ReferenceRun:
    """One cell's measured time-series, normalized for validation.

    ``time_s``/``current_a``/``voltage_v`` are equal-length 1-D arrays. Current
    follows the discharge-positive convention. ``temperature_c`` is optional
    (many bench datasets log it; some don't). ``cycle_index``/``capacity_ah`` are
    optional per-*cycle* series used for capacity-fade / SoH validation.
    """

    dataset_id: str
    time_s: np.ndarray
    current_a: np.ndarray
    voltage_v: np.ndarray
    temperature_c: Optional[np.ndarray] = None

    cell_id: str = "cell"
    chemistry: str = "unknown"
    nominal_capacity_ah: float = 5.0
    ambient_temp_c: float = 25.0

    # Optional per-cycle degradation series (not aligned to the sample arrays).
    cycle_index: Optional[np.ndarray] = None
    capacity_ah: Optional[np.ndarray] = None

    notes: str = ""
    _extra: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.time_s = np.asarray(self.time_s, dtype=float)
        self.current_a = np.asarray(self.current_a, dtype=float)
        self.voltage_v = np.asarray(self.voltage_v, dtype=float)
        n = self.time_s.shape[0]
        if self.current_a.shape[0] != n or self.voltage_v.shape[0] != n:
            raise ValueError(
                "time_s, current_a and voltage_v must be the same length "
                f"(got {self.time_s.shape[0]}, {self.current_a.shape[0]}, "
                f"{self.voltage_v.shape[0]})"
            )
        if n < 2:
            raise ValueError("a reference run needs at least two samples")
        if self.temperature_c is not None:
            self.temperature_c = np.asarray(self.temperature_c, dtype=float)
            if self.temperature_c.shape[0] != n:
                raise ValueError("temperature_c must match the sample length")
        if self.cycle_index is not None:
            self.cycle_index = np.asarray(self.cycle_index, dtype=float)
        if self.capacity_ah is not None:
            self.capacity_ah = np.asarray(self.capacity_ah, dtype=float)

    @property
    def n_samples(self) -> int:
        return int(self.time_s.shape[0])

    @property
    def duration_s(self) -> float:
        return float(self.time_s[-1] - self.time_s[0])

    def dt_s(self) -> float:
        """Representative timestep (median of the sample spacing).

        Real logs aren't perfectly uniform; the engine steps with the actual
        per-sample gap, but this is a handy summary.
        """
        return float(np.median(np.diff(self.time_s)))

    def overlay(self, max_points: int = 400) -> dict[str, list[float]]:
        """Downsample the measured trace for plotting (evenly by index)."""
        idx = self._overlay_index(max_points)
        return {
            "t": self.time_s[idx].tolist(),
            "v_measured": self.voltage_v[idx].tolist(),
        }

    def _overlay_index(self, max_points: int) -> np.ndarray:
        n = self.n_samples
        if n <= max_points:
            return np.arange(n)
        return np.linspace(0, n - 1, max_points).astype(int)
