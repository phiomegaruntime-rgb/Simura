"""Getting the building to the right size.

The single most common way a BIM import goes wrong is not geometry -- it is
units. A model authored in millimetres and read as metres produces a perfectly
valid, perfectly plausible plan of a building 1000 times too big, and every
number downstream is wrong by a factor nobody notices until a corridor turns out
to be 40 km long. Worse, it *sometimes* looks right: a 6000 mm room read as
6000 m is obviously wrong, but a site plan in feet read as metres is only out by
3.28 and just looks like a slightly generous office.

So unit handling gets its own module, three rules, and a test:

1. **Convert at the edge.** Each importer resolves its file's unit once and
   multiplies on the way in. Below :mod:`simura.space.plan`, everything is metres
   and nothing carries a unit.
2. **Record what it was.** ``FloorPlan.source_units`` keeps the original, so a
   number that looks wrong can be checked against the assumption that produced it.
3. **A guessed unit is an inference.** When a file does not declare its unit, the
   importer picks one *and logs it* -- because "assumed millimetres" is precisely
   the sentence somebody needs to read when the plan comes out too small.
"""

from __future__ import annotations

# Metres per unit. Names are the ones the source formats actually use, lower-cased.
UNIT_FACTORS: dict[str, float] = {
    "m": 1.0,
    "metre": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "metres": 1.0,
    "dm": 0.1,
    "decimetre": 0.1,
    "cm": 0.01,
    "centimetre": 0.01,
    "centimeters": 0.01,
    "mm": 0.001,
    "millimetre": 0.001,
    "millimeters": 0.001,
    "km": 1000.0,
    "in": 0.0254,
    "inch": 0.0254,
    "inches": 0.0254,
    "ft": 0.3048,
    "foot": 0.3048,
    "feet": 0.3048,
    "yd": 0.9144,
    "yard": 0.9144,
    "mi": 1609.344,
}

# IFC writes its units as an SI prefix on a base unit, e.g.
# IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.). This is that prefix table.
SI_PREFIXES: dict[str, float] = {
    "EXA": 1e18,
    "PETA": 1e15,
    "TERA": 1e12,
    "GIGA": 1e9,
    "MEGA": 1e6,
    "KILO": 1e3,
    "HECTO": 1e2,
    "DECA": 1e1,
    "DECI": 1e-1,
    "CENTI": 1e-2,
    "MILLI": 1e-3,
    "MICRO": 1e-6,
    "NANO": 1e-9,
}

# DXF stores its unit as an integer code in $INSUNITS. 0 means "unitless", which
# is the case that forces a guess -- see `guess_scale`.
DXF_INSUNITS: dict[int, str] = {
    0: "",
    1: "in",
    2: "ft",
    3: "mi",
    4: "mm",
    5: "cm",
    6: "m",
    7: "km",
    8: "microinch",
    9: "mil",
    10: "yd",
    11: "angstrom",
    12: "nm",
    13: "micron",
    14: "dm",
    15: "deca",
    16: "hecto",
    17: "gigameter",
    18: "au",
    19: "lightyear",
    20: "parsec",
}


def factor(unit: str) -> float:
    """Metres per ``unit``. Unknown units are 1.0 -- the caller must log that."""
    return UNIT_FACTORS.get(str(unit or "").strip().lower(), 1.0)


def known(unit: str) -> bool:
    """True when the unit is one this module can convert exactly."""
    return str(unit or "").strip().lower() in UNIT_FACTORS


def to_metres(value: float, unit: str) -> float:
    """One length, converted."""
    return float(value) * factor(unit)


def si_length_factor(prefix: str, base: str = "METRE") -> float:
    """Metres per IFC SI length unit, from its prefix and base.

    ``IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.)`` is ``("MILLI", "METRE")`` and
    gives 0.001.
    """
    if str(base).strip().upper().rstrip("S") not in ("METRE", "METER"):
        return 1.0
    return SI_PREFIXES.get(str(prefix or "").strip().upper(), 1.0)


def guess_scale(extent: float) -> tuple[float, str, str]:
    """Guess a unit from how big the drawing is. Returns ``(factor, unit, basis)``.

    Only for files that genuinely do not declare one -- an unlabelled DXF is the
    common case. The reasoning is a building-shaped prior: buildings are tens of
    metres across, so a drawing whose longest extent is in the thousands is
    millimetres and one in the tens is metres. It is a guess, it says it is a
    guess, and the caller is required to log it as an inference.

    The middle of the range is genuinely ambiguous -- a 300-unit drawing is either
    a 300 m campus or a 3 m room in centimetres -- so it resolves to metres and
    says which choice it made rather than pretending the number decided.
    """
    extent = abs(float(extent))
    if extent <= 0:
        return (1.0, "m", "empty drawing; assumed metres")
    if extent > 5000:
        return (0.001, "mm", f"drawing spans {extent:.0f} units; assumed millimetres")
    if extent > 500:
        return (0.01, "cm", f"drawing spans {extent:.0f} units; assumed centimetres")
    return (1.0, "m", f"drawing spans {extent:.0f} units; assumed metres")


def plausible_building(width_m: float, depth_m: float) -> tuple[bool, str]:
    """Does this look like a building at all? Returns ``(ok, complaint)``.

    The backstop for a unit error that got through everything above. It cannot
    tell a correct plan from a wrong one, but it can tell a *building* from a
    building-shaped thing the size of a postage stamp or a county -- which is what
    a factor-of-1000 error actually produces, and it is worth one warning in the
    fidelity record rather than a silent pass.
    """
    span = max(abs(width_m), abs(depth_m))
    if span <= 0:
        return (False, "the plan has no extent")
    if span < 1.0:
        return (
            False,
            f"the whole plan spans {span * 1000:.0f} mm — the source units are "
            f"probably wrong (a building read as though it were drawn in metres "
            f"when it was drawn in millimetres looks like this)",
        )
    if span > 5000.0:
        return (
            False,
            f"the whole plan spans {span / 1000:.1f} km — the source units are "
            f"probably wrong (millimetres read as metres looks like this)",
        )
    return (True, "")
