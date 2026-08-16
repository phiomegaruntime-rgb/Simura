"""Spectral physics: Planck's law, the CIE observer, luminous efficacy and CCT.

This is the *bottom* of the lights component -- the layer everything above is
derived from. A light source is, physically, a spectral power distribution (SPD):
how many watts it radiates at each wavelength. Everything a lighting engineer
actually quotes falls out of that SPD and the human eye's response to it:

    Luminous flux      Phi_v = 683 * integral( Phi_e(lambda) * V(lambda) dlambda )
    Efficacy of radiation  LER = Phi_v / integral( Phi_e(lambda) dlambda )   [lm/W_radiant]
    Chromaticity       X,Y,Z = integral( Phi_e * xbar,ybar,zbar dlambda ) -> (x, y)
    Correlated colour temperature  CCT = f(x, y)

Deriving efficacy this way -- rather than looking it up in a table -- is what
makes the model *predictive*. Dim an incandescent lamp and its filament cools;
the Planck curve slides into the infrared; ``LER`` collapses and the light goes
orange. Nothing in the code says "dim lamps look orange": it emerges.

Two constants define the photometric scale:

* ``K_M = 683 lm/W`` -- the luminous efficacy of 555 nm radiation, the definition
  of the candela (CGPM 1979).
* ``V(lambda)`` -- the CIE 1924 photopic luminosity function, here as the
  ``ybar`` of the CIE 1931 2-degree standard observer.

The colour-matching functions use the multi-lobe piecewise-Gaussian analytic fit
of Wyman, Sloan & Shirley (2013), *Simple Analytic Approximations to the CIE XYZ
Colour Matching Functions*, Journal of Computer Graphics Techniques 2(2). It
reproduces the tabulated observer to well under a percent while keeping this
module a few dozen lines of pure standard library -- and, because the fit is an
approximation, the error it introduces is itself something
:mod:`simura.lights.validation` measures rather than assumes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

# -- physical constants (SI, CODATA) --------------------------------------
H_PLANCK = 6.62607015e-34        # J*s
C_LIGHT = 2.99792458e8           # m/s
K_BOLTZMANN = 1.380649e-23       # J/K
SIGMA_SB = 5.670374419e-8        # W/(m^2*K^4), Stefan-Boltzmann
WIEN_B = 2.897771955e-3          # m*K, Wien displacement constant

# The photometric scale: 683 lm/W at 555 nm defines the candela.
K_M = 683.0

# How far a chromaticity may sit from the Planckian locus (Euclidean, in CIE 1931
# xy) before a correlated colour temperature stops meaning anything. The usual
# convention is |Duv| <= 0.05 in the uv plane; this is its rough xy equivalent.
MAX_LOCUS_DISTANCE = 0.06

# The wavelength grid every SPD in this package is sampled on. 360-830 nm is the
# CIE observer's full domain; 1 nm steps make the integrals exact enough that the
# discretization is never the thing being measured.
LAMBDA_MIN_NM = 360.0
LAMBDA_MAX_NM = 830.0
LAMBDA_STEP_NM = 1.0

WAVELENGTHS_NM: tuple[float, ...] = tuple(
    LAMBDA_MIN_NM + i * LAMBDA_STEP_NM
    for i in range(int((LAMBDA_MAX_NM - LAMBDA_MIN_NM) / LAMBDA_STEP_NM) + 1)
)


# -- the CIE 1931 2-degree standard observer ------------------------------
def _lobe(x: float, mu: float, sigma1: float, sigma2: float) -> float:
    """One piecewise-Gaussian lobe: narrower on one side of the peak than the other."""
    sigma = sigma1 if x < mu else sigma2
    t = (x - mu) / sigma
    return math.exp(-0.5 * t * t)


def xbar(nm: float) -> float:
    """CIE 1931 2-degree ``x`` colour-matching function (analytic fit)."""
    return (
        1.056 * _lobe(nm, 599.8, 37.9, 31.0)
        + 0.362 * _lobe(nm, 442.0, 16.0, 26.7)
        - 0.065 * _lobe(nm, 501.1, 20.4, 26.2)
    )


def ybar(nm: float) -> float:
    """CIE 1931 2-degree ``y`` function -- i.e. ``V(lambda)``, the eye's sensitivity."""
    return 0.821 * _lobe(nm, 568.8, 46.9, 40.5) + 0.286 * _lobe(nm, 530.9, 16.3, 31.1)


