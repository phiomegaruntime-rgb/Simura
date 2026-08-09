"""A curated catalog of conductor materials, gauges, insulations and wire types.

This is the "parts bin" the user picks from -- the wiring analog of the OCV
chemistry tables in :mod:`simura.sim.ocv` and the dataset directory in
:mod:`simura.validate.catalog`. It is a *reference*, not an authority: the
resistivities and temperature coefficients are standard textbook values, but the
**ampacity** figures are approximate, single-conductor-in-free-air reference
numbers for orientation only.

Honesty note: real-world current ratings depend on installation method, grouping,
ambient temperature and the governing electrical code (NEC / IEC). **Size real
wiring against the applicable code, not against these reference numbers.**
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ConductorMaterial:
    """Electrical properties of a conductor metal (nominal, at 20 C)."""

    key: str
    name: str
    resistivity_20c_ohm_m: float   # rho_20 (ohm-metre)
    temp_coeff_per_k: float        # alpha: rho(T) = rho_20 * (1 + alpha*(T-20))
    density_kg_m3: float = 0.0     # for mass / thermal-capacity estimates
    specific_heat_j_per_kg_k: float = 385.0   # cp, for thermal-capacity estimates

    def resistivity_at(self, temp_c: float) -> float:
        """Resistivity at ``temp_c`` via the linear temperature model."""
        return self.resistivity_20c_ohm_m * (1.0 + self.temp_coeff_per_k * (temp_c - 20.0))


# Standard values. Copper/aluminium are the two conductors that matter in
# practice; tinned copper is copper with a marginally higher resistivity.
MATERIALS: dict[str, ConductorMaterial] = {
    "copper": ConductorMaterial("copper", "Copper", 1.68e-8, 0.00393, 8960.0, 385.0),
    "aluminum": ConductorMaterial("aluminum", "Aluminium", 2.65e-8, 0.00403, 2700.0, 897.0),
    "tinned_copper": ConductorMaterial("tinned_copper", "Tinned copper", 1.72e-8, 0.00385, 8960.0, 385.0),
}

# Insulation classes -> maximum continuous conductor temperature (C). This is the
# limit the thermal model checks against and the ceiling on a wire's ampacity.
INSULATION_TEMP_C: dict[str, float] = {
    "PVC-60": 60.0,
    "PVC-75": 75.0,
    "PVC-90": 90.0,
    "THHN-90": 90.0,
    "XLPE-90": 90.0,
    "silicone-150": 150.0,
    "silicone-200": 200.0,
}


def material_for(key: str) -> ConductorMaterial:
    """Look up a :class:`ConductorMaterial` by key (case-insensitive)."""
    k = str(key).lower()
    if k not in MATERIALS:
        raise ValueError(f"unknown conductor material '{key}' (use one of {list(MATERIALS)})")
    return MATERIALS[k]


def insulation_temp_c(insulation: str) -> float:
    """Maximum conductor temperature for a named insulation class."""
    if insulation not in INSULATION_TEMP_C:
        raise ValueError(
            f"unknown insulation '{insulation}' (use one of {list(INSULATION_TEMP_C)})"
        )
    return INSULATION_TEMP_C[insulation]


def awg_area_mm2(awg: float) -> float:
    """Cross-sectional area (mm^2) of an AWG gauge.

    Uses the defining AWG relation ``d = 0.127 mm * 92^((36-n)/39)``. Works for
    the sizes that go below 1 too: pass ``0`` for 1/0, ``-1`` for 2/0, ``-2`` for
    3/0, ``-3`` for 4/0.
    """
    diameter_mm = 0.127 * 92.0 ** ((36.0 - awg) / 39.0)
    return math.pi / 4.0 * diameter_mm ** 2


@dataclass(frozen=True)
class WireType:
    """One selectable, off-the-shelf wire (a conductor + gauge + insulation)."""

    id: str
    name: str
    material: str            # key into MATERIALS
    awg: int                 # American Wire Gauge (0..-3 == 1/0..4/0)
    area_mm2: float          # conductor cross-section
    insulation: str          # key into INSULATION_TEMP_C
    temp_rating_c: float     # = INSULATION_TEMP_C[insulation]
    ampacity_a: float        # reference single-conductor free-air current rating
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _wire(id: str, material: str, awg: int, insulation: str, ampacity_a: float, notes: str = "") -> WireType:
    return WireType(
        id=id,
        name=f"{MATERIALS[material].name} {_awg_label(awg)} AWG {insulation}",
        material=material,
        awg=awg,
        area_mm2=round(awg_area_mm2(awg), 4),
        insulation=insulation,
        temp_rating_c=INSULATION_TEMP_C[insulation],
        ampacity_a=ampacity_a,
        notes=notes,
    )


def _awg_label(awg: int) -> str:
    """Human label for a gauge (``0`` -> ``1/0`` etc.)."""
    return f"{1 - awg}/0" if awg <= 0 else str(awg)


# Curated selection spanning small hookup wire to feeder cable. Ampacity figures
# are reference values (copper ~ the NEC 75/90 C columns; aluminium derated ~80%).
WIRE_CATALOG: list[WireType] = [
    _wire("cu-18-pvc75", "copper", 18, "PVC-75", 10.0, "hookup / signal"),
    _wire("cu-16-pvc75", "copper", 16, "PVC-75", 13.0, "hookup"),
    _wire("cu-14-thhn90", "copper", 14, "THHN-90", 20.0, "branch circuit"),
    _wire("cu-12-thhn90", "copper", 12, "THHN-90", 25.0, "branch circuit"),
    _wire("cu-10-thhn90", "copper", 10, "THHN-90", 35.0, "branch circuit"),
    _wire("cu-8-thhn90", "copper", 8, "THHN-90", 55.0, "feeder"),
    _wire("cu-6-thhn90", "copper", 6, "THHN-90", 75.0, "feeder"),
    _wire("cu-4-xlpe90", "copper", 4, "XLPE-90", 95.0, "feeder"),
    _wire("cu-2-xlpe90", "copper", 2, "XLPE-90", 130.0, "feeder"),
    _wire("cu-1/0-xlpe90", "copper", 0, "XLPE-90", 170.0, "service"),
    _wire("cu-14-sil150", "copper", 14, "silicone-150", 30.0, "high-temp / battery lead"),
    _wire("cu-10-sil150", "copper", 10, "silicone-150", 55.0, "high-temp / battery lead"),
    _wire("al-6-xlpe90", "aluminum", 6, "XLPE-90", 60.0, "aluminium feeder"),
    _wire("al-2-xlpe90", "aluminum", 2, "XLPE-90", 100.0, "aluminium feeder"),
    _wire("al-1/0-xlpe90", "aluminum", 0, "XLPE-90", 135.0, "aluminium service"),
]

_BY_ID = {w.id: w for w in WIRE_CATALOG}


def wire_type_for(id: str) -> WireType:
    """Look up a catalog :class:`WireType` by id."""
    if id not in _BY_ID:
        raise ValueError(f"unknown wire type '{id}' (see list_wire_types())")
    return _BY_ID[id]


def list_wire_types() -> list[WireType]:
    """Return the full catalog (a copy-safe view of the curated list)."""
    return list(WIRE_CATALOG)


def catalog_ampacity_for(material: str, awg: int, insulation: str | None = None) -> float | None:
    """Reference ampacity for a material/gauge (preferring a matching insulation).

    Returns ``None`` if nothing in the catalog matches, so callers can fall back
    to their own estimate.
    """
    mat = str(material).lower()
    matches = [w for w in WIRE_CATALOG if w.material == mat and w.awg == awg]
    if not matches:
        return None
    if insulation is not None:
        exact = [w for w in matches if w.insulation == insulation]
        if exact:
            return exact[0].ampacity_a
    return matches[0].ampacity_a
