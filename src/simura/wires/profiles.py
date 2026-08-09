"""Current profiles: how the load through a wire varies over time.

Domain-neutral by design -- a profile maps simulated time (seconds) to a current
in amps, and knows nothing about batteries. This mirrors
:mod:`simura.sim.profiles` but is deliberately simpler (no voltage argument):
a wire just carries whatever current the circuit puts through it.
"""

from __future__ import annotations

import math
from typing import Callable, Protocol


class CurrentProfile(Protocol):
    def current(self, t: float) -> float: ...


class ConstantCurrent:
    """Steady current at a fixed amperage."""

    def __init__(self, amps: float) -> None:
        self.amps = amps

    def current(self, t: float) -> float:
        return self.amps


class StepCurrent:
    """A single step: ``low`` before ``step_s``, ``high`` after."""

    def __init__(self, low_a: float, high_a: float, step_s: float) -> None:
        self.low_a = low_a
        self.high_a = high_a
        self.step_s = step_s

    def current(self, t: float) -> float:
        return self.high_a if t >= self.step_s else self.low_a


class DutyCycle:
    """On/off cycling: ``on_a`` for ``on_s``, then ``off_a`` for ``off_s``, repeat."""

    def __init__(self, on_a: float, off_a: float = 0.0, on_s: float = 60.0, off_s: float = 60.0) -> None:
        self.on_a = on_a
        self.off_a = off_a
        self.on_s = on_s
        self.off_s = off_s
        self.period = on_s + off_s

    def current(self, t: float) -> float:
        return self.on_a if (t % self.period) < self.on_s else self.off_a


class Callable_:
    """Wrap an arbitrary ``f(t) -> amps`` as a profile."""

    def __init__(self, fn: Callable[[float], float]) -> None:
        self.fn = fn

    def current(self, t: float) -> float:
        return self.fn(t)


def sinusoidal(mean_a: float, amplitude_a: float, period_s: float) -> Callable_:
    """A gently varying current, e.g. a fluctuating load."""
    return Callable_(lambda t: mean_a + amplitude_a * math.sin(2 * math.pi * t / period_s))
