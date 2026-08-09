"""Fault-injection framework.

Faults are what turn a battery *model* into a battery *twin* worth exploring:
they let you reproduce the exact degradation and safety events that predictive
maintenance is supposed to catch -- on demand, reproducibly, without setting
anything on fire.

Design
------
Every fault contributes to a shared :class:`FaultEffect` accumulator each
timestep. The pack applies the accumulated effect uniformly, so faults compose
(you can run a cooling failure *and* an internal short together) and new fault
types never require changes to the integrator. A fault targets a cell by its
``(series_index, parallel_index)`` position; ``None`` means "all cells".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class FaultEffect:
    """Per-cell accumulator applied by the pack each timestep.

    Shapes are ``(series, parallel)``. Multiplicative fields start at 1.0 and
    additive fields at 0.0 so that "no fault" is the identity.
    """

    resistance_mult: np.ndarray       # scales R0 (e.g. resistance growth)
    cooling_mult: np.ndarray          # scales cooling conductance (e.g. fan loss)
    extra_current_a: np.ndarray       # parasitic drain, A (e.g. internal short)
    extra_heat_w: np.ndarray          # exothermic heat, W (e.g. runaway)
    # Telemetry-only biases (added to reported values, do not affect physics).
    voltage_bias_v: np.ndarray
    temp_bias_c: np.ndarray

    @classmethod
    def zeros(cls, shape: tuple[int, int]) -> "FaultEffect":
        return cls(
            resistance_mult=np.ones(shape),
            cooling_mult=np.ones(shape),
            extra_current_a=np.zeros(shape),
            extra_heat_w=np.zeros(shape),
            voltage_bias_v=np.zeros(shape),
            temp_bias_c=np.zeros(shape),
        )


class Fault:
    """Base class. A fault is active in the half-open window [start_s, end_s)."""

    name: str = "fault"

    def __init__(
        self,
        cell: Optional[tuple[int, int]] = None,
        start_s: float = 0.0,
        end_s: float = float("inf"),
    ) -> None:
        self.cell = cell
        self.start_s = start_s
        self.end_s = end_s

    def is_active(self, t: float) -> bool:
        return self.start_s <= t < self.end_s

    def _mask(self, effect: FaultEffect) -> tuple:
        """Index selecting the targeted cell(s) within an effect array."""
        if self.cell is None:
            return (slice(None), slice(None))
        return self.cell

    def apply(self, effect: FaultEffect, pack, t: float) -> None:  # noqa: ANN001
        """Contribute to the accumulated effect. Override in subclasses.

        ``pack`` is passed read-only so faults can depend on live state (a
        thermal runaway that feeds back on temperature, for example).
        """
        raise NotImplementedError


class ResistanceGrowth(Fault):
    """Elevated internal resistance -- the classic aging / connector-fault signature."""

    name = "resistance_growth"

    def __init__(self, multiplier: float = 2.0, **kw) -> None:
        super().__init__(**kw)
        self.multiplier = multiplier

    def apply(self, effect: FaultEffect, pack, t: float) -> None:  # noqa: ANN001
        effect.resistance_mult[self._mask(effect)] *= self.multiplier


class InternalShort(Fault):
    """Soft internal short: a resistive path that self-discharges and heats a cell.

    Modeled as a parasitic current ``i = OCV / r_short`` drawn from the cell,
    dissipating ``OCV * i`` watts of heat locally. Smaller ``r_short`` => more
    severe. This is the seed condition that can precede thermal runaway.
    """

    name = "internal_short"

    def __init__(self, r_short_ohm: float = 5.0, **kw) -> None:
        super().__init__(**kw)
        self.r_short_ohm = r_short_ohm

    def apply(self, effect: FaultEffect, pack, t: float) -> None:  # noqa: ANN001
        idx = self._mask(effect)
        ocv = pack.ocv(pack.soc)[idx]
        i_short = ocv / self.r_short_ohm
        effect.extra_current_a[idx] += i_short
        effect.extra_heat_w[idx] += ocv * i_short


class CoolingFault(Fault):
    """Degraded heat rejection (blocked airflow, failed fan, coolant loss)."""

    name = "cooling_fault"

    def __init__(self, effectiveness: float = 0.3, **kw) -> None:
        super().__init__(**kw)
        self.effectiveness = effectiveness  # remaining fraction of cooling

    def apply(self, effect: FaultEffect, pack, t: float) -> None:  # noqa: ANN001
        effect.cooling_mult[self._mask(effect)] *= self.effectiveness


class ThermalRunaway(Fault):
    """Exothermic runaway that ignites once a cell crosses ``trigger_c``.

    Above the trigger, self-heating grows exponentially with temperature, the
    hallmark of thermal runaway. Pair it with an :class:`InternalShort` or
    :class:`CoolingFault` to reproduce a realistic cause-and-effect sequence.
    """

    name = "thermal_runaway"

    def __init__(
        self, trigger_c: float = 80.0, scale_w: float = 5.0, temp_slope_c: float = 15.0, **kw
    ) -> None:
        super().__init__(**kw)
        self.trigger_c = trigger_c
        self.scale_w = scale_w
        self.temp_slope_c = temp_slope_c

    def apply(self, effect: FaultEffect, pack, t: float) -> None:  # noqa: ANN001
        idx = self._mask(effect)
        temp = pack.temp_c[idx]
        over = temp - self.trigger_c
        heat = np.where(over > 0, self.scale_w * np.exp(over / self.temp_slope_c), 0.0)
        effect.extra_heat_w[idx] += heat


class SensorDrift(Fault):
    """A drifting/failing sensor: biases *reported* telemetry, not the physics.

    Useful for building diagnostics that must distinguish a genuine fault from a
    lying sensor -- a real and underappreciated failure mode in the field.
    """

    name = "sensor_drift"

    def __init__(
        self, signal: str = "voltage", rate_per_s: float = 0.0, offset: float = 0.0, **kw
    ) -> None:
        super().__init__(**kw)
        if signal not in ("voltage", "temp"):
            raise ValueError("signal must be 'voltage' or 'temp'")
        self.signal = signal
        self.rate_per_s = rate_per_s
        self.offset = offset

    def apply(self, effect: FaultEffect, pack, t: float) -> None:  # noqa: ANN001
        bias = self.offset + self.rate_per_s * (t - self.start_s)
        target = effect.voltage_bias_v if self.signal == "voltage" else effect.temp_bias_c
        target[self._mask(effect)] += bias


def accumulate(faults: list[Fault], pack, t: float) -> FaultEffect:
    """Build the combined :class:`FaultEffect` from all faults active at time ``t``."""
    effect = FaultEffect.zeros(pack.shape)
    for f in faults:
        if f.is_active(t):
            f.apply(effect, pack, t)
    return effect
