"""The light simulator: drives a luminaire through a profile, weather and faults.

A generator at heart -- ``run()`` yields one :class:`LightTelemetry` per timestep
-- so the same code can feed a plot, an ageing study, or an MQTT publisher without
change. Mirrors :class:`simura.sim.simulator.Simulator` and
:class:`simura.wires.simulator.WireSimulator`.

What makes a lighting run interesting over time, rather than a single operating
point repeated:

* **warm-up and restrike** -- a discharge lamp is not at full output for minutes
  after it strikes, and will not restrike at all until it has cooled;
* **the thermal transient** -- an LED is measurably brighter in its first minute
  than after an hour, because the junction is still cold;
* **ageing** -- run it long enough (or with ``speed`` turned up) and lumen
  depreciation and switch-cycle wear become the story;
* **weather** -- with a provider attached, the ambient, the wind and the daylight
  all move, and with a daylight-linked control the lamp answers them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterator, Optional

from .environment import (
    DaylightHarvesting,
    LightEnvironmentCoupling,
    PhotocellControl,
    apply_to_effect,
)
from .faults import Fault, accumulate
from .lamp import Light, LightSpec
from .photometry import point_illuminance_lux
from .profiles import DriveProfile
from .telemetry import LightTelemetry, snapshot


@dataclass
class LightSimConfig:
    """Simulation loop settings."""

    dt_s: float = 1.0
    duration_s: float = 3600.0
    # Where illuminance is reported: directly under the lamp at this height, on a
    # horizontal surface. Left at 0 the frame reports 0 lux and only flux matters.
    mounting_height_m: float = 3.0
    target_lux: float = 0.0
    # Ageing accelerator: how many hours of lamp life pass per simulated second.
    # Left at 0 the lamp ages in real time (1 s of simulation = 1 s of life).
    hours_per_second: float = 0.0


class LightSimulator:
    """Runs one luminaire through time."""

    def __init__(
        self,
        spec: LightSpec | None = None,
        sim_config: LightSimConfig | None = None,
        profile: DriveProfile | None = None,
        faults: list[Fault] | None = None,
        weather=None,
        coupling: LightEnvironmentCoupling | None = None,
        weather_epoch0: float | None = None,
        control: Optional[PhotocellControl | DaylightHarvesting] = None,
    ) -> None:
        self.light = Light(spec or LightSpec(lamp_type="led-9-e27"))
        self.sim = sim_config or LightSimConfig()
        self.profile = profile
        self.faults = faults or []
        self.t = 0.0
        # Optional environmental coupling. ``weather`` is any object with an
        # ``at(epoch_seconds) -> WeatherSample`` method (a WeatherProvider), the
        # same seam the battery and wire simulators use.
        self.weather = weather
        self.coupling = coupling or LightEnvironmentCoupling()
        self.weather_epoch0 = weather_epoch0
        # An environment-driven control overrides the time profile when the
        # daylight is known: a photocell or a daylight-harvesting dimmer.
        self.control = control

    def run(self) -> Iterator[LightTelemetry]:
        """Yield telemetry once per timestep until ``duration_s`` is reached."""
        if self.profile is None and self.control is None:
            raise ValueError("LightSimulator needs a drive profile or a control.")

        epoch0 = self.weather_epoch0 if self.weather_epoch0 is not None else time.time()
        n_steps = int(self.sim.duration_s / self.sim.dt_s)
        for _ in range(n_steps):
            effect = accumulate(self.faults, self.light, self.t)

            sample = None
            ambient_c = None
            daylight_lux = None
            if self.weather is not None:
                sample = self.weather.at(epoch0 + self.t)
                env = self.coupling.apply(sample)
                apply_to_effect(effect, env)
                # Absorbed sunlight arrives as a warmer effective ambient for the
                # housing, which is how it reaches the source.
                ambient_c = env.ambient_c + env.solar_heat_w * self.light.r_th
                daylight_lux = env.daylight_lux

            drive = self._drive(daylight_lux)
            point = self.light.step(drive, self.sim.dt_s, ambient_c=ambient_c, effect=effect)

            # Age the lamp faster than real time, if asked.
            if self.sim.hours_per_second > 0 and point.lit:
                self.light.operating_hours_h += (
                    self.sim.hours_per_second * self.sim.dt_s
                    - self.sim.dt_s / 3600.0    # step() already added real time
                )

            lux = 0.0
            if self.sim.mounting_height_m > 0:
                lux = point_illuminance_lux(
                    point.luminous_flux_lm,
                    self.light.beam_angle_deg,
                    self.sim.mounting_height_m,
                )
            total_lux = lux + (daylight_lux or 0.0)

            self.t += self.sim.dt_s
            yield snapshot(
                self.light,
                self.t,
                drive,
                point,
                illuminance_lux=total_lux,
                target_lux=self.sim.target_lux,
                weather=sample,
                daylight_lux=daylight_lux,
            )

    def _drive(self, daylight_lux: float | None) -> float:
        """The commanded level this step, from the profile and the control together.

        Real installations layer the two: a timeclock or occupancy sensor decides
        *whether* the lights are on, and a daylight sensor decides *how bright*.
        So the two multiply -- an office on a 7-to-7 schedule with daylight
        harvesting is dark at night and dim at noon, which neither alone would
        give. With only one present, that one governs.
        """
        level = self.profile.drive(self.t) if self.profile is not None else 1.0
        if self.control is not None and daylight_lux is not None:
            level *= self.control.drive_for(daylight_lux)
        return level

    def run_to_list(self) -> list[LightTelemetry]:
        """Convenience: collect the whole run into a list."""
        return list(self.run())
