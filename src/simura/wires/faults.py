"""Fault-injection framework for wires.

Mirrors :mod:`simura.sim.faults`: every active fault contributes to a shared
:class:`FaultEffect` accumulator each timestep, so faults compose and the
integrator never needs to know about individual fault types. These are the
electrical failure modes wiring actually suffers -- corrosion, loose joints,
nicked conductors, cooked insulation, leakage to ground -- made reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FaultEffect:
    """Accumulated fault contributions applied by :meth:`Wire.step`.

    Multiplicative fields start at 1.0 and additive fields at 0.0 so that
    "no fault" is the identity.
    """

    resistance_mult: float = 1.0        # scales conductor resistance
    extra_resistance_ohm: float = 0.0   # series resistance added (e.g. bad joint)
    extra_current_a: float = 0.0        # parasitic current (e.g. ground fault)
    extra_heat_w: float = 0.0           # extra heat injected (e.g. hot joint, absorbed sun)
    cooling_mult: float = 1.0           # scales convective cooling (e.g. wind)
    ampacity_mult: float = 1.0          # derates the current rating
    temp_rating_delta: float = 0.0      # shifts the insulation temp limit (<0 = degraded)

    @classmethod
    def zeros(cls) -> "FaultEffect":
        return cls()


class Fault:
    """Base class. A fault is active in the half-open window ``[start_s, end_s)``."""

    def __init__(self, start_s: float = 0.0, end_s: float = float("inf")) -> None:
        self.start_s = start_s
        self.end_s = end_s

    def active(self, t: float) -> bool:
        return self.start_s <= t < self.end_s

    def contribute(self, effect: FaultEffect, wire, t: float) -> None:  # pragma: no cover
        raise NotImplementedError


class ResistanceGrowth(Fault):
    """Corrosion / oxidation / annealing that raises resistance over time.

    ``rate_per_s`` grows the multiplier linearly from fault onset (e.g.
    ``rate_per_s=1e-4`` adds ~0.36 to the multiplier per hour).
    """

    def __init__(self, rate_per_s: float = 1e-4, max_mult: float = 3.0, **kw) -> None:
        super().__init__(**kw)
        self.rate_per_s = rate_per_s
        self.max_mult = max_mult

    def contribute(self, effect: FaultEffect, wire, t: float) -> None:
        if not self.active(t):
            return
        grown = 1.0 + self.rate_per_s * (t - self.start_s)
        effect.resistance_mult *= min(grown, self.max_mult)


class ContactResistance(Fault):
    """A loose or corroded connection: a lump of series resistance at a joint.

    Real connectors fail here first -- the added resistance both drops voltage
    and dumps ``I^2*R`` heat right at the joint, the classic hot-spot.
    """

    def __init__(self, added_ohm: float = 0.01, **kw) -> None:
        super().__init__(**kw)
        self.added_ohm = added_ohm

    def contribute(self, effect: FaultEffect, wire, t: float) -> None:
        if self.active(t):
            effect.extra_resistance_ohm += self.added_ohm


class ConductorDamage(Fault):
    """A nick / partial break: effective cross-section is reduced.

    Losing a fraction of the strands raises resistance by ``1/(1-frac)`` and
    derates ampacity by ``(1-frac)`` -- less copper carries the same current.
    """

    def __init__(self, area_loss_frac: float = 0.3, **kw) -> None:
        super().__init__(**kw)
        self.area_loss_frac = min(max(area_loss_frac, 0.0), 0.95)

    def contribute(self, effect: FaultEffect, wire, t: float) -> None:
        if not self.active(t):
            return
        remaining = 1.0 - self.area_loss_frac
        effect.resistance_mult *= 1.0 / remaining
        effect.ampacity_mult *= remaining


class InsulationDegradation(Fault):
    """Thermal/UV ageing that lowers the safe conductor temperature.

    Does not change the physics -- it lowers the *rating* the telemetry compares
    against, so an over-temperature flag can trip earlier as insulation ages.
    """

    def __init__(self, rating_drop_c: float = 20.0, **kw) -> None:
        super().__init__(**kw)
        self.rating_drop_c = rating_drop_c

    def contribute(self, effect: FaultEffect, wire, t: float) -> None:
        if self.active(t):
            effect.temp_rating_delta -= self.rating_drop_c


class GroundFault(Fault):
    """Insulation breakdown leaking current to ground -- a parasitic drain."""

    def __init__(self, leakage_a: float = 1.0, **kw) -> None:
        super().__init__(**kw)
        self.leakage_a = leakage_a

    def contribute(self, effect: FaultEffect, wire, t: float) -> None:
        if self.active(t):
            effect.extra_current_a += self.leakage_a


def accumulate(faults: list[Fault], wire, t: float) -> FaultEffect:
    """Combine every active fault's contribution into one :class:`FaultEffect`."""
    effect = FaultEffect.zeros()
    for f in faults:
        f.contribute(effect, wire, t)
    return effect