def zbar(nm: float) -> float:
    """CIE 1931 2-degree ``z`` colour-matching function (analytic fit)."""
    return 1.217 * _lobe(nm, 437.0, 11.8, 36.0) + 0.681 * _lobe(nm, 459.0, 26.0, 13.8)


def photopic(nm: float) -> float:
    """``V(lambda)``: relative luminous sensitivity of the light-adapted eye."""
    return ybar(nm)


# Precomputed observer over the standard grid -- built once, reused by every SPD.
_XBAR: tuple[float, ...] = tuple(xbar(w) for w in WAVELENGTHS_NM)
_YBAR: tuple[float, ...] = tuple(ybar(w) for w in WAVELENGTHS_NM)
_ZBAR: tuple[float, ...] = tuple(zbar(w) for w in WAVELENGTHS_NM)


# -- Planck's law ----------------------------------------------------------
def planck_exitance(nm: float, temp_k: float) -> float:
    """Spectral radiant exitance of a blackbody, W/(m^2*nm), at ``nm`` and ``temp_k``.

    ``M(lambda,T) = 2*pi*h*c^2 / lambda^5 / (exp(h*c/(lambda*k*T)) - 1)``, converted
    from per-metre to per-nanometre. Only *relative* shape matters for colour and
    efficacy, but the absolute form keeps the units honest.
    """
    if temp_k <= 0.0:
        return 0.0
    lam_m = nm * 1e-9
    x = H_PLANCK * C_LIGHT / (lam_m * K_BOLTZMANN * temp_k)
    if x > 700.0:                       # exp overflows long before this matters
        return 0.0
    denom = math.expm1(x)
    if denom <= 0.0:
        return 0.0
    m_per_m = 2.0 * math.pi * H_PLANCK * C_LIGHT ** 2 / lam_m ** 5 / denom
    return m_per_m * 1e-9               # per metre -> per nanometre


def wien_peak_nm(temp_k: float) -> float:
    """Wavelength of peak spectral exitance (Wien's displacement law), in nm."""
    return WIEN_B / max(temp_k, 1e-9) * 1e9


