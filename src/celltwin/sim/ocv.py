"""Open-circuit-voltage (OCV) vs state-of-charge (SoC) relationship.

The OCV-SoC curve is the electrochemical "fingerprint" of a cell chemistry.
The table below is an *illustrative* NMC (nickel-manganese-cobalt) Li-ion curve
at 25 C -- good enough for a realistic-looking twin, and easy to replace with a
measured curve later. Values are volts at the given fractional SoC.

Replace `NMC_OCV_TABLE` (or pass your own to :func:`make_ocv`) to model a
different chemistry (LFP, for example, has a much flatter plateau).
"""

from __future__ import annotations

import re
from typing import Callable, Optional

import numpy as np

# (SoC fraction, OCV volts) -- monotonically increasing in SoC.
NMC_OCV_TABLE: list[tuple[float, float]] = [
    (0.00, 3.00),
    (0.05, 3.45),
    (0.10, 3.55),
    (0.20, 3.63),
    (0.30, 3.68),
    (0.40, 3.72),
    (0.50, 3.76),
    (0.60, 3.83),
    (0.70, 3.90),
    (0.80, 3.98),
    (0.90, 4.07),
    (1.00, 4.18),
]

# LFP (lithium iron phosphate): ~3.2-3.3 V with a famously *flat* mid-SoC plateau
# and sharp knees at both ends. The flatness is what makes voltage-only SoC
# estimation hard -- and why using the *right* OCV curve matters for validation.
# Kept strictly increasing so the inverse (SoC-from-OCV) is well-defined.
LFP_OCV_TABLE: list[tuple[float, float]] = [
    (0.00, 2.80),
    (0.05, 3.06),
    (0.10, 3.20),
    (0.15, 3.26),
    (0.20, 3.290),
    (0.30, 3.305),
    (0.40, 3.315),
    (0.50, 3.320),
    (0.60, 3.328),
    (0.70, 3.335),
    (0.80, 3.345),
    (0.90, 3.365),
    (0.95, 3.420),
    (1.00, 3.600),
]

# LCO (lithium cobalt oxide): the classic 3.0-4.2 V consumer-cell curve
# (NASA PCoE and CALCE cells are LCO).
LCO_OCV_TABLE: list[tuple[float, float]] = [
    (0.00, 3.00),
    (0.10, 3.55),
    (0.20, 3.70),
    (0.30, 3.78),
    (0.40, 3.84),
    (0.50, 3.90),
    (0.60, 3.96),
    (0.70, 4.02),
    (0.80, 4.08),
    (0.90, 4.14),
    (1.00, 4.20),
]

# NCA (nickel-cobalt-aluminium): close to NMC, ~2.5-4.2 V.
NCA_OCV_TABLE: list[tuple[float, float]] = [
    (0.00, 3.00),
    (0.10, 3.52),
    (0.20, 3.60),
    (0.30, 3.66),
    (0.40, 3.71),
    (0.50, 3.76),
    (0.60, 3.82),
    (0.70, 3.89),
    (0.80, 3.97),
    (0.90, 4.06),
    (1.00, 4.20),
]

# Registry keyed by chemistry code. All curves are *illustrative* -- realistic in
# shape and range, not manufacturer-exact. Replace with measured tables for
# publication-grade validation (a great "good first area" for contributors).
OCV_TABLES: dict[str, list[tuple[float, float]]] = {
    "NMC": NMC_OCV_TABLE,
    "LFP": LFP_OCV_TABLE,
    "LCO": LCO_OCV_TABLE,
    "NCA": NCA_OCV_TABLE,
}


def chemistry_key_for(chemistry: str) -> Optional[str]:
    """Return the OCV-table key for a chemistry label, or ``None`` if unknown.

    Handles compound labels ("NMC/LCO", "NMC-LCO", "NMC/NCA/LFP") by taking the
    *first* recognized chemistry token -- the primary chemistry of that cell.
    """
    for token in re.split(r"[^A-Za-z0-9]+", chemistry.upper()):
        if token in OCV_TABLES:
            return token
    return None


def ocv_table_for(chemistry: str) -> list[tuple[float, float]]:
    """Return the OCV-SoC table for a chemistry label, defaulting to NMC."""
    key = chemistry_key_for(chemistry)
    return OCV_TABLES[key] if key is not None else NMC_OCV_TABLE


def make_ocv(
    table: list[tuple[float, float]] | None = None,
) -> Callable[[np.ndarray], np.ndarray]:
    """Return a vectorized OCV(SoC) function using linear interpolation.

    SoC is clamped to [0, 1] before lookup so the model degrades gracefully if a
    fault or an aggressive load pushes a cell slightly out of bounds.
    """
    tbl = table if table is not None else NMC_OCV_TABLE
    soc_points = np.array([p[0] for p in tbl], dtype=float)
    ocv_points = np.array([p[1] for p in tbl], dtype=float)

    def ocv(soc: np.ndarray) -> np.ndarray:
        soc_clamped = np.clip(soc, 0.0, 1.0)
        return np.interp(soc_clamped, soc_points, ocv_points)

    return ocv


def make_soc_from_ocv(
    table: list[tuple[float, float]] | None = None,
) -> Callable[[np.ndarray], np.ndarray]:
    """Return the inverse: estimate SoC from (open-circuit) voltage.

    Used by hardware connectors when a BMS reports per-cell voltage but not
    per-cell SoC. It is only exact at rest -- under load the terminal voltage is
    below OCV -- so it is a rough estimate, offered as one derivation option.
    """
    tbl = table if table is not None else NMC_OCV_TABLE
    soc_points = np.array([p[0] for p in tbl], dtype=float)
    ocv_points = np.array([p[1] for p in tbl], dtype=float)

    def soc_from_ocv(voltage: np.ndarray) -> np.ndarray:
        return np.interp(voltage, ocv_points, soc_points)

    return soc_from_ocv
