"""A curated catalog of published lighting standards and reference data.

The lighting analog of :mod:`simura.validate.catalog` (battery datasets) and
:mod:`simura.wires.validation.standards` (conductor resistance tables). All of it
is compact public reference data, so the whole validation runs offline out of the
box.

Five standards, deliberately chosen to check the model at five different depths
rather than five variations of the same thing:

1. **The observer.** ``V(lambda)`` from the CIE 1931 tables against the analytic
   fit this package uses. Everything photometric rests on this curve, so if it is
   wrong nothing above it can be right.
2. **The colour maths.** The correlated colour temperature of a blackbody is, by
   definition, its own temperature -- the Planckian locus *is* the reference. Any
   error here is the combined error of the spectral integration, the chromaticity
   transform and McCamy's approximation.
3. **The whole lamp.** Published luminous efficacy for twenty real lamps spanning
   four physical families and a fifteen-fold range of lm/W. This is the end-to-end
   check: spectrum, energy balance, thermal state and photometry, all at once,
   against what manufacturers actually print.
4. **Solid-state derating.** Relative LED output against junction temperature.
5. **Vapour-pressure response.** Relative fluorescent output against ambient
   temperature -- the derating that runs the opposite way from an LED's.

Honesty notes, per standard, in ``notes``. The short version: (1) and (2) are
exact references and the residual is purely the model's own approximation error;
(3) compares against manufacturer figures that themselves vary by tens of percent
between products, so a few percent of spread is expected and a systematic bias is
the interesting signal; (4) and (5) are *typical* published curves, not any one
product's test report.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..catalog import LAMP_CATALOG
from .reference import LightReference, LightRefRow

# ---------------------------------------------------------------------------
# 1. The CIE 1931 photopic luminosity function, V(lambda).
#
# The tabulated 2-degree standard observer's y-bar, at 5-20 nm intervals across
# the visible band. These are the defining values of photometry: the candela is
# fixed by 683 lm/W at 555 nm, where this curve is 1.0 by construction.
# ---------------------------------------------------------------------------
_CIE_PHOTOPIC: list[tuple[float, float]] = [
    (400.0, 0.0004), (420.0, 0.0040), (440.0, 0.0230), (450.0, 0.0380),
    (460.0, 0.0600), (470.0, 0.0910), (480.0, 0.1390), (490.0, 0.2080),
    (500.0, 0.3230), (510.0, 0.5030), (520.0, 0.7100), (530.0, 0.8620),
    (540.0, 0.9540), (550.0, 0.9950), (555.0, 1.0000), (560.0, 0.9950),
    (570.0, 0.9520), (580.0, 0.8700), (590.0, 0.7570), (600.0, 0.6310),
    (610.0, 0.5030), (620.0, 0.3810), (630.0, 0.2650), (640.0, 0.1750),
    (650.0, 0.1070), (660.0, 0.0610), (670.0, 0.0320), (680.0, 0.0170),
    (700.0, 0.0041), (720.0, 0.00105),
]

# ---------------------------------------------------------------------------
# 2. The Planckian locus. A blackbody at T has, by definition, a correlated
#    colour temperature of exactly T -- so the reference column is the input.
# ---------------------------------------------------------------------------
_LOCUS_TEMPS: list[float] = [
    1800.0, 2000.0, 2200.0, 2400.0, 2700.0, 3000.0, 3500.0, 4000.0,
    4500.0, 5000.0, 5500.0, 6000.0, 6500.0, 7000.0, 8000.0, 10000.0,
]

# ---------------------------------------------------------------------------
# 4. Relative luminous flux of a typical white LED against junction temperature,
#    normalized to 1.0 at 25 C. The shape every mid-power LED datasheet shows:
#    close to linear, losing roughly 0.2%/K -- but only close. Real curves are
#    gently concave, flattening at low junction temperatures and steepening at
#    high ones, and Simura's derating is a straight line. That difference is the
#    point of the standard: a reference that was itself a straight line with the
#    model's own coefficient would validate nothing at all.
# ---------------------------------------------------------------------------
_LED_JUNCTION_DERATING: list[tuple[float, float]] = [
    (-20.0, 1.090), (0.0, 1.048), (25.0, 1.000), (40.0, 0.972),
    (55.0, 0.943), (70.0, 0.912), (85.0, 0.880), (100.0, 0.845),
    (115.0, 0.808),
]

# ---------------------------------------------------------------------------
# 5. Relative light output of a T8 fluorescent lamp against ambient temperature,
#    normalized to 1.0 at its 25 C optimum. Falls off both ways, because ambient
#    sets the mercury vapour pressure and the 254 nm resonance output peaks at
#    one pressure.
# ---------------------------------------------------------------------------
_FLUORESCENT_AMBIENT_RESPONSE: list[tuple[float, float]] = [
    (-20.0, 0.20), (-10.0, 0.35), (0.0, 0.56), (10.0, 0.79),
    (20.0, 0.975), (25.0, 1.00), (30.0, 0.975), (40.0, 0.87),
    (50.0, 0.70), (60.0, 0.50),
]


@dataclass(frozen=True)
class LightStandardSpec:
    """Metadata + bundled reference table for one lighting standard."""

    id: str
    name: str
    institution: str
    quantity: str
    unit: str
    x_label: str
    x_unit: str
    license: str
    license_url: str
    citation: str
    homepage_url: str
    what_it_validates: tuple[str, ...]
    notes: str = ""
    _rows: list[LightRefRow] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("_rows", None)
        d["what_it_validates"] = list(self.what_it_validates)
        d["n_points"] = len(self._rows)
        return d

    def reference(self) -> LightReference:
        """Materialize this standard as a :class:`LightReference` for the engine."""
        return LightReference(
            standard_id=self.id,
            quantity=self.quantity,
            rows=list(self._rows),
            unit=self.unit,
            x_label=self.x_label,
            x_unit=self.x_unit,
            data_source="bundled-standard",
            notes=self.notes,
        )


def _lamp_efficacy_rows() -> list[LightRefRow]:
    """One row per catalog lamp: its published luminous efficacy."""
    return [
        LightRefRow(
            key=lamp.id,
            x=lamp.rated_power_w,
            published=lamp.published_efficacy_lm_per_w,
            context=lamp.id,
        )
        for lamp in LAMP_CATALOG
    ]


STANDARDS: list[LightStandardSpec] = [
    LightStandardSpec(
        id="cie-photopic-1931",
        name="CIE 1931 photopic luminosity function V(λ)",
        institution="CIE (Commission Internationale de l'Éclairage)",
        quantity="photopic_response",
        unit="relative",
        x_label="wavelength",
        x_unit="nm",
        license="Physical/perceptual reference data (facts, not copyrightable)",
        license_url="https://en.wikipedia.org/wiki/Luminous_efficiency_function",
        citation="CIE 1931 2° standard observer, ȳ(λ); the basis of the candela "
        "(CGPM 1979: 683 lm/W at 540 THz ≈ 555 nm).",
        homepage_url="https://en.wikipedia.org/wiki/CIE_1931_color_space",
        what_it_validates=(
            "the analytic colour-matching fit against the tabulated observer",
            "the foundation every lumen in this package is computed from",
        ),
        notes="Simura uses the Wyman–Sloan–Shirley (2013) multi-lobe Gaussian fit "
        "rather than the tabulated curve, so this measures that approximation "
        "directly. Errors are largest in the far tails, where V(λ) is near zero "
        "and a small absolute error is a large relative one — which is why the "
        "report gives absolute error alongside percent.",
        _rows=[
            LightRefRow(key=f"{nm:.0f} nm", x=nm, published=v)
            for nm, v in _CIE_PHOTOPIC
        ],
    ),
    LightStandardSpec(
        id="blackbody-cct-locus",
        name="Correlated colour temperature on the Planckian locus",
        institution="CIE / Planck's law",
        quantity="color_temperature",
        unit="K",
        x_label="blackbody temperature",
        x_unit="K",
        license="Physical reference data (facts, not copyrightable)",
        license_url="https://en.wikipedia.org/wiki/Planckian_locus",
        citation="A Planckian radiator at temperature T has, by definition, a "
        "correlated colour temperature of T. McCamy (1992), Color Research & "
        "Application 17(2), gives the cubic approximation used here.",
        homepage_url="https://en.wikipedia.org/wiki/Correlated_color_temperature",
        what_it_validates=(
            "Planck's law integrated against the CIE observer",
            "the chromaticity transform and McCamy's CCT approximation",
        ),
        notes="An exact reference: the answer is the input. Every kelvin of error "
        "is the model's own, accumulated through the spectral integration, the "
        "tristimulus transform and the CCT fit. Expect the largest errors below "
        "2000 K, where McCamy's approximation is furthest from its fitted range.",
        _rows=[
            LightRefRow(key=f"{t:.0f} K", x=t, published=t) for t in _LOCUS_TEMPS
        ],
    ),
    LightStandardSpec(
        id="lamp-efficacy-published",
        name="Published luminous efficacy of real lamps",
        institution="Manufacturer catalogue data (GE / Osram / Philips)",
        quantity="luminous_efficacy",
        unit="lm/W",
        x_label="rated power",
        x_unit="W",
        license="Published product specifications (facts, not copyrightable)",
        license_url="https://en.wikipedia.org/wiki/Luminous_efficacy",
        citation="Long-established general-service lamp catalogue figures: rated "
        "luminous flux divided by rated system power, per lamp.",
        homepage_url="https://en.wikipedia.org/wiki/Luminous_efficacy",
        what_it_validates=(
            "the whole chain end to end: spectrum → energy balance → photometry",
            "all four source families against each other on one scale",
            "that efficacy is predicted, not tabulated",
        ),
        notes="The demanding one. Simura computes each lamp's efficacy from its "
        "spectrum and energy balance and never consults the published figure, so "
        "this is a genuine prediction across a fifteen-fold range of lm/W. "
        "Manufacturer figures themselves vary by tens of percent between products "
        "of the same technology, so a few percent of scatter is expected — a "
        "systematic bias, or one family being consistently wrong, is the signal "
        "worth acting on.",
        _rows=_lamp_efficacy_rows(),
    ),
    LightStandardSpec(
        id="led-junction-derating",
        name="LED relative flux vs junction temperature",
        institution="Typical white-LED datasheet (mid-power, phosphor-converted)",
        quantity="flux_vs_junction_temp",
        unit="relative to 25 °C",
        x_label="junction temperature",
        x_unit="°C",
        license="Typical published characteristic (facts, not copyrightable)",
        license_url="https://en.wikipedia.org/wiki/Light-emitting_diode",
        citation="Representative relative-luminous-flux vs junction-temperature "
        "characteristic for a phosphor-converted white LED, normalised at 25 °C "
        "(≈ −0.22%/K).",
        homepage_url="https://en.wikipedia.org/wiki/Light-emitting_diode",
        what_it_validates=(
            "the solid-state thermal derating law",
            "that an LED gets dimmer as it gets hotter, by the right amount",
        ),
        notes="A *typical* curve, not one product's test report — real parts range "
        "from about −0.1%/K for the best modern dies to −0.5%/K for older or "
        "high-power ones. The reference is gently concave where Simura's derating "
        "is a straight line, so the residual is the cost of that linearisation: "
        "small in the middle of the range and largest at both ends.",
        _rows=[
            LightRefRow(key=f"{t:.0f} °C", x=t, published=v)
            for t, v in _LED_JUNCTION_DERATING
        ],
    ),
    LightStandardSpec(
        id="fluorescent-ambient-response",
        name="Fluorescent relative output vs ambient temperature",
        institution="Typical T8 linear fluorescent characteristic",
        quantity="flux_vs_ambient_temp",
        unit="relative to 25 °C",
        x_label="ambient temperature",
        x_unit="°C",
        license="Typical published characteristic (facts, not copyrightable)",
        license_url="https://en.wikipedia.org/wiki/Fluorescent_lamp",
        citation="Representative relative-light-output vs ambient-temperature "
        "characteristic for a T8 linear fluorescent lamp, peaking near 25 °C where "
        "the mercury vapour pressure optimises the 254 nm resonance output.",
        homepage_url="https://en.wikipedia.org/wiki/Fluorescent_lamp",
        what_it_validates=(
            "the low-pressure discharge vapour-pressure response",
            "that a cold fluorescent tube is a dim one — the failure mode that "
            "drove unheated spaces to LED",
        ),
        notes="Simura models this as a Gaussian about the optimum, which is a "
        "smooth stand-in for a genuinely asymmetric curve: real tubes fall off "
        "faster below the optimum than above it. Expect the residual to be "
        "one-sided at the cold end, and read that as the model's shape being "
        "approximate rather than its placement being wrong.",
        _rows=[
            LightRefRow(key=f"{t:.0f} °C", x=t, published=v)
            for t, v in _FLUORESCENT_AMBIENT_RESPONSE
        ],
    ),
]

_BY_ID = {s.id: s for s in STANDARDS}


def list_standards() -> list[LightStandardSpec]:
    """Every bundled lighting standard."""
    return list(STANDARDS)


def get_standard(standard_id: str) -> LightStandardSpec:
    """Look up one standard by id, with a helpful error listing the known ids."""
    try:
        return _BY_ID[standard_id]
    except KeyError:
        known = ", ".join(sorted(_BY_ID))
        raise KeyError(f"unknown light standard '{standard_id}'. known ids: {known}") from None