# -- the spectral power distribution --------------------------------------
@dataclass(frozen=True)
class Spectrum:
    """A sampled spectral power distribution on :data:`WAVELENGTHS_NM`.

    ``values`` are spectral power per nanometre (any consistent unit -- everything
    this class reports is a ratio or a chromaticity, so the scale cancels). Build
    one with :func:`blackbody`, :func:`gaussian_band`, :func:`emission_lines` or
    :func:`phosphor_led`, and combine with ``+``.

    ``out_of_band_power`` is radiant power **outside** 360-830 nm. The grid stops
    where the CIE observer does, but a thermal radiator puts most of its watts in
    the infrared, and leaving them out would flatter every incandescent lamp by an
    order of magnitude. :func:`blackbody` fills this in exactly, from
    Stefan-Boltzmann minus the in-band integral; sources that radiate essentially
    nothing outside the visible (an LED die, an arc line) leave it at zero.
    """

    values: tuple[float, ...]
    out_of_band_power: float = 0.0

    def __post_init__(self) -> None:
        if len(self.values) != len(WAVELENGTHS_NM):
            raise ValueError(
                f"a Spectrum must be sampled on the standard grid "
                f"({len(WAVELENGTHS_NM)} points), got {len(self.values)}"
            )

    # -- combination ------------------------------------------------------
    def __add__(self, other: "Spectrum") -> "Spectrum":
        return Spectrum(
            tuple(a + b for a, b in zip(self.values, other.values)),
            self.out_of_band_power + other.out_of_band_power,
        )

    def scaled(self, factor: float) -> "Spectrum":
        return Spectrum(
            tuple(v * factor for v in self.values), self.out_of_band_power * factor
        )

    def normalized(self) -> "Spectrum":
        """Unit total radiant power, so spectra can be mixed by weight."""
        total = self.radiant_power
        return self if total <= 0 else self.scaled(1.0 / total)

    # -- integrals --------------------------------------------------------
    @property
    def in_band_power(self) -> float:
        """``integral(Phi_e dlambda)`` over 360-830 nm only."""
        return sum(self.values) * LAMBDA_STEP_NM

    @property
    def radiant_power(self) -> float:
        """Total radiated power, including whatever falls outside the grid."""
        return self.in_band_power + self.out_of_band_power

    @property
    def luminous_power(self) -> float:
        """``683 * integral(Phi_e * V dlambda)`` -- luminous flux, lm per unit SPD."""
        acc = 0.0
        for v, y in zip(self.values, _YBAR):
            acc += v * y
        return K_M * acc * LAMBDA_STEP_NM

    @property
    def ler_lm_per_w(self) -> float:
        """Luminous efficacy **of radiation**: lumens per radiated watt.

        This is the ceiling a source of this colour could reach if every electrical
        watt became radiation in this spectrum. It peaks near 95 lm/W for a
        blackbody (~6600 K) and reaches ~683 lm/W for pure 555 nm light -- which is
        why low-pressure sodium, radiating one yellow line, is the most efficacious
        lamp ever built and renders colour not at all.
        """
        radiant = self.radiant_power
        return 0.0 if radiant <= 0 else self.luminous_power / radiant

    # -- colour -----------------------------------------------------------
    def xyz(self) -> tuple[float, float, float]:
        """CIE 1931 tristimulus values (unnormalized)."""
        x = y = z = 0.0
        for v, xb, yb, zb in zip(self.values, _XBAR, _YBAR, _ZBAR):
            x += v * xb
            y += v * yb
            z += v * zb
        s = LAMBDA_STEP_NM
        return x * s, y * s, z * s

    def chromaticity(self) -> tuple[float, float]:
        """CIE 1931 ``(x, y)`` chromaticity coordinates."""
        x, y, z = self.xyz()
        total = x + y + z
        if total <= 0:
            return 0.0, 0.0
        return x / total, y / total

    def cct_k(self) -> float:
        """Correlated colour temperature (K) via McCamy's cubic approximation.

        McCamy (1992), *Correlated colour temperature as an explicit function of
        chromaticity coordinates*: accurate to a few kelvin from ~2000 K to
        ~12000 K near the Planckian locus, which covers every lamp in the catalog.

        Returns 0.0 when the chromaticity sits too far off the Planckian locus for
        a colour *temperature* to mean anything. That is not a failure -- it is the
        correct answer for a monochromatic source. A green laser or a low-pressure
        sodium lamp has a colour, but it is not the colour of anything hot, and
        quoting a CCT for it would be an invention.
        """
        x, y = self.chromaticity()
        denom = 0.1858 - y
        if abs(denom) < 1e-9:
            return 0.0
        n = (x - 0.3320) / denom
        cct = 449.0 * n ** 3 + 3525.0 * n ** 2 + 6823.3 * n + 5520.33
        if not 800.0 <= cct <= 25000.0:
            return 0.0
        # Guard: how far is this chromaticity from the blackbody of that temperature?
        bx, by = blackbody(cct).chromaticity()
        if math.hypot(x - bx, y - by) > MAX_LOCUS_DISTANCE:
            return 0.0
        return cct

    def dominant_wavelength_nm(self) -> float:
        """Wavelength carrying the most spectral power -- the source's visual 'colour'."""
        best_i = max(range(len(self.values)), key=lambda i: self.values[i])
        return WAVELENGTHS_NM[best_i]

    def visible_fraction(self) -> float:
        """Share of radiant power that lands inside 380-780 nm.

        The rest is infrared (an incandescent lamp's dominant output) or
        ultraviolet. Not an efficacy -- a bookkeeping split that explains *where*
        a thermal radiator's watts go.
        """
        total = self.radiant_power
        if total <= 0:
            return 0.0
        acc = 0.0
        for w, v in zip(WAVELENGTHS_NM, self.values):
            if 380.0 <= w <= 780.0:
                acc += v
        return acc * LAMBDA_STEP_NM / total

    def spectral_coverage(self) -> float:
        """A 0..1 proxy for how *completely* the spectrum fills the visible band.

        Honesty note: this is **not** CIE Ra. Computing a real colour-rendering
        index needs the 8 (or 14) CIE test-colour samples and a reference
        illuminant, which this package deliberately does not carry. What this does
        is measure the fraction of 380-780 nm in which the source radiates at least
        1% of its own peak -- a continuum radiator scores near 1, a line source
        near 0 -- and it tracks published CRI well enough to *rank* sources. The
        catalog's ``cri`` field carries the published figure; use that when the
        number matters.
        """
        peak = max(self.values) if self.values else 0.0
        if peak <= 0:
            return 0.0
        floor = 0.01 * peak
        inside = [v for w, v in zip(WAVELENGTHS_NM, self.values) if 380.0 <= w <= 780.0]
        if not inside:
            return 0.0
        return sum(1 for v in inside if v >= floor) / len(inside)


