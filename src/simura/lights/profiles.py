"""Drive profiles: how a lamp is commanded over time.

Domain-neutral by design -- a profile maps simulated time (seconds) to a **drive
level** in 0..1, and knows nothing about which technology is on the other end.
The parallel to :mod:`simura.wires.profiles` (current) and
:mod:`simura.sim.profiles` (load), but the controlled quantity here is dimming.

Lighting is almost never left at full output. It is switched on a schedule,
dimmed to a setpoint, cycled by occupancy, faded at dawn, or -- most interestingly
-- driven by how much daylight is already in the room. The last of those needs to
see the environment, so it lives in :mod:`simura.lights.environment`; everything
that depends only on the clock lives here.
"""

from __future__ import annotations

import math
from typing import Callable, Protocol


class DriveProfile(Protocol):
    def drive(self, t: float) -> float: ...


class ConstantDrive:
    """Steady output at a fixed dim level (1.0 = full)."""

    def __init__(self, level: float = 1.0) -> None:
        self.level = max(0.0, min(1.0, level))

    def drive(self, t: float) -> float:
        return self.level


class Schedule:
    """On for ``on_s`` from ``start_s`` each ``period_s`` -- a timeclock.

    The most common control in existence: lights on at seven, off at eleven,
    every day. ``level`` is the output while on.
    """

    def __init__(
        self, start_s: float = 0.0, on_s: float = 43200.0,
        period_s: float = 86400.0, level: float = 1.0
    ) -> None:
        self.start_s = start_s
        self.on_s = on_s
        self.period_s = max(period_s, 1e-9)
        self.level = max(0.0, min(1.0, level))

    def drive(self, t: float) -> float:
        phase = (t - self.start_s) % self.period_s
        return self.level if 0.0 <= phase < self.on_s else 0.0


class Ramp:
    """A linear fade from ``start_level`` to ``end_level`` over ``duration_s``.

    Sunrise simulation, theatre fades, and the soft start that spares a filament
    the inrush of a cold switch-on.
    """

    def __init__(
        self, start_level: float = 0.0, end_level: float = 1.0,
        duration_s: float = 60.0, start_s: float = 0.0
    ) -> None:
        self.start_level = start_level
        self.end_level = end_level
        self.duration_s = max(duration_s, 1e-9)
        self.start_s = start_s

    def drive(self, t: float) -> float:
        frac = (t - self.start_s) / self.duration_s
        frac = max(0.0, min(1.0, frac))
        return max(0.0, min(1.0, self.start_level + (self.end_level - self.start_level) * frac))


class PwmDrive:
    """Pulse-width modulation: full output for a duty fraction of each period.

    How LEDs are actually dimmed. The *average* output is the duty cycle, but the
    lamp is never at a partial drive -- it is fully on or fully off, thousands of
    times a second. Simulated at a timestep coarser than the period this behaves
    as the duty cycle; simulated finely it shows the real square wave, which is
    what a flicker measurement would see.
    """

    def __init__(self, duty: float = 0.5, freq_hz: float = 1000.0) -> None:
        self.duty = max(0.0, min(1.0, duty))
        self.freq_hz = max(freq_hz, 1e-9)

    def drive(self, t: float) -> float:
        period = 1.0 / self.freq_hz
        return 1.0 if (t % period) < self.duty * period else 0.0

    @property
    def average(self) -> float:
        return self.duty


class OccupancyCycle:
    """Occupancy-sensed switching: on for ``hold_s`` after each detection.

    ``interval_s`` is how often someone walks in. Brutal on lamps that hate being
    switched -- a corridor CFL on a five-minute occupancy hold can burn through its
    cycle budget in a year, which the lumen-maintenance model will show.
    """

    def __init__(
        self, interval_s: float = 1800.0, hold_s: float = 600.0, level: float = 1.0
    ) -> None:
        self.interval_s = max(interval_s, 1e-9)
        self.hold_s = hold_s
        self.level = max(0.0, min(1.0, level))

    def drive(self, t: float) -> float:
        return self.level if (t % self.interval_s) < self.hold_s else 0.0


class CallableDrive:
    """Wrap an arbitrary ``f(t) -> level`` as a profile."""

    def __init__(self, fn: Callable[[float], float]) -> None:
        self.fn = fn

    def drive(self, t: float) -> float:
        return max(0.0, min(1.0, self.fn(t)))


def sinusoidal(mean: float, amplitude: float, period_s: float) -> CallableDrive:
    """A gently varying drive level, e.g. a slow architectural fade."""
    return CallableDrive(
        lambda t: mean + amplitude * math.sin(2.0 * math.pi * t / period_s)
    )
