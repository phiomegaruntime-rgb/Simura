"""Fault-injection framework for light sources.

Mirrors :mod:`simura.wires.faults` and :mod:`simura.sim.faults`: every active
fault contributes to a shared :class:`LightFaultEffect` accumulator each timestep,
so faults compose and the solver never needs to know about individual fault types.

These are the ways lighting actually fails -- and most of them fail *gradually*,
which is what makes them interesting. A luminaire rarely goes dark; it dims, it
shifts colour, it starts to flicker, its driver runs hot and takes the LEDs with
it. Each of those is a different maintenance decision, and telling them apart from
telemetry is the whole job.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class LightFaultEffect:
    """Accumulated fault contributions applied when the lamp is solved.

    Multiplicative fields start at 1.0 and flags at False, so "no fault" is the
    identity.
    """

    flux_mult: float = 1.0                  # scales luminous output
    efficiency_mult: float = 1.0            # scales radiant efficiency (heat instead of light)
    drive_mult: float = 1.0                 # scales the commanded dim level
    current_mult: float = 1.0               # scales drive current / arc power
    supply_mult: float = 1.0                # scales supply or forward voltage
    resistance_mult: float = 1.0            # scales filament resistance
    thermal_resistance_mult: float = 1.0    # scales the heat path to ambient
    cct_shift_k: float = 0.0                # colour drift (reported, not re-radiated)
    failed: bool = False                    # the lamp does not light at all

    @classmethod
    def zeros(cls) -> "LightFaultEffect":
        return cls()


class Fault:
    """Base class. A fault is active in the half-open window ``[start_s, end_s)``."""

    def __init__(self, start_s: float = 0.0, end_s: float = float("inf")) -> None:
        self.start_s = start_s
        self.end_s = end_s

    def active(self, t: float) -> bool:
        return self.start_s <= t < self.end_s

    def elapsed(self, t: float) -> float:
        return max(0.0, t - self.start_s)

    def contribute(self, effect: LightFaultEffect, light, t: float) -> None:  # pragma: no cover
        raise NotImplementedError


class LumenDepreciation(Fault):
    """Accelerated light loss: the lamp keeps drawing power and stops delivering.

    The failure mode that costs the most and is noticed the least -- output decays
    quietly while the meter runs. ``rate_per_h`` is the exponential decay constant
    on top of the technology's normal ageing.
    """

    def __init__(self, rate_per_h: float = 2e-4, floor: float = 0.2, **kw) -> None:
        super().__init__(**kw)
        self.rate_per_h = rate_per_h
        self.floor = floor

    def contribute(self, effect: LightFaultEffect, light, t: float) -> None:
        if not self.active(t):
            return
        hours = self.elapsed(t) / 3600.0
        effect.flux_mult *= max(self.floor, math.exp(-self.rate_per_h * hours))


class PhosphorDegradation(Fault):
    """A cooked phosphor: light output falls and the colour drifts blue.

    Overheating an LED's phosphor (or an aged fluorescent coating) destroys the
    down-conversion, so less of the blue pump is converted. Output drops and what
    is left is bluer -- a diagnosis you can make on colour alone.
    """

    def __init__(self, loss_frac: float = 0.25, cct_shift_k: float = 600.0, **kw) -> None:
        super().__init__(**kw)
        self.loss_frac = min(max(loss_frac, 0.0), 0.95)
        self.cct_shift_k = cct_shift_k

    def contribute(self, effect: LightFaultEffect, light, t: float) -> None:
        if not self.active(t):
            return
        effect.flux_mult *= 1.0 - self.loss_frac
        effect.cct_shift_k += self.cct_shift_k


class HeatsinkLoss(Fault):
    """A blocked or detached heatsink: the thermal path to ambient degrades.

    On a solid-state lamp this is the classic slow killer. The junction runs
    hotter, output derates, the forward voltage drops, current rises if the driver
    is not current-limited -- and the whole thing accelerates.
    """

    def __init__(self, r_th_mult: float = 2.5, **kw) -> None:
        super().__init__(**kw)
        self.r_th_mult = max(r_th_mult, 1.0)

    def contribute(self, effect: LightFaultEffect, light, t: float) -> None:
        if self.active(t):
            effect.thermal_resistance_mult *= self.r_th_mult


class DriverFault(Fault):
    """Control gear misbehaving: driver or ballast delivering the wrong current.

    ``current_mult`` above 1 is an over-driving driver (bright now, dead soon);
    below 1 is a failing one. ``efficiency_loss_frac`` accounts for gear that turns
    the difference into heat rather than light.
    """

    def __init__(self, current_mult: float = 1.35, efficiency_loss_frac: float = 0.1, **kw) -> None:
        super().__init__(**kw)
        self.current_mult = max(current_mult, 0.0)
        self.efficiency_loss_frac = min(max(efficiency_loss_frac, 0.0), 0.95)

    def contribute(self, effect: LightFaultEffect, light, t: float) -> None:
        if not self.active(t):
            return
        effect.current_mult *= self.current_mult
        effect.efficiency_mult *= 1.0 - self.efficiency_loss_frac


class SupplyVoltageFault(Fault):
    """Supply out of tolerance -- a brown-out, or a long feeder sagging under load.

    Brutal on filament lamps: light output goes roughly as the 3.4th power of
    supply voltage, so a 10% sag costs about 30% of the light, while a 10%
    over-voltage buys 35% more light and cuts the lamp's life by two thirds.
    """

    def __init__(self, supply_mult: float = 0.9, **kw) -> None:
        super().__init__(**kw)
        self.supply_mult = max(supply_mult, 0.0)

    def contribute(self, effect: LightFaultEffect, light, t: float) -> None:
        if self.active(t):
            effect.supply_mult *= self.supply_mult


class Flicker(Fault):
    """Periodic output modulation: a failing ballast, a bad dimmer, a loose joint.

    ``depth`` is the peak-to-peak swing as a fraction of output and ``freq_hz`` its
    rate. Low-frequency flicker is the kind people actually see and get headaches
    from; this makes it reproducible.
    """

    def __init__(self, depth: float = 0.4, freq_hz: float = 8.0, **kw) -> None:
        super().__init__(**kw)
        self.depth = min(max(depth, 0.0), 1.0)
        self.freq_hz = max(freq_hz, 1e-6)

    def contribute(self, effect: LightFaultEffect, light, t: float) -> None:
        if not self.active(t):
            return
        phase = 2.0 * math.pi * self.freq_hz * t
        effect.flux_mult *= max(0.0, 1.0 - 0.5 * self.depth * (1.0 - math.cos(phase)))


class LensFouling(Fault):
    """Dirt, insects, corrosion or UV-hazed optics between the source and the room.

    Purely optical: the lamp is healthy and the power is unchanged, but less light
    escapes. Distinguishing this from lumen depreciation is a cleaning decision
    versus a replacement decision.
    """

    def __init__(self, rate_per_h: float = 1e-4, max_loss_frac: float = 0.5, **kw) -> None:
        super().__init__(**kw)
        self.rate_per_h = rate_per_h
        self.max_loss_frac = min(max(max_loss_frac, 0.0), 0.99)

    def contribute(self, effect: LightFaultEffect, light, t: float) -> None:
        if not self.active(t):
            return
        loss = min(self.max_loss_frac, self.rate_per_h * self.elapsed(t) / 3600.0)
        effect.flux_mult *= 1.0 - loss


class Burnout(Fault):
    """The lamp is out: a broken filament, a failed driver, an arc that will not strike.

    The one unambiguous fault -- and in a lit space the only one anybody reports.
    """

    def contribute(self, effect: LightFaultEffect, light, t: float) -> None:
        if self.active(t):
            effect.failed = True


def accumulate(faults: list[Fault], light, t: float) -> LightFaultEffect:
    """Combine every active fault's contribution into one :class:`LightFaultEffect`."""
    effect = LightFaultEffect.zeros()
    for f in faults:
        f.contribute(effect, light, t)
    return effect