# -- SPD builders ----------------------------------------------------------
def blackbody(temp_k: float, emissivity: float = 1.0) -> Spectrum:
    """The Planck spectrum of a thermal radiator at ``temp_k``.

    The infrared beyond 830 nm is where a filament lamp's watts actually go, so
    the out-of-band power is filled in exactly: Stefan-Boltzmann gives the total
    exitance ``eps*sigma*T^4`` and the in-band integral is subtracted from it. That
    is what makes the reported efficacy of radiation the real ~15 lm/W of a 2800 K
    filament rather than the ~120 lm/W its *visible* spectrum alone would suggest.

    ``emissivity`` is grey (wavelength-independent) here, so it cancels out of every
    ratio this module reports. Tungsten is *selectively* emissive -- rather more so
    in the visible than the infrared, which is worth a few lm/W in its favour -- and
    :mod:`simura.lights.lamp` applies that correction where it matters.
    """
    values = tuple(emissivity * planck_exitance(w, temp_k) for w in WAVELENGTHS_NM)
    total = emissivity * SIGMA_SB * temp_k ** 4
    in_band = sum(values) * LAMBDA_STEP_NM
    return Spectrum(values, max(0.0, total - in_band))


def selective_thermal(
    temp_k: float,
    emissivity_visible: float = 0.44,
    emissivity_ir: float = 0.28,
    visible_slope_per_nm: float = 0.0,
) -> Spectrum:
    """A thermal radiator whose emissivity differs in the visible and the infrared.

    Tungsten is not a greybody: it emits roughly ``0.43-0.45`` of a blackbody
    across the visible but only about ``0.25-0.30`` out in the infrared, where a
    filament dumps ~90% of its power. Radiating *selectively* in the band the eye
    can use is worth about 50% more efficacy than the equivalent blackbody -- a
    2800 K filament reaches ~22 lm/W of radiation against a blackbody's ~15 -- and
    no filament lamp's numbers come out right without it.

    ``visible_slope_per_nm`` tilts the in-band emissivity with wavelength (tungsten
    falls very slightly towards the red); the out-of-band infrared is treated as
    grey at ``emissivity_ir``.
    """
    values = []
    for w in WAVELENGTHS_NM:
        eps = emissivity_visible + visible_slope_per_nm * (w - 555.0)
        values.append(max(0.0, eps) * planck_exitance(w, temp_k))
    # Out-of-band: total blackbody exitance minus its in-band part, times eps_ir.
    bb_in_band = sum(planck_exitance(w, temp_k) for w in WAVELENGTHS_NM) * LAMBDA_STEP_NM
    bb_total = SIGMA_SB * temp_k ** 4
    return Spectrum(tuple(values), emissivity_ir * max(0.0, bb_total - bb_in_band))


def arc_continuum(temp_k: float) -> Spectrum:
    """The *shape* of a Planck curve, with no infrared tail beyond the grid.

    High-pressure arcs (metal halide, xenon) sit on a continuum that looks
    Planckian across the visible, but they are not blackbodies: there is no
    ``sigma*T^4`` of infrared behind it, because the emitting plasma is optically
    thin outside its lines. Using :func:`blackbody` for that continuum would
    saddle an arc lamp with a filament lamp's infrared and destroy its efficacy.
    """
    return Spectrum(blackbody(temp_k).values, 0.0)


@lru_cache(maxsize=1024)
def _unit_band(center_nm: float, fwhm_nm: float) -> Spectrum:
    sigma = max(fwhm_nm, 1e-6) / 2.354820045
    vals = []
    for w in WAVELENGTHS_NM:
        t = (w - center_nm) / sigma
        vals.append(math.exp(-0.5 * t * t))
    return Spectrum(tuple(vals))


def gaussian_band(center_nm: float, fwhm_nm: float, weight: float = 1.0) -> Spectrum:
    """A Gaussian emission band -- an LED die, a phosphor, a broadened arc line.

    Cached on shape: phosphor blends are searched by re-weighting a handful of
    fixed bands, so building the band itself once pays for the whole search.
    """
    band = _unit_band(float(center_nm), float(fwhm_nm))
    return band if weight == 1.0 else band.scaled(weight)


