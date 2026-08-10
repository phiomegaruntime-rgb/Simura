"""The one place weather meets a conductor.

The :mod:`simura.weather` package is deliberately domain-agnostic. This module is
the wire-specific translation -- the conductor analog of
:mod:`simura.sim.environment` -- mapping a
:class:`~simura.weather.sample.WeatherSample` onto the three environmental levers
the wire's thermal model already exposes:

* **air temperature** -> the ambient the conductor cools toward (``T_amb``),
* **wind speed**       -> a multiplier on convective cooling (``k_cool``),
* **solar irradiance** -> an added heat load on the sun-facing surface (``extra_heat_w``).

This is the standard conductor heat balance (cf. IEEE Std 738 / dynamic line
rating): forced convection carries heat away as the wind rises, absorbed sunlight
adds it back, and everything happens relative to the ambient air. The coefficients
are *illustrative* -- a plausible bare/insulated outdoor run, not a calibrated
model -- exactly like the nominal ``k_cool`` and the catalog ampacities elsewhere.
They are constructor parameters so a specific installation can tune them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WireEnvironmentEffect:
    """What the weather does to the conductor this step (parallels ``FaultEffect``)."""

    ambient_c: float                 # ambient temperature the conductor cools toward
    cooling_mult: float = 1.0        # multiplies k_cool (wind-driven convection)
    solar_heat_w: float = 0.0        # added heat from absorbed sunlight


@dataclass
class WireEnvironmentCoupling:
    """Maps weather to a :class:`WireEnvironmentEffect` for a conductor.

    Defaults model a modestly exposed outdoor run. A conductor is far more
    wind-sensitive than an enclosed battery cabinet -- forced convection dominates
    its cooling -- so the wind gain is larger here than in
    :class:`simura.sim.environment.EnvironmentCoupling`. Tune per installation
    (set ``shading_frac=1`` for a fully shaded/indoor run to drop solar gain).
    """

    wind_cooling_gain: float = 0.15       # +15% convective cooling per m/s of wind
    max_cooling_mult: float = 6.0         # cap the wind benefit
    solar_absorptivity: float = 0.5       # fraction of irradiance absorbed (weathered conductor)
    shading_frac: float = 0.0             # 0 = fully exposed to sun, 1 = fully shaded

    def apply(self, sample, projected_area_m2: float = 0.0) -> WireEnvironmentEffect:  # noqa: ANN001
        """Translate one weather sample into its effect on the conductor.

        ``projected_area_m2`` is the sun-facing silhouette of the run (a cylinder's
        ``diameter * length``); the simulator supplies it from the wire geometry.
        Left at 0 (e.g. calling this standalone) there is simply no solar gain.
        """
        wind = max(0.0, float(getattr(sample, "wind_speed_ms", 0.0)))
        cooling = 1.0 + self.wind_cooling_gain * wind
        cooling = min(self.max_cooling_mult, max(1.0, cooling))

        irradiance = max(0.0, float(getattr(sample, "solar_w_m2", 0.0)))
        solar_w = (
            self.solar_absorptivity
            * (1.0 - self.shading_frac)
            * irradiance
            * max(0.0, projected_area_m2)
        )

        return WireEnvironmentEffect(
            ambient_c=float(sample.air_temp_c),
            cooling_mult=cooling,
            solar_heat_w=solar_w,
        )


def apply_to_effect(effect, env: WireEnvironmentEffect) -> None:
    """Merge a :class:`WireEnvironmentEffect` into an accumulated ``FaultEffect``.

    Wind rides the ``cooling_mult`` channel and solar the ``extra_heat_w`` channel,
    so :meth:`Wire.step` needs no new inputs -- only the ambient temperature is
    passed to it separately.
    """
    effect.cooling_mult = effect.cooling_mult * env.cooling_mult
    effect.extra_heat_w = effect.extra_heat_w + env.solar_heat_w
