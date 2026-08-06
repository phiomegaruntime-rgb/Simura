"""The one place weather meets the battery.

The :mod:`celltwin.weather` package is deliberately battery-agnostic. This module
is the thin, battery-specific translation: it maps a
:class:`~celltwin.weather.sample.WeatherSample` onto the three environmental
levers the pack's thermal model already exposes --

* **air temperature** -> the ambient the pack cools toward (``T_amb``),
* **wind speed**       -> a multiplier on convective cooling conductance (``k_cool``),
* **solar irradiance** -> an added heat load on each exposed cell (``extra_heat_w``).

The coefficients are *illustrative* -- a plausible generic outdoor enclosure, not
a calibrated CFD model -- exactly like the nominal ``k_cool`` and the OCV tables
elsewhere in the simulator. They are all constructor parameters so a specific
deployment can tune them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EnvironmentEffect:
    """What the weather does to the pack this step (parallels ``FaultEffect``)."""

    ambient_c: float                 # ambient temperature the pack cools toward
    cooling_mult: float = 1.0        # multiplies k_cool (wind-driven convection)
    solar_heat_w: float = 0.0        # added heat per cell from absorbed sunlight


@dataclass
class EnvironmentCoupling:
    """Maps weather to an :class:`EnvironmentEffect` for a battery enclosure.

    Defaults model a modestly ventilated outdoor cabinet. Tune per deployment.
    """

    wind_cooling_gain: float = 0.05       # +5% convective cooling per m/s of wind
    max_cooling_mult: float = 3.0         # cap the wind benefit
    solar_absorptivity: float = 0.6       # fraction of irradiance reaching a cell
    exposed_area_m2_per_cell: float = 0.004  # sun-facing area attributable per cell
    shading_frac: float = 0.0             # 0 = fully exposed, 1 = fully shaded

    def apply(self, sample) -> EnvironmentEffect:  # noqa: ANN001 (duck-typed WeatherSample)
        """Translate one weather sample into its effect on the pack."""
        wind = max(0.0, float(getattr(sample, "wind_speed_ms", 0.0)))
        cooling = 1.0 + self.wind_cooling_gain * wind
        cooling = min(self.max_cooling_mult, max(1.0, cooling))

        irradiance = max(0.0, float(getattr(sample, "solar_w_m2", 0.0)))
        solar_w = (
            self.solar_absorptivity
            * (1.0 - self.shading_frac)
            * irradiance
            * self.exposed_area_m2_per_cell
        )

        return EnvironmentEffect(
            ambient_c=float(sample.air_temp_c),
            cooling_mult=cooling,
            solar_heat_w=solar_w,
        )


def apply_to_effect(effect, env: EnvironmentEffect) -> None:
    """Merge an :class:`EnvironmentEffect` into an accumulated ``FaultEffect``.

    Wind rides the existing ``cooling_mult`` channel and solar the ``extra_heat_w``
    channel, so the integrator needs no new inputs -- only the ambient temperature
    is passed to :meth:`BatteryPack.step` separately.
    """
    effect.cooling_mult = effect.cooling_mult * env.cooling_mult
    effect.extra_heat_w = effect.extra_heat_w + env.solar_heat_w
