"""The light model: a config description and its electro-thermal-photometric state.

Split exactly like the battery and wire sides (:class:`simura.wires.WireSpec` /
:class:`simura.wires.Wire`): :class:`LightSpec` is a plain, serializable
description of *what the lamp is*; :class:`Light` holds the live state -- node
temperature, warm-up progress, accumulated operating hours -- and does the
physics.

Three families, three electrical laws, one photometric chain
------------------------------------------------------------

Whatever the technology, light is produced the same way once the source power is
known::

    Phi_v = LER(spectrum) * P_source * radiant_efficiency * transmission * derating

The families differ in how ``P_source`` and the spectrum come about.

**Thermal radiators (incandescent, halogen).** Everything is solved from the
filament's energy balance::

    P_electrical(T) = V^2 / R(T),      R(T) = R_293 * (T/293)^1.2
    P_out(T)        = A * M(T) + G_cond * (T - T_ambient)

``T`` is whatever temperature balances the two. The filament geometry (``R_293``,
``A``, ``G_cond``) is back-solved once from the catalog's rated power and design
temperature, so the lamp reproduces its own datasheet at the design point and then
*predicts* everything off it. Dim it to half voltage and the filament falls to
~2200 K: the Planck curve retreats into the infrared, the efficacy of radiation
collapses, and the light turns orange. None of that is coded -- it falls out.

**Solid state (LED, laser diode).** The junction obeys a diode law, with a forward
voltage that drops as it heats::

    V_f(I, T_j) = V_f,rated + n*V_T*ln(I/I_rated) + (I - I_rated)*R_s + k_V*(T_j - 25)

Flux is proportional to current, less *efficiency droop* at high current density,
less the junction's thermal derating (about -0.22%/K). The junction sits at
``T_j = T_ambient + P_heat * R_th``, and since none of the heat leaves in the beam,
the whole engineering problem is that thermal path.

**Discharge (fluorescent, CFL, induction, sodium, metal halide, mercury, xenon,
neon).** The arc holds a roughly fixed voltage and the ballast sets the current, so
source power is nearly constant. What varies is *availability*: a discharge lamp
takes minutes to warm up, and a hot high-pressure lamp will not restrike until it
has cooled. Low-pressure lamps add a strong ambient-temperature dependence,
because ambient sets the mercury vapour pressure -- a fluorescent tube in a cold
garage is a dim tube.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields, replace
from functools import lru_cache
from typing import Any, Optional

from .catalog import LampType, LightTechnology, lamp_type_for, technology_for
from .spectrum import K_BOLTZMANN, Spectrum, thermal_radiator

# Elementary charge, for the diode thermal voltage kT/q.
_Q_ELECTRON = 1.602176634e-19

# Reference temperature for the filament's cold resistance (20 C in kelvin).
_T_COLD_K = 293.15


@dataclass
class LightSpec:
    """A serializable description of a light source.

    Give it a catalog ``lamp_type`` (which fills technology, power, beam and
    published flux) or name a ``technology`` and a ``power_w`` directly. Anything
    left as ``None`` is taken from the catalog or the technology's defaults.
    """

    technology: str = "led"
    lamp_type: str | None = None
    power_w: float | None = None            # rated system power, including gear
    supply_voltage_v: float | None = None
    beam_angle_deg: float | None = None     # full cone; 360 = omnidirectional
    ambient_temp_c: float = 25.0

    # Optional physical overrides (None -> the technology's value).
    thermal_resistance_k_per_w: float | None = None
    thermal_mass_j_per_k: float | None = None
    envelope_transmission: float | None = None
    radiant_efficiency: float | None = None
    control_gear_loss_frac: float | None = None
    design_filament_k: float | None = None

    # Where the lamp starts life: accumulated operating hours and switch cycles,
    # so an aged luminaire can be modelled without simulating years of it.
    operating_hours_h: float = 0.0
    switch_cycles: float = 0.0

    # Maintenance state: dirt on the lens/luminaire, 0 = clean, 1 = fully obscured.
    # The lighting industry calls the survivor of this the light loss factor.
    dirt_depreciation_frac: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LightSpec":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass(frozen=True)
class OperatingPoint:
    """What the lamp is doing right now, at one drive level and one temperature."""

    input_power_w: float          # system power drawn from the supply
    source_power_w: float         # power reaching the light source itself
    current_a: float
    voltage_v: float
    radiant_power_w: float        # optical watts leaving the source
    luminous_flux_lm: float       # what the eye sees
    efficacy_lm_per_w: float      # flux / system input power
    ler_lm_per_w: float           # flux / radiant watt -- the spectrum's own ceiling
    color_temp_k: float
    source_temp_c: float          # filament / junction / wall temperature
    visible_fraction: float       # share of radiant power inside 380-780 nm
    lumen_maintenance: float      # 0..1, flux remaining vs a new lamp
    warmup_frac: float            # 0..1, how far through warm-up
    lit: bool                     # is it actually producing light?

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SupplyPoint:
    """What a lamp does on a supply that is not at its rated voltage.

    ``supply_current_a`` is what the *supply* delivers, which for anything with
    control gear is emphatically not ``point.current_a`` (that is the current
    inside the lamp, after the driver). Keeping both is the point of this type:
    the electrical network needs the first and the photometry needs the second.
    """

    supply_voltage_v: float
    nominal_voltage_v: float
    voltage_ratio: float          # supply / nominal
    supply_current_a: float       # drawn from the supply at this voltage
    regulated: bool               # is there a driver or ballast in front of it?
    dropped_out: bool             # gear below its minimum input voltage
    over_voltage: bool
    point: OperatingPoint

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["point"] = self.point.to_dict()
        return d


class Light:
    """Live electro-thermal-photometric state of one light source."""

    def __init__(self, spec: LightSpec) -> None:
        self.spec = spec

        # Resolve the catalog lamp first; explicit spec fields then win over it.
        lamp: Optional[LampType] = None
        technology_key = spec.technology
        if spec.lamp_type is not None:
            lamp = lamp_type_for(spec.lamp_type)
            technology_key = lamp.technology
        self.lamp_type = lamp
        self.tech: LightTechnology = technology_for(technology_key)

        self.rated_power_w = float(
            spec.power_w
            if spec.power_w is not None
            else (lamp.rated_power_w if lamp else 10.0)
        )
        if self.rated_power_w <= 0:
            raise ValueError("a light needs a positive rated power")
        self.supply_voltage_v = float(
            spec.supply_voltage_v
            if spec.supply_voltage_v is not None
            else self.tech.nominal_voltage_v
        )
        self.beam_angle_deg = float(
            spec.beam_angle_deg
            if spec.beam_angle_deg is not None
            else (lamp.beam_angle_deg if lamp else 360.0)
        )
        self.published_flux_lm = float(lamp.rated_flux_lm) if lamp else 0.0

        # Physical parameters, technology defaults unless overridden.
        self.radiant_efficiency = _pick(spec.radiant_efficiency, self.tech.radiant_efficiency)
        self.envelope_transmission = _pick(
            spec.envelope_transmission, self.tech.envelope_transmission
        )
        self.gear_loss_frac = min(
            0.6, max(0.0, _pick(spec.control_gear_loss_frac, self.tech.control_gear_loss_frac))
        )
        # Power that actually reaches the light source, at rated drive.
        self.rated_source_power_w = self.rated_power_w * (1.0 - self.gear_loss_frac)

        # The heat path is back-solved from the technology's design temperature
        # rise and *this* lamp's heat load, so a 100 W floodlight gets a 100 W
        # luminaire's heatsink rather than a 9 W bulb's. Without this the model
        # cooks every large lamp and under-predicts its output badly.
        rated_heat_w = max(self.rated_source_power_w * (1.0 - self.radiant_efficiency), 1e-6)
        self.r_th = max(
            1e-9,
            _pick(
                spec.thermal_resistance_k_per_w,
                self.tech.design_temp_rise_k / rated_heat_w,
            ),
        )
        self.c_th = max(
            1e-6,
            _pick(
                spec.thermal_mass_j_per_k,
                self.tech.thermal_mass_j_per_k_per_w * self.rated_power_w,
            ),
        )

        # Live state.
        self.ambient_c = float(spec.ambient_temp_c)
        self.temp_c = self.ambient_c            # filament / junction / wall node
        self.operating_hours_h = float(spec.operating_hours_h)
        self.switch_cycles = float(spec.switch_cycles)
        self.dirt_frac = min(0.95, max(0.0, float(spec.dirt_depreciation_frac)))
        self.lit = False
        self.time_lit_s = 0.0                   # since the last strike, for warm-up
        self.time_dark_s = 1e9                  # since it went out, for restrike
        self._spectrum_cache: Spectrum | None = None
        # Spectral recipe: the technology's, unless this lamp tunes it (an LED's
        # phosphor loading is set by the colour temperature it is sold as).
        self._spectrum_params: dict[str, Any] = dict(self.tech.spectrum_params)

        # Family-specific calibration.
        if self.tech.is_thermal:
            self._calibrate_filament()
        elif self.tech.is_solid_state:
            self._calibrate_junction()
            self._tune_phosphor()
        else:
            self._calibrate_arc()
            self._tune_phosphor()

    # -- calibration -------------------------------------------------------
    def _calibrate_filament(self) -> None:
        """Back-solve the filament from the rated power and design temperature.

        Two unknowns, two equations at the design point: the cold resistance that
        makes the lamp draw its rated power at rated volts, and the radiating area
        that dissipates the radiant share of that power at the design temperature.
        The conduction conductance takes the rest. Everything off-design then
        follows from physics rather than from a table.
        """
        lamp_design = self.lamp_type.design_filament_k if self.lamp_type else None
        t_design = float(
            _pick(self.spec.design_filament_k, lamp_design or self.tech.design_filament_k)
            or 2700.0
        )
        self.design_filament_k = t_design
        p = self.rated_source_power_w
        v = self.supply_voltage_v

        # R(T_design) = V^2 / P  ->  R_293 from the tungsten power law.
        r_hot = v * v / p
        self.r_cold_ohm = r_hot / (t_design / _T_COLD_K) ** self.tech.filament_temp_exponent

        # Radiating area from the design-point radiant balance.
        exitance, _, _, _ = self._thermal_metrics(t_design)
        self.filament_area_m2 = (p * self.radiant_efficiency) / max(exitance, 1e-9)

        # Whatever is not radiated leaves by conduction through the fill gas/leads.
        t_amb_ref_k = self.tech.reference_temp_c + 273.15
        self.g_cond_w_per_k = (p * (1.0 - self.radiant_efficiency)) / max(
            t_design - t_amb_ref_k, 1.0
        )
        self.temp_c = self.ambient_c

    def _calibrate_junction(self) -> None:
        """Scale the single-die diode model up to the module's rated power."""
        self.vf_rated_v = self.tech.forward_voltage_v
        self.i_rated_a = max(self.tech.rated_current_a, 1e-6)
        # How hard each die is driven. A luminaire that spreads its watts over more
        # dies runs each one softer, which buys back efficiency droop and lowers
        # the junction temperature -- the standard way to build a high-efficacy
        # fitting out of ordinary LEDs.
        self.die_drive_frac = max(
            0.05, float(self.lamp_type.die_drive_frac if self.lamp_type else 1.0)
        )
        self.die_current_a = self.i_rated_a * self.die_drive_frac
        # How many dies' worth of power the module represents. Keeps the per-die
        # physics (forward voltage, droop) while sizing to the real lamp.
        die_power = self.forward_voltage_v(self.die_current_a, 25.0) * self.die_current_a
        self.n_emitters = max(1.0, self.rated_source_power_w / max(die_power, 1e-9))

    def _tune_phosphor(self) -> None:
        """Set the phosphor blend so the lamp actually *is* the colour it claims.

        A 2700 K and a 4000 K lamp of the same technology are the same emitter
        under a different phosphor: more down-conversion and more red for the warm
        one. Rather than carry a separate technology per colour temperature, tune a
        single "warmth" knob until the modelled spectrum lands on the lamp's
        published CCT.

        The efficacy consequence then follows for free, and in the right direction.
        Warm white converts more of its pump, pays more Stokes loss and puts more
        of its light into deep red where the eye is insensitive -- so it comes out
        less efficacious than the cool-white version of itself, which is exactly
        what the datasheets say. Nothing states that rule; it emerges from the
        spectrum.
        """
        self._spectrum_cache = None
        target = self.lamp_type.color_temp_k if self.lamp_type else 0.0
        if target <= 0 or self._warmth_knob(0.0) is None:
            return

        # Warmth is monotone decreasing in CCT: turn it up and the light reddens.
        lo, hi = 0.0, 1.0
        cct_lo, cct_hi = self._cct_at_warmth(lo), self._cct_at_warmth(hi)
        if not (cct_hi <= target <= cct_lo):
            return              # this phosphor cannot reach the published colour
        for _ in range(28):
            mid = 0.5 * (lo + hi)
            if self._cct_at_warmth(mid) > target:
                lo = mid
            else:
                hi = mid
        self._spectrum_params = self._warmth_knob(0.5 * (lo + hi)) or self._spectrum_params

    def _warmth_knob(self, warmth: float) -> dict[str, Any] | None:
        """Spectral parameters at a warmth of 0 (coolest) to 1 (warmest).

        ``None`` if this technology's colour is not adjustable -- a sodium lamp is
        the colour sodium is, and a laser is its own wavelength.
        """
        p = dict(self.tech.spectrum_params)
        if self.tech.spectrum_kind == "phosphor_led":
            conv, red, phosphor = _led_blend_path(
                float(p.get("pump_nm", 452.0)),
                float(p.get("pump_fwhm_nm", 22.0)),
                float(p.get("phosphor_fwhm_nm", 120.0)),
                float(p.get("red_fwhm_nm", 90.0)),
                float(p.get("red_nm") or 630.0),
                round(warmth, 4),
            )
            p["conversion_frac"] = conv
            p["red_frac"] = red
            p["phosphor_nm"] = phosphor
            return p
        if self.tech.spectrum_kind == "lines" and p.get("phosphor_blend"):
            # A fluorescent tri-phosphor: shift the blend from blue towards red.
            lines = []
            for center, fwhm, weight in p.get("lines", []):
                if center < 500.0:
                    weight *= 1.0 - 0.75 * warmth
                elif center > 580.0:
                    weight *= 1.0 + 2.2 * warmth
                lines.append((center, fwhm, weight))
            p["lines"] = lines
            return p
        return None

    def _cct_at_warmth(self, warmth: float) -> float:
        params = self._warmth_knob(warmth)
        if params is None:
            return 0.0
        return replace(self.tech, spectrum_params=params).spectrum().cct_k()

    def _calibrate_arc(self) -> None:
        """A ballasted arc: fixed arc voltage sets the current for the rated power."""
        self.arc_voltage_v = max(self.tech.arc_voltage_v, 1e-6)
        self.arc_current_a = self.rated_source_power_w / self.arc_voltage_v

    # -- spectrum ----------------------------------------------------------
    def _thermal_metrics(self, temp_k: float) -> tuple[float, float, float, float]:
        p = self._spectrum_params
        return thermal_radiator(
            temp_k,
            float(p.get("emissivity_visible", 0.44)),
            float(p.get("emissivity_ir", 0.28)),
            float(p.get("visible_slope_per_nm", 0.0)),
        )

    def _recipe(self) -> LightTechnology:
        """The technology with this lamp's own spectral parameters substituted in."""
        if self._spectrum_params == self.tech.spectrum_params:
            return self.tech
        return replace(self.tech, spectrum_params=self._spectrum_params)

    def spectrum(self, temp_k: float | None = None) -> Spectrum:
        """The current spectral power distribution (rebuilt per temperature if thermal)."""
        if self.tech.is_thermal:
            return self._recipe().spectrum(temp_k if temp_k else self.filament_temp_k())
        if self._spectrum_cache is None:
            self._spectrum_cache = self._recipe().spectrum()
        return self._spectrum_cache

    def _static_photometrics(self) -> tuple[float, float]:
        """``(LER, CCT)`` for the technologies whose spectrum never changes."""
        spd = self.spectrum()
        return spd.ler_lm_per_w, spd.cct_k()

    # -- thermal radiators -------------------------------------------------
    def filament_temp_k(self, drive: float = 1.0, ambient_c: float | None = None) -> float:
        """Steady-state filament temperature at a drive fraction, by bisection.

        Balances ``V^2/R(T)`` against radiation plus conduction. The function is
        monotone in ``T`` over any range that matters (electrical power falls with
        temperature as resistance rises; losses climb as ``T^4``), so a plain
        bisection on 300..6000 K is both robust and fast.
        """
        amb_k = (self.ambient_c if ambient_c is None else ambient_c) + 273.15
        # Clamped at zero but deliberately **not** at one: over-voltage is a real
        # and instructive condition (a filament on a bus above its rating burns
        # brighter, whiter and very much shorter), and the bisection below spans
        # far enough to solve for it.
        v = self.supply_voltage_v * max(0.0, drive)
        if v <= 0:
            return amb_k

        def imbalance(t_k: float) -> float:
            r = self.r_cold_ohm * (t_k / _T_COLD_K) ** self.tech.filament_temp_exponent
            p_in = v * v / max(r, 1e-12)
            exitance, _, _, _ = self._thermal_metrics(t_k)
            p_out = self.filament_area_m2 * exitance + self.g_cond_w_per_k * (t_k - amb_k)
            return p_in - p_out

        lo, hi = max(amb_k, 300.0), 6000.0
        if imbalance(hi) > 0:
            return hi
        if imbalance(lo) < 0:
            return lo
        for _ in range(48):
            mid = 0.5 * (lo + hi)
            if imbalance(mid) > 0:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    # -- solid state -------------------------------------------------------
    def forward_voltage_v(self, current_a: float, junction_c: float) -> float:
        """Diode forward voltage at a current and junction temperature.

        The logarithmic term is the ideal diode law referenced to the rated point;
        the linear term is the series resistance that dominates at high drive; the
        last is the roughly ``-2 mV/K`` shift that makes a hot LED draw more current
        from a fixed-voltage source -- the feedback behind thermal runaway.
        """
        i = max(current_a, 1e-9)
        v_t = K_BOLTZMANN * (junction_c + 273.15) / _Q_ELECTRON
        v = self.vf_rated_v + self.tech.ideality_factor * v_t * math.log(i / self.i_rated_a)
        v += (i - self.i_rated_a) * self.tech.series_resistance_ohm
        v += self.tech.vf_temp_coeff_v_per_k * (junction_c - 25.0)
        return max(v, 0.0)

    def droop_factor(self, current_a: float) -> float:
        """Efficiency droop: relative radiant efficiency at a given drive current.

        An LED is *more* efficient at low current density and loses ground as it is
        driven hard (Auger recombination and carrier leakage). Modelled as
        ``1/(1 + I/I_droop)`` normalised to the rated point, so running at half
        current buys a few percent back -- which is why dimmed LEDs beat their
        datasheet efficacy.
        """
        i_d = self.tech.droop_ref_current_a
        if i_d <= 0:
            return 1.0
        at_rated = 1.0 / (1.0 + self.i_rated_a / i_d)
        return (1.0 / (1.0 + max(current_a, 0.0) / i_d)) / at_rated

    # -- shared derating ---------------------------------------------------
    def ambient_output_factor(self, ambient_c: float) -> float:
        """Relative output from the ambient temperature, for low-pressure discharge.

        Ambient sets the mercury vapour pressure inside the tube, and the 254 nm
        resonance output peaks at one pressure. Modelled as a Gaussian about the
        technology's optimum -- *asymmetric*, because the pressure falls away below
        the optimum faster than it climbs above it. A T8 tube at 0 °C manages a
        little over half its rated output, which is exactly why unheated spaces
        got LED.
        """
        opt = self.tech.optimum_ambient_c
        if opt is None:
            return 1.0
        cold = max(self.tech.ambient_falloff_width_c, 1e-6)
        warm = max(self.tech.ambient_falloff_width_warm_c, 1e-6)
        t = (ambient_c - opt) / (cold if ambient_c < opt else warm)
        return math.exp(-0.5 * t * t)

    def junction_output_factor(self, junction_c: float) -> float:
        """Relative output from junction temperature, for solid state (linear derating)."""
        k = self.tech.flux_temp_coeff_per_k
        if k == 0.0:
            return 1.0
        return max(0.0, 1.0 + k * (junction_c - self.tech.reference_temp_c))

    def warmup_factor(self) -> float:
        """How far through warm-up the lamp is: ``1 - exp(-t/tau)``.

        A cold high-pressure sodium lamp takes five minutes to reach full output;
        a metal halide four. An LED and a filament are effectively instant.
        """
        tau = self.tech.warmup_s
        if tau <= 0:
            return 1.0
        return 1.0 - math.exp(-self.time_lit_s / tau)

    def lumen_maintenance(self) -> float:
        """Flux remaining relative to a new lamp, from age and switching.

        Follows the TM-21 exponential form ``exp(-alpha * hours)`` with ``alpha``
        fixed by the technology's L70 rating, plus the equivalent hours each
        on/off cycle costs (fluorescent cathodes and HID electrodes erode on every
        strike; LEDs and induction lamps do not care).
        """
        equivalent_h = self.operating_hours_h + self.switch_cycles * self.tech.cycle_wear_h
        l70 = self.tech.l70_h
        if l70 <= 0:
            # No published depreciation curve: fall back on a gentle decline to
            # ~80% across the rated life, which is typical of filament lamps.
            life = max(self.tech.rated_life_h, 1.0)
            return max(0.0, 1.0 - 0.2 * equivalent_h / life)
        alpha = -math.log(0.7) / l70
        return math.exp(-alpha * equivalent_h)

    def can_strike(self) -> bool:
        """Whether the lamp will ignite right now.

        A hot high-pressure arc tube needs its vapour pressure to fall before the
        ballast can re-strike it: kill the power to a metal-halide floodlight and
        you wait ten minutes for light, which is why they are never used where an
        instant restart matters.
        """
        if self.tech.restrike_s <= 0:
            return True
        return self.lit or self.time_dark_s >= self.tech.restrike_s

    # -- the operating point ----------------------------------------------
    def operating_point(
        self,
        drive: float = 1.0,
        ambient_c: float | None = None,
        effect: "LightFaultEffect | None" = None,
    ) -> OperatingPoint:
        """Solve the lamp at one drive level -- the single entry point for physics.

        ``drive`` is 0..1 of rated: a dimmer position, a PWM duty, a daylight-
        harvesting setpoint. ``effect`` folds in any accumulated faults.
        """
        from .faults import LightFaultEffect

        if effect is None:
            effect = LightFaultEffect.zeros()
        amb = self.ambient_c if ambient_c is None else ambient_c
        drive = max(0.0, min(1.0, drive)) * effect.drive_mult

        # Below the technology's dimming floor the lamp is simply off (a
        # non-dimmable discharge lamp either runs at full output or not at all).
        floor = self.tech.min_dim_frac
        if drive <= 0.0 or (floor > 0.0 and drive < floor and not self.tech.dimmable):
            drive = 0.0 if drive < floor * 0.5 else (1.0 if not self.tech.dimmable else floor)
        elif floor > 0.0 and drive < floor:
            drive = floor

        lit = drive > 0.0 and self.can_strike() and not effect.failed
        if not lit:
            return OperatingPoint(
                input_power_w=0.0, source_power_w=0.0, current_a=0.0, voltage_v=0.0,
                radiant_power_w=0.0, luminous_flux_lm=0.0, efficacy_lm_per_w=0.0,
                ler_lm_per_w=0.0, color_temp_k=0.0,
                source_temp_c=self.temp_c, visible_fraction=0.0,
                lumen_maintenance=self.lumen_maintenance(), warmup_frac=0.0, lit=False,
            )

        if self.tech.is_thermal:
            point = self._solve_thermal(drive, amb, effect)
        elif self.tech.is_solid_state:
            point = self._solve_solid_state(drive, amb, effect)
        else:
            point = self._solve_discharge(drive, amb, effect)
        return point

    # -- per-family solvers ------------------------------------------------
    def _solve_thermal(self, drive: float, amb: float, effect) -> OperatingPoint:
        v = self.supply_voltage_v * drive * effect.supply_mult
        t_k = self.filament_temp_k(drive * effect.supply_mult, amb)
        r = self.r_cold_ohm * (t_k / _T_COLD_K) ** self.tech.filament_temp_exponent
        r *= effect.resistance_mult
        current = v / max(r, 1e-12)
        p_source = v * current
        exitance, ler, cct, vis = self._thermal_metrics(t_k)
        radiant = self.filament_area_m2 * exitance
        flux = self._flux_from_radiant(radiant, ler, effect, extra=1.0)
        p_input = p_source / max(1.0 - self.gear_loss_frac, 1e-6)
        return self._point(p_input, p_source, current, v, radiant, flux, ler, cct,
                           t_k - 273.15, vis, True)

    def _solve_solid_state(self, drive: float, amb: float, effect) -> OperatingPoint:
        # Junction temperature is where the heat lands; iterate the couple between
        # forward voltage, heat, and junction temperature to a fixed point.
        current = self.die_current_a * drive * effect.current_mult
        t_j = max(self.temp_c, amb)
        vf = self.vf_rated_v
        p_source = 0.0
        for _ in range(24):
            vf = self.forward_voltage_v(current, t_j) * effect.supply_mult
            p_source = vf * current * self.n_emitters
            eta = self.radiant_efficiency * self.droop_factor(current) * effect.efficiency_mult
            p_heat = p_source * (1.0 - min(eta, 0.95))
            t_new = amb + p_heat * self.r_th * effect.thermal_resistance_mult
            if abs(t_new - t_j) < 0.01:
                t_j = t_new
                break
            t_j = t_j + 0.6 * (t_new - t_j)     # damped, so it cannot oscillate

        eta = self.radiant_efficiency * self.droop_factor(current) * effect.efficiency_mult
        radiant = p_source * eta
        ler, cct = self._static_photometrics()
        # Below its threshold a laser diode stops lasing: no beam, all heat.
        if self.tech.spectrum_kind == "laser" and drive < self.tech.min_dim_frac:
            radiant = 0.0
        flux = self._flux_from_radiant(
            radiant, ler, effect, extra=self.junction_output_factor(t_j)
        )
        p_input = p_source / max(1.0 - self.gear_loss_frac, 1e-6)
        vis = self.spectrum().visible_fraction()
        return self._point(p_input, p_source, current, vf, radiant, flux, ler, cct,
                           t_j, vis, True)

    def _solve_discharge(self, drive: float, amb: float, effect) -> OperatingPoint:
        p_source = self.rated_source_power_w * drive * effect.current_mult
        current = p_source / self.arc_voltage_v
        eta = self.radiant_efficiency * effect.efficiency_mult
        radiant = p_source * eta
        ler, cct = self._static_photometrics()
        extra = self.ambient_output_factor(amb) * self.warmup_factor()
        flux = self._flux_from_radiant(radiant, ler, effect, extra=extra)
        p_input = p_source / max(1.0 - self.gear_loss_frac, 1e-6)
        # The wall temperature the lamp settles at; drives nothing but reporting
        # for high-pressure types, and is the physical reason for the ambient
        # factor on the low-pressure ones.
        t_wall = amb + p_source * (1.0 - eta) * self.r_th * effect.thermal_resistance_mult
        vis = self.spectrum().visible_fraction()
        return self._point(p_input, p_source, current, self.arc_voltage_v, radiant,
                           flux, ler, cct, t_wall, vis, True)

    # -- shared plumbing ---------------------------------------------------
    def _flux_from_radiant(self, radiant_w: float, ler: float, effect, extra: float) -> float:
        """Radiant watts -> lumens, through every loss that stands in the way."""
        return (
            radiant_w
            * ler
            * self.envelope_transmission
            * (1.0 - self.dirt_frac)
            * self.lumen_maintenance()
            * max(0.0, extra)
            * effect.flux_mult
        )

    def _point(self, p_input, p_source, current, voltage, radiant, flux, ler, cct,
               temp_c, vis, lit) -> OperatingPoint:
        return OperatingPoint(
            input_power_w=p_input,
            source_power_w=p_source,
            current_a=current,
            voltage_v=voltage,
            radiant_power_w=radiant,
            luminous_flux_lm=flux,
            efficacy_lm_per_w=(flux / p_input) if p_input > 0 else 0.0,
            ler_lm_per_w=ler,
            color_temp_k=cct,
            source_temp_c=temp_c,
            visible_fraction=vis,
            lumen_maintenance=self.lumen_maintenance(),
            warmup_frac=self.warmup_factor(),
            lit=lit,
        )

    # -- running off a supply that is not at its nominal voltage -----------
    def at_supply(
        self,
        supply_voltage_v: float,
        drive: float = 1.0,
        ambient_c: float | None = None,
        effect: "LightFaultEffect | None" = None,
    ) -> "SupplyPoint":
        """Solve the lamp against the voltage that has *actually* arrived.

        :meth:`operating_point` answers "what does this lamp do at dim level
        ``drive``?", which assumes the supply is at its rated voltage. Wire it to
        the far end of a long cable, or to a battery that has been discharging all
        afternoon, and it is not -- and what happens next depends entirely on
        whether the lamp has control gear in front of it.

        **A filament has none.** It is connected straight across the supply, so
        the voltage *is* the drive: sag it and the filament cools, the light
        collapses far faster than the power does, and the colour reddens. Over-volt
        it and it burns brighter, whiter and very much shorter. Light output goes
        roughly as ``V^3.4``, which is why filament lamps are such a good
        indicator of what the cable did to you.

        **An LED driver or a discharge ballast is a regulator.** It holds its
        output constant across a wide input range, so the lamp does not dim at
        all -- but constant *power* off a sagging bus means the current it draws
        goes **up**, which is a genuinely under-appreciated property of DC
        systems: the load fights back, pulling the bus down further. Below the
        gear's dropout voltage it stops regulating and the lamp goes out
        completely, with no dimming on the way down to warn anybody.

        Returns a :class:`SupplyPoint` carrying both the photometric answer and
        the current the *supply* sees, which are not the same number for any lamp
        with gear in it.
        """
        from .faults import LightFaultEffect

        if effect is None:
            effect = LightFaultEffect.zeros()
        nominal = self.supply_voltage_v
        supply_v = max(0.0, float(supply_voltage_v))
        ratio = supply_v / nominal if nominal > 0 else 0.0

        if self.regulated:
            # The gear either regulates or it does not.
            dropped_out = ratio < self.tech.gear_dropout_frac
            if dropped_out:
                point = self._dark_point()
                return SupplyPoint(
                    supply_voltage_v=supply_v, nominal_voltage_v=nominal,
                    voltage_ratio=ratio, supply_current_a=0.0, regulated=True,
                    dropped_out=True, over_voltage=False, point=point,
                )
            point = self.operating_point(drive, ambient_c, effect)
            # Constant power in, so the current rises as the voltage falls.
            current = point.input_power_w / supply_v if supply_v > 0 else 0.0
            return SupplyPoint(
                supply_voltage_v=supply_v, nominal_voltage_v=nominal,
                voltage_ratio=ratio, supply_current_a=current, regulated=True,
                dropped_out=False,
                over_voltage=ratio > 1.0 + (1.0 - self.tech.gear_dropout_frac),
                point=point,
            )

        # Unregulated: the supply ratio rides the same channel a brown-out fault
        # uses, so a sagging bus and an injected voltage fault compose correctly
        # rather than one overwriting the other.
        scaled = replace(effect, supply_mult=effect.supply_mult * ratio)
        point = self.operating_point(drive, ambient_c, scaled)
        return SupplyPoint(
            supply_voltage_v=supply_v, nominal_voltage_v=nominal,
            voltage_ratio=ratio,
            # The filament current *is* the supply current: nothing sits between.
            supply_current_a=point.current_a,
            regulated=False, dropped_out=False, over_voltage=ratio > 1.05,
            point=point,
        )

    @property
    def regulated(self) -> bool:
        """Whether control gear stands between the supply and the light source.

        Solid-state and discharge lamps always have some -- a driver or a ballast
        -- and filament lamps never do. That single fact decides how each responds
        to a supply that is off nominal, so it is worth naming rather than
        re-deriving.
        """
        return not self.tech.is_thermal

    def _dark_point(self) -> OperatingPoint:
        """The operating point of a lamp that is not lit."""
        return OperatingPoint(
            input_power_w=0.0, source_power_w=0.0, current_a=0.0, voltage_v=0.0,
            radiant_power_w=0.0, luminous_flux_lm=0.0, efficacy_lm_per_w=0.0,
            ler_lm_per_w=0.0, color_temp_k=0.0, source_temp_c=self.temp_c,
            visible_fraction=0.0, lumen_maintenance=self.lumen_maintenance(),
            warmup_frac=0.0, lit=False,
        )

    # -- integrator --------------------------------------------------------
    def step(
        self,
        drive: float,
        dt_s: float,
        ambient_c: float | None = None,
        effect: "LightFaultEffect | None" = None,
    ) -> OperatingPoint:
        """Advance the lamp by ``dt_s`` and return the operating point it reached.

        Tracks the three things that make a lamp's behaviour history-dependent:
        the thermal node's approach to its steady state, warm-up since the last
        strike (and cool-down since it went dark, for restrike), and accumulated
        operating hours for lumen depreciation.
        """
        if ambient_c is not None:
            self.ambient_c = ambient_c

        was_lit = self.lit
        point = self.operating_point(drive, self.ambient_c, effect)

        if point.lit and not was_lit:
            self.switch_cycles += 1
            self.time_lit_s = 0.0
        if point.lit:
            self.time_lit_s += dt_s
            self.time_dark_s = 0.0
            self.operating_hours_h += dt_s / 3600.0
        else:
            self.time_dark_s += dt_s
            self.time_lit_s = 0.0
        self.lit = point.lit

        # The temperature node relaxes towards the point's steady-state value with
        # the lamp's own thermal time constant, so a just-switched-on floodlight is
        # briefly cooler (and brighter) than the same lamp an hour later.
        target = point.source_temp_c if point.lit else self.ambient_c
        tau = max(self.c_th * self.r_th, 1e-6)
        self.temp_c += (target - self.temp_c) * (1.0 - math.exp(-dt_s / tau))

        # Re-report with the settled temperature so the caller sees the transient,
        # not the steady state -- for solid state that is a real brightness change.
        if point.lit and self.tech.is_solid_state:
            settled = self.junction_output_factor(self.temp_c)
            instant = self.junction_output_factor(point.source_temp_c)
            if instant > 0:
                flux = point.luminous_flux_lm * settled / instant
                point = OperatingPoint(
                    **{**point.to_dict(),
                       "luminous_flux_lm": flux,
                       "efficacy_lm_per_w": flux / point.input_power_w if point.input_power_w else 0.0,
                       "source_temp_c": self.temp_c}
                )
        return point


