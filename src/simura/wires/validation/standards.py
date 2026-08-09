"""A curated catalog of published conductor-resistance standards.

The wiring analog of :mod:`simura.validate.catalog`. Where the battery side
points at large, separately-downloaded lab datasets, a conductor's reference data
is a compact, public *physical* table -- DC resistance per unit length by gauge --
so we bundle it directly and the whole validation runs offline.

How the ``published_ohm_per_km`` values are derived (so every number is traceable):

    R/length = rho(T) / A,   rho(T) = rho_20 * (1 + alpha * (T - 20))

with ``A`` the standard nominal AWG cross-section and ``rho_20`` the material's
**standard** resistivity -- deliberately the reference value, *not* the one
:mod:`simura.wires.catalog` ships, so the validation actually measures the gap
between Simura's model and the standard:

* Copper: IACS annealed copper, ``rho_20 = 1.7241e-8`` ohm*m (IEC 60228 /
  ASTM B193), ``alpha = 0.00393 /K``. Simura models pure copper at
  ``1.68e-8``, so expect the model to read a few percent *below* the annealed
  standard -- a real, honest bias, not a rigged match.
* Aluminium: IEC 60228 hard-drawn aluminium, ``rho_20 = 2.82e-8`` ohm*m
  vs Simura's ``2.65e-8``.

Honesty note: these are nominal reference resistances for *solid* annealed
conductors. Real cable adds stranding, coating and lay-length factors, and current
ratings depend on the installation and governing code. **Size real wiring against
the applicable standard, not these orientation figures.**
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .reference import WireReference, WireRefRow

# Standard nominal AWG cross-sections (mm^2). Independent of Simura's own
# geometry helper so the AWG->area relation is itself part of what's validated.
_AWG_AREA_MM2: dict[int, float] = {
    18: 0.823,
    16: 1.31,
    14: 2.08,
    12: 3.31,
    10: 5.26,
    8: 8.37,
    6: 13.30,
    4: 21.15,
    2: 33.62,
    1: 42.41,
    0: 53.48,   # 1/0
}

# Standard resistivities (ohm*m at 20 C) and temperature coefficients (per K).
_STD_RHO_20 = {"copper": 1.7241e-8, "aluminum": 2.82e-8}
_STD_ALPHA = {"copper": 0.00393, "aluminum": 0.00403}


def _rows(material: str, gauges: list[int], ref_temp_c: float) -> list[WireRefRow]:
    """Build the published resistance rows for a material at ``ref_temp_c``."""
    rho20 = _STD_RHO_20[material]
    alpha = _STD_ALPHA[material]
    rho = rho20 * (1.0 + alpha * (ref_temp_c - 20.0))
    out: list[WireRefRow] = []
    for awg in gauges:
        area_m2 = _AWG_AREA_MM2[awg] * 1e-6
        ohm_per_km = rho / area_m2 * 1000.0
        out.append(WireRefRow(awg=awg, area_mm2=_AWG_AREA_MM2[awg], published_ohm_per_km=ohm_per_km))
    return out


@dataclass(frozen=True)
class WireStandardSpec:
    """Metadata + bundled reference table for one conductor-resistance standard."""

    id: str
    name: str
    institution: str
    material: str
    ref_temp_c: float
    quantity: str
    unit: str
    license: str
    license_url: str
    citation: str
    homepage_url: str
    what_it_validates: tuple[str, ...]
    notes: str = ""
    _rows: list[WireRefRow] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("_rows", None)
        d["what_it_validates"] = list(self.what_it_validates)
        d["n_points"] = len(self._rows)
        return d

    def reference(self) -> WireReference:
        """Materialize this standard as a :class:`WireReference` for the engine."""
        return WireReference(
            standard_id=self.id,
            material=self.material,
            ref_temp_c=self.ref_temp_c,
            rows=list(self._rows),
            quantity=self.quantity,
            unit=self.unit,
            data_source="bundled-standard",
            notes=self.notes,
        )


_COPPER_GAUGES = [18, 16, 14, 12, 10, 8, 6, 4, 2, 0]
_ALUMINUM_GAUGES = [8, 6, 4, 2, 0]

STANDARDS: list[WireStandardSpec] = [
    WireStandardSpec(
        id="copper-annealed-20c",
        name="Annealed copper DC resistance @ 20 °C",
        institution="IEC 60228 / ASTM B193 (IACS)",
        material="copper",
        ref_temp_c=20.0,
        quantity="dc_resistance",
        unit="Ω/km",
        license="Physical reference data (facts, not copyrightable)",
        license_url="https://en.wikipedia.org/wiki/International_Annealed_Copper_Standard",
        citation="International Annealed Copper Standard (IACS): annealed copper "
        "resistivity 1.7241×10⁻⁸ Ω·m at 20 °C; IEC 60228 conductor classes.",
        homepage_url="https://en.wikipedia.org/wiki/American_wire_gauge",
        what_it_validates=(
            "AWG cross-section → resistance relation",
            "copper resistivity vs the annealed (IACS) standard",
        ),
        notes="Solid annealed copper, computed R = ρ·L/A with ρ=1.7241e-8 Ω·m. "
        "Simura models pure copper (1.68e-8), so a small negative bias (~2–3%) "
        "is expected and correct.",
        _rows=_rows("copper", _COPPER_GAUGES, 20.0),
    ),
    WireStandardSpec(
        id="copper-annealed-75c",
        name="Annealed copper DC resistance @ 75 °C",
        institution="IEC 60228 / ASTM B193 (IACS)",
        material="copper",
        ref_temp_c=75.0,
        quantity="dc_resistance",
        unit="Ω/km",
        license="Physical reference data (facts, not copyrightable)",
        license_url="https://en.wikipedia.org/wiki/Electrical_resistivity_and_conductivity",
        citation="IACS annealed copper temperature-corrected to 75 °C using the "
        "standard coefficient α = 0.00393 /K.",
        homepage_url="https://en.wikipedia.org/wiki/American_wire_gauge",
        what_it_validates=(
            "resistance temperature coefficient (20 °C → 75 °C)",
            "elevated-temperature resistance at a typical conductor rating",
        ),
        notes="Same annealed-copper basis as the 20 °C standard, scaled by "
        "(1 + α·55). Checks Simura's linear ρ(T) model at operating temperature.",
        _rows=_rows("copper", _COPPER_GAUGES, 75.0),
    ),
    WireStandardSpec(
        id="aluminum-20c",
        name="Hard-drawn aluminium DC resistance @ 20 °C",
        institution="IEC 60228",
        material="aluminum",
        ref_temp_c=20.0,
        quantity="dc_resistance",
        unit="Ω/km",
        license="Physical reference data (facts, not copyrightable)",
        license_url="https://en.wikipedia.org/wiki/Electrical_resistivity_and_conductivity",
        citation="IEC 60228 hard-drawn aluminium, resistivity 2.82×10⁻⁸ Ω·m at 20 °C.",
        homepage_url="https://en.wikipedia.org/wiki/American_wire_gauge",
        what_it_validates=(
            "aluminium resistivity path (the second conductor material)",
            "AWG cross-section → resistance for feeder-sized gauges",
        ),
        notes="Solid hard-drawn aluminium (ρ=2.82e-8 Ω·m) vs Simura's 2.65e-8; "
        "expect the model a few percent below the standard.",
        _rows=_rows("aluminum", _ALUMINUM_GAUGES, 20.0),
    ),
]

_BY_ID = {s.id: s for s in STANDARDS}


def list_standards() -> list[WireStandardSpec]:
    """Every bundled conductor-resistance standard."""
    return list(STANDARDS)


def get_standard(standard_id: str) -> WireStandardSpec:
    """Look up one standard by id, with a helpful error listing the known ids."""
    try:
        return _BY_ID[standard_id]
    except KeyError:
        known = ", ".join(sorted(_BY_ID))
        raise KeyError(f"unknown wire standard '{standard_id}'. known ids: {known}") from None
