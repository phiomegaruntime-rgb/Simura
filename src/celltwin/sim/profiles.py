"""Load profiles: how the pack is charged and discharged over time.

A profile maps simulated time (seconds) and the current pack voltage to a
requested **pack current** in amps (positive = discharge). Passing voltage in
lets us express constant-*power* duty cycles -- the usual way grid and EV loads
are specified -- as ``I = P / V``.
"""

from __future__ import annotations

import math
from typing import Callable, Protocol


class LoadProfile(Protocol):
    def current(self, t: float, pack_voltage_v: float) -> float: ...


class ConstantCurrent:
    """Steady discharge (or charge, if negative) at a fixed amperage."""

    def __init__(self, amps: float) -> None:
        self.amps = amps

    def current(self, t: float, pack_voltage_v: float) -> float:
        return self.amps


class ConstantPower:
    """Constant-power load, converted to current using the present voltage."""

    def __init__(self, watts: float) -> None:
        self.watts = watts

    def current(self, t: float, pack_voltage_v: float) -> float:
        if pack_voltage_v <= 0:
            return 0.0
        return self.watts / pack_voltage_v


class ChargeDischargeCycle:
    """Symmetric duty cycle: discharge for a while, rest, charge, rest, repeat.

    A compact stand-in for the daily cycling a grid BESS actually sees -- and the
    kind of repeated stress that surfaces degradation over many cycles.
    """

    def __init__(
        self,
        discharge_a: float = 10.0,
        charge_a: float = 10.0,
        discharge_s: float = 1200.0,
        charge_s: float = 1200.0,
        rest_s: float = 300.0,
    ) -> None:
        self.discharge_a = discharge_a
        self.charge_a = charge_a
        self.d = discharge_s
        self.c = charge_s
        self.rest = rest_s
        self.period = discharge_s + rest_s + charge_s + rest_s

    def current(self, t: float, pack_voltage_v: float) -> float:
        phase = t % self.period
        if phase < self.d:
            return self.discharge_a
        phase -= self.d
        if phase < self.rest:
            return 0.0
        phase -= self.rest
        if phase < self.c:
            return -self.charge_a
        return 0.0


class Callable_:
    """Wrap an arbitrary ``f(t, v) -> amps`` as a profile."""

    def __init__(self, fn: Callable[[float, float], float]) -> None:
        self.fn = fn

    def current(self, t: float, pack_voltage_v: float) -> float:
        return self.fn(t, pack_voltage_v)


def sinusoidal(mean_a: float, amplitude_a: float, period_s: float) -> Callable_:
    """A gently varying load, e.g. to mimic fluctuating grid demand."""
    return Callable_(lambda t, v: mean_a + amplitude_a * math.sin(2 * math.pi * t / period_s))
