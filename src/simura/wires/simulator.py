"""The wire simulator: drives a conductor through a current profile with faults.

A generator at heart -- ``run()`` yields one :class:`WireTelemetry` per timestep --
so the same code can feed a plot, a transient-heating study, or (later) an MQTT
publisher without change. Mirrors :class:`simura.sim.simulator.Simulator`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterator

from .environment import WireEnvironmentCoupling, apply_to_effect
from .faults import Fault, accumulate
from .profiles import CurrentProfile
from .telemetry import WireTelemetry, snapshot
from .wire import Wire, WireSpec


@dataclass
class WireSimConfig:
    """Simulation loop settings."""

    dt_s: float = 1.0
    duration_s: float = 600.0


class WireSimulator:
    def __init__(
        self,
        spec: WireSpec | None = None,
        sim_config: WireSimConfig | None = None,
        profile: CurrentProfile | None = None,
        faults: list[Fault] | None = None,
        weather=None,
        coupling: WireEnvironmentCoupling | None = None,
        weather_epoch0: float | None = None,
    ) -> None:
        self.wire = Wire(spec or WireSpec(awg=12, length_m=1.0))
        self.sim = sim_config or WireSimConfig()
        self.profile = profile
        self.faults = faults or []
        self.t = 0.0
        # Optional environmental coupling. ``weather`` is any object with an
        # ``at(epoch_seconds) -> WeatherSample`` method (a WeatherProvider), the
        # same seam the battery Simulator uses.
        self.weather = weather
        self.coupling = coupling or WireEnvironmentCoupling()
        self.weather_epoch0 = weather_epoch0
        # Sun-facing silhouette of the run (a cylinder's diameter * length).
        self._projected_area_m2 = self.wire.diameter_m * self.wire.length_m

    def run(self) -> Iterator[WireTelemetry]:
        """Yield telemetry once per timestep until ``duration_s`` is reached."""
        if self.profile is None:
            raise ValueError("WireSimulator needs a current profile to run.")

        epoch0 = self.weather_epoch0 if self.weather_epoch0 is not None else time.time()
        n_steps = int(self.sim.duration_s / self.sim.dt_s)
        for _ in range(n_steps):
            current = self.profile.current(self.t)
            effect = accumulate(self.faults, self.wire, self.t)

            sample = None
            ambient_c = None
            if self.weather is not None:
                sample = self.weather.at(epoch0 + self.t)
                env = self.coupling.apply(sample, self._projected_area_m2)
                # Wind cooling + solar heat ride the existing effect channels.
                apply_to_effect(effect, env)
                ambient_c = env.ambient_c

            self.wire.step(current, self.sim.dt_s, ambient_c=ambient_c, effect=effect)
            self.t += self.sim.dt_s
            yield snapshot(self.wire, self.t, current, effect=effect, weather=sample)

    def run_to_list(self) -> list[WireTelemetry]:
        """Convenience: collect the whole run into a list."""
        return list(self.run())