def emission_lines(lines: list[tuple[float, float, float]]) -> Spectrum:
    """A discharge spectrum: ``[(center_nm, fwhm_nm, relative_weight), ...]``.

    Real arc discharges radiate in lines (mercury's 436/546/578 nm, sodium's 589 nm
    doublet). Pressure- and Doppler-broadening give each line a finite width, which
    is why a high-pressure lamp renders colour better than a low-pressure one.
    """
    spd = Spectrum(tuple(0.0 for _ in WAVELENGTHS_NM))
    for center, fwhm, weight in lines:
        spd = spd + gaussian_band(center, fwhm, weight)
    return spd


def phosphor_led(
    pump_nm: float = 452.0,
    pump_fwhm_nm: float = 22.0,
    phosphor_nm: float = 565.0,
    phosphor_fwhm_nm: float = 120.0,
    conversion_frac: float = 0.72,
    red_nm: float | None = None,
    red_fwhm_nm: float = 90.0,
    red_frac: float = 0.0,
) -> Spectrum:
    """A phosphor-converted white LED: a blue die under a down-converting phosphor.

    ``conversion_frac`` of the blue pump is absorbed by the phosphor and re-emitted
    as the broad yellow band; the unconverted remainder is what makes the light
    white rather than yellow. Raising it (more phosphor) warms the colour and costs
    a little efficacy to the Stokes shift. ``red_frac`` adds the red phosphor that
    high-CRI parts use -- better colour rendering, lower efficacy, exactly the real
    trade.
    """
    conv = min(max(conversion_frac, 0.0), 0.98)
    red = min(max(red_frac, 0.0), 0.9)

    # Each band carries unit radiant power before weighting, so the weights below
    # are true power shares. Stokes shift: a converted photon comes back at a
    # longer wavelength, so its energy is scaled by the wavelength ratio -- the
    # phosphor's intrinsic loss.
    spd = gaussian_band(pump_nm, pump_fwhm_nm).normalized().scaled(1.0 - conv)
    spd = spd + gaussian_band(phosphor_nm, phosphor_fwhm_nm).normalized().scaled(
        conv * (1.0 - red) * (pump_nm / phosphor_nm)
    )
    if red > 0.0:
        center = red_nm if red_nm is not None else 630.0
        spd = spd + gaussian_band(center, red_fwhm_nm, 1.0).normalized().scaled(
            conv * red * (pump_nm / center)
        )
    return spd


# -- cached thermal-radiator metrics --------------------------------------
#
# A filament's temperature is solved by iteration, and every trial temperature
# wants a fresh Planck integral over 471 wavelengths. Since the answer depends on
# nothing but the temperature and two emissivities, cache it. Temperatures are
# rounded to the kelvin, which moves efficacy by well under a tenth of a percent.

@lru_cache(maxsize=8192)
def thermal_metrics(
    temp_k_rounded: int,
    emissivity_visible: float = 0.44,
    emissivity_ir: float = 0.28,
    visible_slope_per_nm: float = 0.0,
) -> tuple[float, float, float, float]:
    """``(exitance W/m^2, LER lm/W, CCT K, visible fraction)`` for a thermal radiator.

    Call it through :func:`thermal_radiator` rather than directly -- this signature
    takes an integer temperature so the cache key is exact.
    """
    spd = selective_thermal(
        float(temp_k_rounded), emissivity_visible, emissivity_ir, visible_slope_per_nm
    )
    return spd.radiant_power, spd.ler_lm_per_w, spd.cct_k(), spd.visible_fraction()


def thermal_radiator(
    temp_k: float,
    emissivity_visible: float = 0.44,
    emissivity_ir: float = 0.28,
    visible_slope_per_nm: float = 0.0,
) -> tuple[float, float, float, float]:
    """Cached ``(exitance, LER, CCT, visible fraction)`` for a filament at ``temp_k``."""
    t = int(round(max(300.0, min(6000.0, temp_k))))
    return thermal_metrics(t, emissivity_visible, emissivity_ir, visible_slope_per_nm)


def daylight_d65() -> Spectrum:
    """A stand-in for CIE D65 -- a 6504 K blackbody, close enough for efficacy work.

    Real D65 is a measured phase-of-daylight spectrum with Fraunhofer absorption
    lines; its luminous efficacy of radiation differs from the equivalent Planckian
    by only about a percent, which is well inside everything else this package
    approximates.
    """
    return blackbody(6504.0)