def _pick(override: float | None, default: float) -> float:
    return float(default if override is None else override)


# ---------------------------------------------------------------------------
# White-LED phosphor blending.
#
# A blue die and two phosphors give three free parameters, and only a curve
# through that space produces *white* light -- everything else is off the
# Planckian locus and would never be sold as an illuminant. Real manufacturing
# calls that curve binning: parts are sorted onto it and the ones that miss are
# discarded.
#
# So the model finds the curve once per phosphor system, by searching the blend
# space for the combinations that sit on the locus, and then walks along it. A
# lamp's colour temperature picks a point on that curve, and its efficacy is
# whatever the spectrum there happens to give -- which is how warm white ends up
# less efficacious than cool white without anyone saying so.
# ---------------------------------------------------------------------------

# How far off the Planckian locus a blend may sit and still count as white. Real
# binning is far tighter than this; the tolerance here only has to be small enough
# that the search follows the locus rather than wandering across the diagram.
_LOCUS_TOLERANCE = 0.015


@lru_cache(maxsize=64)
def _led_locus_curve(
    pump_nm: float,
    pump_fwhm_nm: float,
    phosphor_fwhm_nm: float,
    red_fwhm_nm: float,
    red_nm: float,
) -> tuple[tuple[float, float, float, float], ...]:
    """Blends that produce white light, as ``(cct, conversion, red_frac, phosphor_nm)``.

    Searched once per phosphor system and cached. Sorted by colour temperature,
    coolest first, so :func:`_led_blend_path` can interpolate along it.
    """
    from .spectrum import blackbody, phosphor_led

    found: list[tuple[float, float, float, float]] = []
    for ci in range(16):
        conv = 0.62 + 0.36 * ci / 15.0
        for ri in range(13):
            red = 0.7 * ri / 12.0
            for pi in range(5):
                phosphor = 555.0 + 10.0 * pi
                spd = phosphor_led(
                    pump_nm=pump_nm,
                    pump_fwhm_nm=pump_fwhm_nm,
                    phosphor_nm=phosphor,
                    phosphor_fwhm_nm=phosphor_fwhm_nm,
                    conversion_frac=conv,
                    red_nm=red_nm,
                    red_fwhm_nm=red_fwhm_nm,
                    red_frac=red,
                )
                x, y = spd.chromaticity()
                denom = 0.1858 - y
                if abs(denom) < 1e-9:
                    continue
                n = (x - 0.3320) / denom
                cct = 449.0 * n ** 3 + 3525.0 * n ** 2 + 6823.3 * n + 5520.33
                if not 1800.0 <= cct <= 8000.0:
                    continue
                bx, by = blackbody(cct).chromaticity()
                if math.hypot(x - bx, y - by) > _LOCUS_TOLERANCE:
                    continue
                found.append((cct, conv, red, phosphor))

    if not found:
        return ()
    # Keep the closest blend per 100 K bucket, so the curve is a clean path
    # rather than a cloud of near-duplicates.
    best: dict[int, tuple[float, float, float, float]] = {}
    for entry in found:
        bucket = int(entry[0] // 100)
        if bucket not in best or entry[2] < best[bucket][2]:
            best[bucket] = entry
    return tuple(sorted(best.values(), reverse=True))


def _led_blend_path(
    pump_nm: float,
    pump_fwhm_nm: float,
    phosphor_fwhm_nm: float,
    red_fwhm_nm: float,
    red_nm: float,
    warmth: float,
) -> tuple[float, float, float]:
    """``(conversion_frac, red_frac, phosphor_nm)`` at 0 (coolest) to 1 (warmest)."""
    curve = _led_locus_curve(pump_nm, pump_fwhm_nm, phosphor_fwhm_nm, red_fwhm_nm, red_nm)
    if not curve:
        return 0.80, 0.12, 565.0
    idx = max(0.0, min(1.0, warmth)) * (len(curve) - 1)
    lo = curve[int(math.floor(idx))]
    hi = curve[min(len(curve) - 1, int(math.ceil(idx)))]
    frac = idx - math.floor(idx)
    return (
        lo[1] + (hi[1] - lo[1]) * frac,
        lo[2] + (hi[2] - lo[2]) * frac,
        lo[3] + (hi[3] - lo[3]) * frac,
    )
