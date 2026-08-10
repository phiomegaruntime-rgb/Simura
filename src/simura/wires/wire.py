"""The wire model: a config description and its electro-thermal runtime state.

Split exactly like the battery side (:class:`~simura.sim.config.CellParams` /
:class:`~simura.sim.pack.BatteryPack`): :class:`WireSpec` is a plain,
serializable description of *what* the wire is; :class:`Wire` holds the live
state (its temperature) and does the physics.

Physics (single conductor):

    Resistance:   R(T) = rho_20 * (1 + alpha*(T-20)) * L / A
    Drop:         dV   = I * R
    Loss:         P    = I^2 * R
    Thermal:      dT/dt = (I^2*R - k_cool*(T - T_amb)) / C_th     [explicit Euler]

A :class:`WireSpec` models **one** conductor of ``length_m``. For a two-wire DC
circuit (out and back), either set ``length_m`` to the total conductor length or
let :func:`simura.wires.planning.evaluate_run` double it via ``round_trip``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .catalog import insulation_temp_c, material_for, wire_type_for


@dataclass
class WireSpec:
    """A serializable description of a wire run.

    Provide the conductor size as either ``awg`` or ``area_mm2`` (or reference a
    catalog ``wire_type`` id, which fills material/gauge/insulation/ampacity
    defaults for any field left unset). Thermal parameters default to
    geometry-based estimates when left as ``None``.
    """

    material: str = "copper"
    awg: int | None = None
    area_mm2: float | None = None
    length_m: float = 1.0
    insulation: str = "PVC-90"
    ampacity_a: float | None = None
    ambient_temp_c: float = 25.0

    # Convective/thermal parameters (None -> estimated from geometry).
    thermal_capacity_j_per_k: float | None = None
    cooling_conductance_w_per_k: float | None = None
    convection_coeff_w_m2_k: float = 10.0     # h, natural convection in still air

    # Optional catalog reference that fills any unset field above.
    wire_type: str | None = None

    def to_dict(self) -> dict:
        from dataclasses import asdict

        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WireSpec":
        from dataclasses import fields

        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


# Fallback current density (A/mm^2) used only to estimate an ampacity when a spec
# gives neither an explicit value nor a catalog type. ~4 A/mm^2 is a conventional
# rough figure for insulated copper in air.
_DEFAULT_CURRENT_DENSITY_A_MM2 = 4.0


class Wire:
    """Live electro-thermal state of a single conductor run."""

    def __init__(self, spec: WireSpec) -> None:
        self.spec = spec
        from .catalog import awg_area_mm2

        # Start from the catalog type (if any), then let explicit spec fields win.
        # A catalog wire_type is the base: its material/insulation/ampacity apply
        # unless overridden, and its size applies unless awg/area_mm2 is given.
        material = material_for(spec.material)
        insulation = spec.insulation
        ampacity = spec.ampacity_a
        area_mm2 = spec.area_mm2
        if spec.wire_type is not None:
            wt = wire_type_for(spec.wire_type)
            material = material_for(wt.material)
            insulation = wt.insulation
            if ampacity is None:
                ampacity = wt.ampacity_a
            if area_mm2 is None and spec.awg is None:
                area_mm2 = wt.area_mm2
        if area_mm2 is None and spec.awg is not None:
            area_mm2 = awg_area_mm2(spec.awg)
        if area_mm2 is None:
            raise ValueError("WireSpec needs area_mm2, awg, or a wire_type to size the conductor")

        self.material = material
        self.area_mm2 = float(area_mm2)
        self.area_m2 = self.area_mm2 * 1e-6
        self.length_m = float(spec.length_m)
        self.insulation = insulation
        self.temp_rating_c = insulation_temp_c(insulation)
        if ampacity is None:
            # Prefer a catalog reference for this material/gauge/insulation; only
            # fall back to a conservative current-density estimate if none exists.
            from .catalog import catalog_ampacity_for

            ampacity = (
                catalog_ampacity_for(material.key, spec.awg, insulation)
                if spec.awg is not None
                else None
            )
            if ampacity is None:
                ampacity = _DEFAULT_CURRENT_DENSITY_A_MM2 * self.area_mm2
        self.ampacity_a = float(ampacity)

        # Conductor diameter and lateral surface area (for convective cooling).
        self.diameter_m = 2.0 * math.sqrt(self.area_m2 / math.pi)
        surface_m2 = math.pi * self.diameter_m * self.length_m

        # Thermal parameters: geometry-based defaults unless overridden.
        if spec.thermal_capacity_j_per_k is not None:
            self.c_th = float(spec.thermal_capacity_j_per_k)
        else:
            mass_kg = self.area_m2 * self.length_m * material.density_kg_m3
            self.c_th = max(mass_kg * material.specific_heat_j_per_kg_k, 1e-6)
        if spec.cooling_conductance_w_per_k is not None:
            self.k_cool = float(spec.cooling_conductance_w_per_k)
        else:
            self.k_cool = max(spec.convection_coeff_w_m2_k * surface_m2, 1e-9)

        self.ambient_c = float(spec.ambient_temp_c)
        self.temp_c = self.ambient_c

    # -- electrical -------------------------------------------------------
    def resistance_ohm(self, at_temp_c: float | None = None) -> float:
        """Conductor resistance at ``at_temp_c`` (defaults to current temp)."""
        t = self.temp_c if at_temp_c is None else at_temp_c
        return self.material.resistivity_at(t) * self.length_m / self.area_m2

    @property
    def resistance_20c_ohm(self) -> float:
        return self.resistance_ohm(20.0)

    def voltage_drop_v(self, current_a: float, at_temp_c: float | None = None) -> float:
        """Signed voltage drop ``I*R`` across the conductor."""
        return current_a * self.resistance_ohm(at_temp_c)

    def power_loss_w(self, current_a: float, at_temp_c: float | None = None) -> float:
        """Ohmic loss ``I^2*R`` dissipated in the conductor."""
        return current_a * current_a * self.resistance_ohm(at_temp_c)

    def ampacity_utilization(self, current_a: float) -> float:
        return abs(current_a) / self.ampacity_a if self.ampacity_a > 0 else 0.0

    def derated_ampacity_a(self, ambient_c: float, ref_ambient_c: float = 30.0) -> float:
        """Ampacity corrected for ambient temperature (NEC 310.15(B)-style).

        A catalog ampacity is the current that brings the conductor to its
        insulation rating at a reference ambient (``ref_ambient_c``, ~30 C for the
        free-air reference numbers here). On a hotter day there is less headroom to
        the rating, so the safe current falls; on a colder day it rises. The
        standard correction is ``sqrt((T_rating - T_amb) / (T_rating - T_ref))``,
        which follows from ``I^2*R = k*(T_rating - T_amb)``. Returns 0 once the
        ambient reaches the insulation rating (no capacity left).
        """
        ref_headroom = self.temp_rating_c - ref_ambient_c
        headroom = self.temp_rating_c - ambient_c
        if ref_headroom <= 0:
            return self.ampacity_a
        if headroom <= 0:
            return 0.0
        return self.ampacity_a * math.sqrt(headroom / ref_headroom)

    def steady_state_temp_c(
        self,
        current_a: float,
        ambient_c: float | None = None,
        cooling_mult: float = 1.0,
        extra_heat_w: float = 0.0,
    ) -> float:
        """Equilibrium temperature under a constant current.

        Solves ``I^2*R(T) + extra_heat_w = k_cool*cooling_mult*(T - T_amb)`` by
        fixed-point iteration, so the temperature-dependence of resistance is
        respected. ``cooling_mult`` (wind) and ``extra_heat_w`` (absorbed sun) let
        the weather coupling be reflected in the steady state, mirroring
        :meth:`step`.
        """
        amb = self.ambient_c if ambient_c is None else ambient_c
        k = self.k_cool * cooling_mult
        t = amb
        for _ in range(50):
            r = self.resistance_ohm(t)
            t_new = amb + (current_a * current_a * r + extra_heat_w) / k
            if abs(t_new - t) < 1e-6:
                return t_new
            t = t_new
        return t

    # -- thermal integrator ----------------------------------------------
    def step(
        self,
        current_a: float,
        dt_s: float,
        ambient_c: float | None = None,
        effect: "FaultEffect | None" = None,
    ) -> None:
        """Advance the conductor temperature by ``dt_s`` under ``current_a``."""
        from .faults import FaultEffect

        if effect is None:
            effect = FaultEffect.zeros()
        if ambient_c is not None:
            self.ambient_c = ambient_c

        r = self.resistance_ohm(self.temp_c) * effect.resistance_mult + effect.extra_resistance_ohm
        i = current_a + effect.extra_current_a
        q_gen = i * i * r + effect.extra_heat_w
        k_cool = self.k_cool * effect.cooling_mult
        dtemp = (q_gen - k_cool * (self.temp_c - self.ambient_c)) / self.c_th * dt_s
        self.temp_c = self.temp_c + dtemp
        # Stash the effective resistance/current so telemetry reflects faults.
        self._last_resistance_ohm = r
        self._last_current_a = i

    # -- fault-aware ratings (used by telemetry) --------------------------
    def effective_ampacity_a(self, effect: "FaultEffect | None" = None) -> float:
        if effect is None:
            return self.ampacity_a
        return self.ampacity_a * effect.ampacity_mult

    def effective_temp_rating_c(self, effect: "FaultEffect | None" = None) -> float:
        if effect is None:
            return self.temp_rating_c
        return self.temp_rating_c + effect.temp_rating_delta
