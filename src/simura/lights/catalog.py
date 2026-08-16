"""The parts bin: every light-source technology, and real lamps built from them.

Two levels, exactly as :mod:`simura.wires.catalog` separates a conductor
*material* from an off-the-shelf *wire type*:

* :class:`LightTechnology` -- **how a family of sources makes light.** The
  spectral recipe, the electrical law, how much of the input power leaves as
  radiation, how it responds to temperature, how long it takes to warm up, how it
  ages. Every number here is a physical parameter the model computes *from*, not a
  performance figure it reports.
* :class:`LampType` -- **one lamp you could actually buy.** A technology plus a
  rated power, a published luminous flux, a socket and a beam. The published flux
  is the manufacturer's claim; the model predicts its own, and
  :mod:`simura.lights.validation` measures the gap.

The families:

=================  =========================================================
``incandescent``   A hot tungsten filament radiating a Planck spectrum.
                   Includes halogen, which runs hotter thanks to the
                   regenerative halogen cycle.
``solid_state``    A semiconductor junction: LEDs (blue die + phosphor) and
                   laser diodes (a threshold current and one narrow line).
``discharge_lp``   A low-pressure arc in mercury or sodium vapour --
                   fluorescent, CFL, induction, low-pressure sodium, neon.
                   Output depends sharply on ambient temperature, because
                   ambient sets the vapour pressure.
``discharge_hp``   A high-pressure arc -- metal halide, high-pressure sodium,
                   mercury vapour, xenon short-arc. Long warm-up, and a
                   restrike delay before a hot lamp will re-ignite.
=================  =========================================================

Honesty note: the ``radiant_efficiency`` figures are representative of each
technology at its design point, drawn from the standard energy-balance breakdowns
(e.g. a fluorescent lamp turns ~60% of its input into 254 nm ultraviolet, and the
phosphor returns ~45% of that as visible light -- hence ~0.28). Real products vary
widely by wattage, vintage and manufacturer. **Specify real lighting against
photometric test reports, not against this catalog.**
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .spectrum import (
    Spectrum,
    arc_continuum,
    emission_lines,
    gaussian_band,
    phosphor_led,
    selective_thermal,
)

FAMILIES = ("incandescent", "solid_state", "discharge_lp", "discharge_hp")


@dataclass(frozen=True)
class LightTechnology:
    """The physics of one light-source family."""

    key: str
    name: str
    family: str

    # -- spectrum ---------------------------------------------------------
    # "thermal"      -> selective_thermal(T), T from the filament model at runtime
    # "phosphor_led" -> a blue die under a down-converting phosphor
    # "lines"        -> a set of (center_nm, fwhm_nm, weight) emission lines
    spectrum_kind: str
    spectrum_params: dict[str, Any] = field(default_factory=dict)

    # -- energy balance ---------------------------------------------------
    # Share of the power delivered *to the light source* that leaves as radiation
    # of the modelled spectrum. The remainder is conduction, convection, ballast
    # heat, Stokes loss and non-radiative recombination.
    radiant_efficiency: float = 0.3
    # Transmission of the envelope/optic (glass, diffuser, lens).
    envelope_transmission: float = 0.95
    # Auxiliary loss upstream of the source: LED driver, fluorescent/HID ballast.
    # Fraction of the *system* input power the gear consumes.
    control_gear_loss_frac: float = 0.0
    # How far the supply may sag before that gear stops regulating, as a fraction
    # of nominal. Above it the lamp holds full output and draws *more* current as
    # the voltage falls (constant power); below it the lamp simply goes out, with
    # no dimming on the way down to warn anyone. Unused by filament lamps, which
    # have no gear and follow the supply directly.
    gear_dropout_frac: float = 0.80

    # -- electrical -------------------------------------------------------
    nominal_voltage_v: float = 230.0     # supply the lamp is designed for
    # Solid state: forward-voltage model.
    forward_voltage_v: float = 0.0       # Vf at rated current, 25 C junction
    ideality_factor: float = 2.6         # n in the diode equation (InGaN is high)
    series_resistance_ohm: float = 0.0
    rated_current_a: float = 0.0
    vf_temp_coeff_v_per_k: float = -0.002
    droop_ref_current_a: float = 0.0     # current at which efficiency droop halves output
    # Discharge: the arc sits at a roughly constant voltage; the ballast sets current.
    arc_voltage_v: float = 0.0
    # Thermal radiators: the filament's design temperature at rated volts.
    design_filament_k: float = 0.0
    filament_temp_exponent: float = 1.2  # tungsten: R proportional to T^1.2

    # -- thermal ----------------------------------------------------------
    # The heat path is declared as a *design point* rather than an absolute
    # resistance, because a 100 W floodlight carries a hundred times the heatsink
    # of a 9 W bulb. ``design_temp_rise_k`` is how far the governing node sits
    # above ambient at rated drive; the lamp back-solves its own thermal
    # resistance from that and its rated power, so the model scales across the
    # whole catalog instead of cooking every large luminaire.
    design_temp_rise_k: float = 50.0
    thermal_mass_j_per_k_per_w: float = 2.0   # thermal mass per watt of rated power
    reference_temp_c: float = 25.0       # ambient the published flux is quoted at

    # -- temperature response of light output -----------------------------
    # Solid state: flux falls roughly linearly with junction temperature.
    flux_temp_coeff_per_k: float = 0.0
    # Low-pressure discharge: output peaks at an optimum ambient (mercury vapour
    # pressure) and falls off either side -- a cold fluorescent tube is a dim one.
    optimum_ambient_c: float | None = None
    # The falloff is asymmetric: below the optimum the vapour pressure drops away
    # faster than it climbs above it, so a cold tube loses more light than an
    # equally-overheated one gains back. Two widths, as in the CIE colour lobes.
    ambient_falloff_width_c: float = 23.0          # below the optimum
    ambient_falloff_width_warm_c: float = 30.0     # above it

    # -- dynamics ---------------------------------------------------------
    warmup_s: float = 0.0                # time constant to reach full output
    restrike_s: float = 0.0              # required cool-down before re-ignition
    strike_current_mult: float = 1.0     # inrush while starting, x rated current

    # -- dimming ----------------------------------------------------------
    dimmable: bool = True
    min_dim_frac: float = 0.0

    # -- lifetime ---------------------------------------------------------
    rated_life_h: float = 10000.0
    l70_h: float = 0.0                   # hours to 70% of initial flux (0 = n/a)
    cycle_wear_h: float = 0.0            # equivalent hours consumed per on/off cycle

    # -- published colour figure (not computed; see Spectrum.spectral_coverage) --
    cri: float = 80.0

    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    # -- spectrum ---------------------------------------------------------
    def spectrum(self, temp_k: float | None = None) -> Spectrum:
        """The spectral power distribution this technology radiates.

        Thermal radiators need the *current* filament temperature, so their
        spectrum is rebuilt every time it is asked for -- that is precisely what
        makes a dimmed incandescent lamp go orange and lose efficacy. Every other
        family has a fixed spectrum.
        """
        p = self.spectrum_params
        if self.spectrum_kind == "thermal":
            t = temp_k if temp_k else self.design_filament_k
            return selective_thermal(
                max(300.0, float(t)),
                emissivity_visible=float(p.get("emissivity_visible", 0.44)),
                emissivity_ir=float(p.get("emissivity_ir", 0.28)),
                visible_slope_per_nm=float(p.get("visible_slope_per_nm", 0.0)),
            )
        if self.spectrum_kind == "phosphor_led":
            return phosphor_led(
                pump_nm=float(p.get("pump_nm", 452.0)),
                pump_fwhm_nm=float(p.get("pump_fwhm_nm", 22.0)),
                phosphor_nm=float(p.get("phosphor_nm", 565.0)),
                phosphor_fwhm_nm=float(p.get("phosphor_fwhm_nm", 120.0)),
                conversion_frac=float(p.get("conversion_frac", 0.72)),
                red_nm=p.get("red_nm"),
                red_fwhm_nm=float(p.get("red_fwhm_nm", 90.0)),
                red_frac=float(p.get("red_frac", 0.0)),
            )
        if self.spectrum_kind == "lines":
            lines = [tuple(float(v) for v in line) for line in p.get("lines", [])]
            spd = emission_lines(lines)  # type: ignore[arg-type]
            # Some discharges sit on a pressure-broadened continuum as well.
            cont_k = float(p.get("continuum_k", 0.0))
            cont_w = float(p.get("continuum_weight", 0.0))
            if cont_k > 0 and cont_w > 0:
                spd = spd.normalized() + arc_continuum(cont_k).normalized().scaled(cont_w)
            return spd
        if self.spectrum_kind == "laser":
            return gaussian_band(
                float(p.get("center_nm", 532.0)), float(p.get("fwhm_nm", 2.0))
            )
        raise ValueError(f"unknown spectrum kind '{self.spectrum_kind}'")

    @property
    def is_thermal(self) -> bool:
        return self.family == "incandescent"

    @property
    def is_solid_state(self) -> bool:
        return self.family == "solid_state"

    @property
    def is_discharge(self) -> bool:
        return self.family in ("discharge_lp", "discharge_hp")


# ---------------------------------------------------------------------------
# The technologies.
#
# Spectral recipes are approximations of the real emission: mercury's 405/436/546/
# 578 nm lines, sodium's 589 nm D-doublet, the blue/green/red tri-phosphor bands
# of a modern fluorescent tube. Line widths stand in for pressure broadening,
# which is exactly why the high-pressure lamps render colour and the low-pressure
# ones do not.
# ---------------------------------------------------------------------------

_TRIPHOSPHOR = [(450.0, 22.0, 0.55), (545.0, 32.0, 1.0), (611.0, 26.0, 0.85)]
_MERCURY_LINES = [(405.0, 6.0, 0.14), (436.0, 7.0, 0.42), (546.0, 8.0, 1.0), (578.0, 9.0, 0.82)]

TECHNOLOGIES: dict[str, LightTechnology] = {
    # -- thermal radiators ------------------------------------------------
    "incandescent": LightTechnology(
        key="incandescent",
        name="Incandescent (tungsten filament)",
        family="incandescent",
        spectrum_kind="thermal",
        spectrum_params={"emissivity_visible": 0.44, "emissivity_ir": 0.28},
        radiant_efficiency=0.82,        # rest is conduction through the fill gas + leads
        envelope_transmission=0.94,
        nominal_voltage_v=230.0,
        design_filament_k=2700.0,
        design_temp_rise_k=2400.0,      # the filament itself, glowing white hot
        thermal_mass_j_per_k_per_w=0.002,   # a filament is tiny: it lights up instantly
        warmup_s=0.15,
        dimmable=True,
        min_dim_frac=0.05,
        rated_life_h=1000.0,
        cycle_wear_h=0.5,
        cri=100.0,
        notes="Perfect colour rendering, ~5% of the input as visible light. "
        "Dim it and the filament cools: efficacy collapses and the light goes orange.",
    ),
    "halogen": LightTechnology(
        key="halogen",
        name="Tungsten halogen",
        family="incandescent",
        spectrum_kind="thermal",
        spectrum_params={"emissivity_visible": 0.44, "emissivity_ir": 0.28},
        radiant_efficiency=0.75,   # a small, high-pressure envelope conducts away more
        envelope_transmission=0.93,     # quartz, sometimes with an IR-reflective coat
        nominal_voltage_v=230.0,
        design_filament_k=2950.0,       # the halogen cycle returns evaporated tungsten
        design_temp_rise_k=2700.0,
        thermal_mass_j_per_k_per_w=0.002,
        warmup_s=0.15,
        dimmable=True,
        min_dim_frac=0.05,
        rated_life_h=2000.0,
        cycle_wear_h=0.4,
        cri=100.0,
        notes="A hotter filament than plain incandescent — the halogen cycle "
        "redeposits evaporated tungsten, so it survives 3000 K.",
    ),
    # -- solid state ------------------------------------------------------
    "led": LightTechnology(
        key="led",
        name="White LED (phosphor-converted)",
        family="solid_state",
        spectrum_kind="phosphor_led",
        spectrum_params={
            "pump_nm": 452.0,
            "pump_fwhm_nm": 22.0,
            "phosphor_nm": 565.0,
            "phosphor_fwhm_nm": 120.0,
            "conversion_frac": 0.80,
            "red_frac": 0.12,
            "red_nm": 630.0,
        },
        radiant_efficiency=0.42,        # wall-plug efficiency of a good mid-power die
        envelope_transmission=0.92,
        control_gear_loss_frac=0.10,    # the driver
        nominal_voltage_v=230.0,
        forward_voltage_v=2.9,
        ideality_factor=2.6,
        series_resistance_ohm=0.35,
        rated_current_a=0.35,
        droop_ref_current_a=1.6,
        design_temp_rise_k=55.0,        # a well-heatsunk junction at 80 C in a 25 C room
        thermal_mass_j_per_k_per_w=2.5,
        flux_temp_coeff_per_k=-0.0022,  # ~ -0.22%/K of junction temperature
        warmup_s=0.05,
        dimmable=True,
        min_dim_frac=0.01,
        rated_life_h=50000.0,
        l70_h=50000.0,
        cri=82.0,
        notes="Efficacy falls as the junction heats — the whole design problem is "
        "getting heat out of a device that puts none of it into the beam.",
    ),
    "led_high_cri": LightTechnology(
        key="led_high_cri",
        name="High-CRI warm white LED",
        family="solid_state",
        spectrum_kind="phosphor_led",
        spectrum_params={
            "pump_nm": 450.0,
            "pump_fwhm_nm": 24.0,
            "phosphor_nm": 570.0,
            "phosphor_fwhm_nm": 130.0,
            "conversion_frac": 0.88,
            "red_frac": 0.34,           # a red phosphor buys colour and costs efficacy
            "red_nm": 635.0,
        },
        radiant_efficiency=0.34,
        envelope_transmission=0.90,
        control_gear_loss_frac=0.10,
        nominal_voltage_v=230.0,
        forward_voltage_v=2.85,
        ideality_factor=2.6,
        series_resistance_ohm=0.4,
        rated_current_a=0.35,
        droop_ref_current_a=1.5,
        design_temp_rise_k=58.0,
        thermal_mass_j_per_k_per_w=2.5,
        flux_temp_coeff_per_k=-0.0024,
        warmup_s=0.05,
        dimmable=True,
        min_dim_frac=0.01,
        rated_life_h=50000.0,
        l70_h=45000.0,
        cri=95.0,
        notes="The red phosphor that fills in the deep red costs about a fifth of "
        "the efficacy — the standard colour-versus-efficiency trade.",
    ),
    "laser_diode": LightTechnology(
        key="laser_diode",
        name="Green laser diode (532 nm)",
        family="solid_state",
        spectrum_kind="laser",
        spectrum_params={"center_nm": 532.0, "fwhm_nm": 2.0},
        radiant_efficiency=0.21,
        envelope_transmission=0.97,
        control_gear_loss_frac=0.08,
        nominal_voltage_v=12.0,
        forward_voltage_v=4.6,
        ideality_factor=2.0,
        series_resistance_ohm=1.2,
        rated_current_a=0.28,
        droop_ref_current_a=6.0,
        design_temp_rise_k=35.0,        # laser dies are held cool on purpose
        thermal_mass_j_per_k_per_w=3.0,
        flux_temp_coeff_per_k=-0.004,   # laser output is far more temperature-sensitive
        warmup_s=0.02,
        dimmable=True,
        min_dim_frac=0.2,               # below threshold it stops lasing entirely
        rated_life_h=10000.0,
        cri=0.0,
        notes="One narrow line near the eye's peak sensitivity — enormous efficacy "
        "of radiation, no colour rendering at all. Below threshold current it "
        "simply stops lasing.",
    ),
    # -- low-pressure discharge -------------------------------------------
    "fluorescent_t8": LightTechnology(
        key="fluorescent_t8",
        name="Linear fluorescent T8 (tri-phosphor)",
        family="discharge_lp",
        spectrum_kind="lines",
        spectrum_params={"lines": _TRIPHOSPHOR + [(436.0, 6.0, 0.10), (546.0, 6.0, 0.16)],
                         "phosphor_blend": True},
        radiant_efficiency=0.23,        # ~60% of input to 254 nm UV, ~40% of that returned
        envelope_transmission=0.95,
        control_gear_loss_frac=0.08,    # electronic ballast
        nominal_voltage_v=230.0,
        arc_voltage_v=100.0,
        design_temp_rise_k=20.0,
        thermal_mass_j_per_k_per_w=2.5,
        optimum_ambient_c=25.0,         # the mercury vapour-pressure optimum
        ambient_falloff_width_c=23.0,
        ambient_falloff_width_warm_c=30.0,
        warmup_s=90.0,
        strike_current_mult=1.6,
        dimmable=True,
        min_dim_frac=0.1,
        rated_life_h=20000.0,
        l70_h=16000.0,
        cycle_wear_h=1.5,               # switching wears the cathodes
        cri=85.0,
        notes="Output peaks near 25 °C ambient and falls off either side: ambient "
        "temperature sets the mercury vapour pressure inside the tube.",
    ),
    "cfl": LightTechnology(
        key="cfl",
        name="Compact fluorescent (CFL)",
        family="discharge_lp",
        spectrum_kind="lines",
        spectrum_params={"lines": _TRIPHOSPHOR + [(436.0, 6.0, 0.12), (546.0, 6.0, 0.18)],
                         "phosphor_blend": True},
        radiant_efficiency=0.17,
        envelope_transmission=0.92,
        control_gear_loss_frac=0.12,
        nominal_voltage_v=230.0,
        arc_voltage_v=90.0,
        design_temp_rise_k=35.0,
        thermal_mass_j_per_k_per_w=3.0,
        optimum_ambient_c=22.0,
        ambient_falloff_width_c=21.0,
        ambient_falloff_width_warm_c=27.0,
        warmup_s=120.0,                 # the amalgam has to warm through
        strike_current_mult=1.8,
        dimmable=False,
        min_dim_frac=1.0,
        rated_life_h=8000.0,
        l70_h=6000.0,
        cycle_wear_h=3.0,
        cri=82.0,
        notes="A folded fluorescent tube with the ballast in the base. Slow to "
        "reach full output, and short switching cycles wear it out fast.",
    ),
    "induction": LightTechnology(
        key="induction",
        name="Induction (electrodeless fluorescent)",
        family="discharge_lp",
        spectrum_kind="lines",
        spectrum_params={"lines": _TRIPHOSPHOR + [(436.0, 6.0, 0.10)],
                         "phosphor_blend": True},
        radiant_efficiency=0.20,
        envelope_transmission=0.94,
        control_gear_loss_frac=0.10,
        nominal_voltage_v=230.0,
        arc_voltage_v=110.0,
        design_temp_rise_k=25.0,
        thermal_mass_j_per_k_per_w=1.5,
        optimum_ambient_c=25.0,
        ambient_falloff_width_c=26.0,
        ambient_falloff_width_warm_c=34.0,
        warmup_s=45.0,
        dimmable=True,
        min_dim_frac=0.25,
        rated_life_h=100000.0,
        l70_h=60000.0,
        cycle_wear_h=0.0,               # no electrodes to wear out
        cri=82.0,
        notes="No electrodes — the discharge is driven by an external RF coil, so "
        "the usual life-limiting failure simply isn't there.",
    ),
    "low_pressure_sodium": LightTechnology(
        key="low_pressure_sodium",
        name="Low-pressure sodium (SOX)",
        family="discharge_lp",
        spectrum_kind="lines",
        spectrum_params={"lines": [(589.0, 1.2, 1.0), (589.6, 1.2, 0.9)]},
        radiant_efficiency=0.34,
        envelope_transmission=0.93,
        control_gear_loss_frac=0.12,
        nominal_voltage_v=230.0,
        arc_voltage_v=110.0,
        design_temp_rise_k=45.0,
        thermal_mass_j_per_k_per_w=1.2,
        optimum_ambient_c=25.0,
        ambient_falloff_width_c=38.0,
        ambient_falloff_width_warm_c=48.0,
        warmup_s=480.0,
        restrike_s=60.0,
        dimmable=False,
        min_dim_frac=1.0,
        rated_life_h=18000.0,
        cri=0.0,
        notes="The most efficacious lamp ever built and the worst at colour: all "
        "its light is the sodium D-doublet, 3 nm from the eye's peak sensitivity. "
        "Everything under it is monochrome yellow.",
    ),
    "neon": LightTechnology(
        key="neon",
        name="Neon (cold-cathode sign tube)",
        family="discharge_lp",
        spectrum_kind="lines",
        spectrum_params={
            "lines": [(585.2, 2.0, 0.55), (614.3, 2.0, 0.75), (640.2, 2.0, 1.0),
                      (650.7, 2.0, 0.7), (703.2, 2.5, 0.35)]
        },
        radiant_efficiency=0.062,
        envelope_transmission=0.92,
        control_gear_loss_frac=0.15,
        nominal_voltage_v=230.0,
        arc_voltage_v=1200.0,           # cold cathodes need kilovolts to strike
        design_temp_rise_k=30.0,
        thermal_mass_j_per_k_per_w=2.0,
        optimum_ambient_c=25.0,
        ambient_falloff_width_c=42.0,
        ambient_falloff_width_warm_c=52.0,
        warmup_s=8.0,
        dimmable=False,
        min_dim_frac=1.0,
        rated_life_h=30000.0,
        cri=0.0,
        notes="Signage rather than illumination — a red-orange line spectrum at a "
        "few lumens per watt, driven from a kilovolt transformer.",
    ),
    # -- high-pressure discharge ------------------------------------------
    "metal_halide": LightTechnology(
        key="metal_halide",
        name="Metal halide",
        family="discharge_hp",
        spectrum_kind="lines",
        spectrum_params={
            "lines": [(405.0, 6.0, 0.08), (436.0, 7.0, 0.28), (546.0, 8.0, 0.5),
                      (578.0, 9.0, 0.5), (535.0, 40.0, 0.7), (590.0, 45.0, 0.9),
                      (620.0, 35.0, 0.7), (480.0, 30.0, 0.45), (660.0, 40.0, 0.3)],
            "continuum_k": 4400.0,
            "continuum_weight": 1.4,
        },
        radiant_efficiency=0.34,
        envelope_transmission=0.92,
        control_gear_loss_frac=0.12,
        nominal_voltage_v=230.0,
        arc_voltage_v=95.0,
        design_temp_rise_k=250.0,
        thermal_mass_j_per_k_per_w=1.0,
        warmup_s=240.0,
        restrike_s=600.0,               # a hot arc tube will not restrike
        strike_current_mult=1.7,
        dimmable=False,
        min_dim_frac=1.0,
        rated_life_h=15000.0,
        l70_h=9000.0,
        cycle_wear_h=4.0,
        cri=70.0,
        notes="Metal-halide salts added to a mercury arc fill in the gaps between "
        "the mercury lines — good white light, but a ten-minute restrike after any "
        "power blink.",
    ),
    "high_pressure_sodium": LightTechnology(
        key="high_pressure_sodium",
        name="High-pressure sodium (SON)",
        family="discharge_hp",
        spectrum_kind="lines",
        spectrum_params={
            "lines": [(589.0, 26.0, 1.0), (568.0, 10.0, 0.22), (616.0, 12.0, 0.28),
                      (498.0, 14.0, 0.10), (819.0, 20.0, 0.18)],
            "continuum_k": 2400.0,
            "continuum_weight": 0.30,
        },
        radiant_efficiency=0.35,
        envelope_transmission=0.93,
        control_gear_loss_frac=0.11,
        nominal_voltage_v=230.0,
        arc_voltage_v=100.0,
        design_temp_rise_k=230.0,
        thermal_mass_j_per_k_per_w=1.0,
        warmup_s=300.0,
        restrike_s=90.0,
        strike_current_mult=1.5,
        dimmable=False,
        min_dim_frac=1.0,
        rated_life_h=24000.0,
        l70_h=20000.0,
        cycle_wear_h=3.0,
        cri=25.0,
        notes="Raising the sodium pressure broadens the D-line into a band — much "
        "better colour than low-pressure sodium, a little less efficacy. The orange "
        "glow of twentieth-century street lighting.",
    ),
    "mercury_vapor": LightTechnology(
        key="mercury_vapor",
        name="Mercury vapour",
        family="discharge_hp",
        spectrum_kind="lines",
        spectrum_params={
            "lines": _MERCURY_LINES + [(610.0, 45.0, 0.30)],
            "continuum_k": 4000.0,
            "continuum_weight": 0.55,
        },
        radiant_efficiency=0.175,
        envelope_transmission=0.90,
        control_gear_loss_frac=0.13,
        nominal_voltage_v=230.0,
        arc_voltage_v=130.0,
        design_temp_rise_k=220.0,
        thermal_mass_j_per_k_per_w=1.0,
        warmup_s=300.0,
        restrike_s=300.0,
        strike_current_mult=1.6,
        dimmable=False,
        min_dim_frac=1.0,
        rated_life_h=24000.0,
        l70_h=12000.0,
        cycle_wear_h=3.0,
        cri=45.0,
        notes="The oldest high-intensity discharge lamp. A blue-green cast, no red "
        "to speak of, and largely legislated out of service.",
    ),
    "xenon_arc": LightTechnology(
        key="xenon_arc",
        name="Xenon short-arc",
        family="discharge_hp",
        spectrum_kind="lines",
        spectrum_params={
            "lines": [(467.0, 8.0, 0.18), (823.0, 10.0, 0.25), (881.0, 10.0, 0.2)],
            "continuum_k": 6200.0,
            "continuum_weight": 1.0,
        },
        radiant_efficiency=0.39,
        envelope_transmission=0.94,
        control_gear_loss_frac=0.15,
        nominal_voltage_v=230.0,
        arc_voltage_v=20.0,             # a short arc: low volts, huge current
        design_temp_rise_k=600.0,
        thermal_mass_j_per_k_per_w=0.6,
        warmup_s=30.0,
        restrike_s=10.0,
        strike_current_mult=1.3,
        dimmable=True,
        min_dim_frac=0.5,
        rated_life_h=2000.0,
        cri=95.0,
        notes="A near-daylight continuum from a millimetre-long arc — projection, "
        "solar simulation, searchlights. Brilliant colour, poor efficacy, and a "
        "bulb under enough pressure to be handled behind a shield.",
    ),
}


def technology_for(key: str) -> LightTechnology:
    """Look up a :class:`LightTechnology` by key (case-insensitive)."""
    k = str(key).lower()
    if k not in TECHNOLOGIES:
        raise ValueError(
            f"unknown light technology '{key}' (use one of {', '.join(sorted(TECHNOLOGIES))})"
        )
    return TECHNOLOGIES[k]


def list_technologies() -> list[LightTechnology]:
    """Every modelled light-source technology."""
    return list(TECHNOLOGIES.values())


# ---------------------------------------------------------------------------
# Real lamps.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LampType:
    """One selectable, off-the-shelf lamp.

    ``rated_flux_lm`` is the **published** figure a manufacturer prints on the box.
    The model does not use it to produce light -- it computes flux from the
    physics -- so the two can be compared, which is exactly what
    :mod:`simura.lights.validation` does.
    """

    id: str
    name: str
    technology: str          # key into TECHNOLOGIES
    rated_power_w: float     # system power, including control gear
    rated_flux_lm: float     # published luminous flux at reference conditions
    beam_angle_deg: float    # full cone angle; 360 = bare omnidirectional lamp
    color_temp_k: float      # published nominal CCT
    base: str = "E27"
    # A filament lamp's colour temperature *is* its design point: a 100 W lamp
    # runs a hotter filament than a 60 W one, which is exactly why it is the more
    # efficacious of the two. Left at None, the technology's default applies.
    design_filament_k: float | None = None
    # Solid state: how hard each die is driven, as a fraction of its rated
    # current. High-efficacy luminaires use *more* dies driven *softer* — less
    # efficiency droop and a cooler junction — which is why a big floodlight beats
    # a retrofit bulb on lumens per watt using the same LEDs.
    die_drive_frac: float = 1.0
    notes: str = ""

    @property
    def published_efficacy_lm_per_w(self) -> float:
        return self.rated_flux_lm / self.rated_power_w if self.rated_power_w > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["published_efficacy_lm_per_w"] = round(self.published_efficacy_lm_per_w, 2)
        d["family"] = TECHNOLOGIES[self.technology].family
        return d


# Published fluxes are the long-established catalogue figures for each lamp
# (General Electric / Osram / Philips general-service data). They are *inputs to
# the comparison*, never to the physics.
LAMP_CATALOG: list[LampType] = [
    # -- Incandescent / halogen -------------------------------------------
    LampType(
        id="inc-60-e27", name="60 W incandescent GLS", technology="incandescent",
        rated_power_w=60.0, rated_flux_lm=840.0, beam_angle_deg=360.0,
        color_temp_k=2700.0, base="E27", design_filament_k=2700.0,
        notes="The lamp everything else is compared against.",
    ),
    LampType(
        id="inc-100-e27", name="100 W incandescent GLS", technology="incandescent",
        rated_power_w=100.0, rated_flux_lm=1600.0, beam_angle_deg=360.0,
        color_temp_k=2800.0, base="E27", design_filament_k=2800.0,
        notes="A hotter filament than the 60 W: more efficacious, shorter life. "
        "The model gets that difference from the filament temperature alone.",
    ),
    LampType(
        id="hal-50-gu10", name="50 W halogen spot GU10", technology="halogen",
        rated_power_w=50.0, rated_flux_lm=900.0, beam_angle_deg=36.0,
        color_temp_k=2900.0, base="GU10", design_filament_k=2900.0,
        notes="Retail and display spotlighting.",
    ),
    LampType(
        id="hal-300-r7s", name="300 W halogen linear", technology="halogen",
        rated_power_w=300.0, rated_flux_lm=5600.0, beam_angle_deg=360.0,
        color_temp_k=3000.0, base="R7s", design_filament_k=3000.0,
        notes="Worksite floodlight — the hottest filament in common use.",
    ),
    # -- Solid state -------------------------------------------------------
    LampType(
        id="led-9-e27", name="9 W LED GLS (60 W equivalent)", technology="led",
        rated_power_w=9.0, rated_flux_lm=806.0, beam_angle_deg=300.0,
        color_temp_k=2700.0, base="E27",
        notes="The standard incandescent replacement: same light, a seventh of the power.",
    ),
    LampType(
        id="led-15-e27", name="15 W LED GLS", technology="led",
        rated_power_w=15.0, rated_flux_lm=1521.0, beam_angle_deg=300.0,
        color_temp_k=4000.0, base="E27",
        notes="100 W equivalent, neutral white.",
    ),
    LampType(
        id="led-100-flood", name="100 W LED floodlight", technology="led",
        rated_power_w=100.0, rated_flux_lm=12000.0, beam_angle_deg=120.0,
        color_temp_k=5000.0, base="hardwired", die_drive_frac=0.5,
        notes="Area and yard lighting — a big heatsink is the whole design.",
    ),
    LampType(
        id="led-12-cri95", name="12 W high-CRI LED", technology="led_high_cri",
        rated_power_w=12.0, rated_flux_lm=900.0, beam_angle_deg=300.0,
        color_temp_k=2700.0, base="E27",
        notes="Galleries, retail, anywhere colour has to be right.",
    ),
    LampType(
        id="laser-1-532", name="1 W green laser module", technology="laser_diode",
        rated_power_w=1.3, rated_flux_lm=150.0, beam_angle_deg=0.5,
        color_temp_k=0.0, base="module",
        notes="A collimated beam, not an illuminant — but the same physics, and "
        "the highest efficacy of radiation of anything here.",
    ),
    # -- Low-pressure discharge -------------------------------------------
    LampType(
        id="fl-t8-36", name="36 W T8 fluorescent tube", technology="fluorescent_t8",
        rated_power_w=39.0, rated_flux_lm=3350.0, beam_angle_deg=360.0,
        color_temp_k=4000.0, base="G13",
        notes="The 1.2 m office and workshop tube.",
    ),
    LampType(
        id="fl-t8-58", name="58 W T8 fluorescent tube", technology="fluorescent_t8",
        rated_power_w=62.0, rated_flux_lm=5200.0, beam_angle_deg=360.0,
        color_temp_k=4000.0, base="G13",
        notes="The 1.5 m tube.",
    ),
    LampType(
        id="cfl-15-e27", name="15 W compact fluorescent", technology="cfl",
        rated_power_w=15.0, rated_flux_lm=900.0, beam_angle_deg=320.0,
        color_temp_k=2700.0, base="E27",
        notes="The first mass-market incandescent replacement.",
    ),
    LampType(
        id="ind-80-round", name="80 W induction lamp", technology="induction",
        rated_power_w=88.0, rated_flux_lm=6400.0, beam_angle_deg=360.0,
        color_temp_k=4000.0, base="hardwired",
        notes="Tunnels and high bays — no electrodes, so it lasts effectively forever.",
    ),
    LampType(
        id="lps-135-bx", name="135 W low-pressure sodium", technology="low_pressure_sodium",
        rated_power_w=155.0, rated_flux_lm=22500.0, beam_angle_deg=360.0,
        color_temp_k=1700.0, base="BY22d",
        notes="Peak efficacy, zero colour rendering.",
    ),
    LampType(
        id="neon-30-tube", name="30 W neon sign tube", technology="neon",
        rated_power_w=35.0, rated_flux_lm=350.0, beam_angle_deg=360.0,
        color_temp_k=0.0, base="electrode",
        notes="Signage — a red-orange line spectrum at a few lumens per watt.",
    ),
    # -- High-pressure discharge ------------------------------------------
    LampType(
        id="mh-250-e40", name="250 W metal halide", technology="metal_halide",
        rated_power_w=275.0, rated_flux_lm=20000.0, beam_angle_deg=360.0,
        color_temp_k=4200.0, base="E40",
        notes="Sports fields, high bays, floodlighting.",
    ),
    LampType(
        id="hps-150-e40", name="150 W high-pressure sodium",
        technology="high_pressure_sodium", rated_power_w=168.0, rated_flux_lm=17000.0,
        beam_angle_deg=360.0, color_temp_k=2000.0, base="E40",
        notes="The classic orange street light.",
    ),
    LampType(
        id="hps-400-e40", name="400 W high-pressure sodium",
        technology="high_pressure_sodium", rated_power_w=435.0, rated_flux_lm=48000.0,
        beam_angle_deg=360.0, color_temp_k=2000.0, base="E40",
        notes="Major roads and rail yards.",
    ),
    LampType(
        id="mv-250-e40", name="250 W mercury vapour", technology="mercury_vapor",
        rated_power_w=275.0, rated_flux_lm=13000.0, beam_angle_deg=360.0,
        color_temp_k=4000.0, base="E40",
        notes="Legacy street and industrial lighting.",
    ),
    LampType(
        id="xe-1000-arc", name="1000 W xenon short-arc", technology="xenon_arc",
        rated_power_w=1000.0, rated_flux_lm=30000.0, beam_angle_deg=360.0,
        color_temp_k=6200.0, base="special",
        notes="Cinema projection and solar simulation.",
    ),
]

_BY_ID = {lamp.id: lamp for lamp in LAMP_CATALOG}


def lamp_type_for(id: str) -> LampType:
    """Look up a catalog :class:`LampType` by id."""
    if id not in _BY_ID:
        raise ValueError(f"unknown lamp type '{id}' (see list_lamp_types())")
    return _BY_ID[id]


def list_lamp_types(technology: str | None = None, family: str | None = None) -> list[LampType]:
    """The catalog, optionally filtered to one technology or one family."""
    out = list(LAMP_CATALOG)
    if technology is not None:
        out = [lamp for lamp in out if lamp.technology == technology]
    if family is not None:
        out = [lamp for lamp in out if TECHNOLOGIES[lamp.technology].family == family]
    return out
