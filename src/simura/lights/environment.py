"""The one place weather and daylight meet a luminaire.

The :mod:`simura.weather` package is deliberately domain-agnostic. This module is
the lighting-specific translation -- the counterpart of
:mod:`simura.sim.environment` (batteries) and :mod:`simura.wires.environment`
(conductors) -- and it does rather more than either, because the environment
affects lighting through **two entirely separate channels**.

**Thermally**, weather changes what the lamp can do:

* *air temperature* sets the ambient the source cools toward. A hot night pushes
  an LED's junction up and its output down; a cold morning does the same to a
  fluorescent tube for the opposite reason (the mercury vapour pressure falls off
  its optimum). The two technologies fail in opposite directions, which is exactly
  why the choice between them depends on where the fitting is going.
* *wind* cools the luminaire, lowering the junction temperature and buying back
  output -- the one environmental effect that helps.
* *solar irradiance* warms the housing, working against the heatsink.

**Optically**, weather changes what the lamp is *needed for*. Sunlight already
falling on the task is light the fitting does not have to supply, and that is the
basis of every daylight-linked control ever installed::

    E_daylight = GHI * K_daylight * transmission

with ``GHI`` the global horizontal irradiance the weather source reports and
``K_daylight ~ 110 lm/W`` the luminous efficacy of daylight. Indoors,
``transmission`` is the *daylight factor* -- a few percent, not the glazing's
transmission -- so a desk sees hundreds of lux on a day that is delivering tens
of thousands outside. Feed that into
:class:`DaylightHarvesting` and the lamp dims itself to hold a constant total
illuminance -- so the simulated energy saving is a *consequence* of real weather
at a real place, not an assumption.

Solar geometry (:func:`solar_elevation_deg`) and a clear-sky irradiance model
(:func:`clear_sky_ghi_w_m2`) are here too. They let a photocell work without any
weather source at all, and they give :mod:`simura.lights.validation` something to
check live measurements against.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Luminous efficacy of daylight: lumens per watt of global horizontal irradiance.
# Daylight is a broad ~5500-6500 K spectrum, so its efficacy of radiation sits near
# the blackbody maximum; averaged over sun and sky, 105-120 lm/W is the range
# commonly quoted, and 110 is the conventional single figure.
K_DAYLIGHT_LM_PER_W = 110.0

# Solar constant (W/m^2), the irradiance at the top of the atmosphere.
SOLAR_CONSTANT_W_M2 = 1361.0


# ---------------------------------------------------------------------------
# Solar geometry
# ---------------------------------------------------------------------------

def _fractional_year_rad(epoch_s: float) -> float:
    """Spencer's fractional-year angle for a Unix timestamp."""
    day_of_year = (epoch_s / 86400.0) % 365.2422
    return 2.0 * math.pi * day_of_year / 365.2422


def solar_declination_deg(epoch_s: float) -> float:
    """Declination of the sun, in degrees, via Spencer's Fourier series.

    Good to about 0.05 degrees, which is far below anything else here.
    """
    g = _fractional_year_rad(epoch_s)
    dec = (
        0.006918
        - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g) + 0.001480 * math.sin(3 * g)
    )
    return math.degrees(dec)


def equation_of_time_min(epoch_s: float) -> float:
    """The sun's disagreement with the clock, in minutes (Spencer's series)."""
    g = _fractional_year_rad(epoch_s)
    eot = (
        0.000075
        + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
        - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g)
    )
    return 229.18 * eot


def solar_elevation_deg(latitude: float, longitude: float, epoch_s: float) -> float:
    """Sun elevation above the horizon, in degrees (negative = below).

    Standard astronomical geometry from a Unix timestamp: declination and the
    equation of time give the sun's position, the hour angle gives the time of day
    at this longitude, and

        ``sin(h) = sin(lat)*sin(dec) + cos(lat)*cos(dec)*cos(HA)``

    gives the elevation. Everything daylight-related follows from this one number.
    """
    dec = math.radians(solar_declination_deg(epoch_s))
    lat = math.radians(latitude)

    utc_minutes = (epoch_s / 60.0) % 1440.0
    true_solar_min = utc_minutes + equation_of_time_min(epoch_s) + 4.0 * longitude
    hour_angle = math.radians(true_solar_min / 4.0 - 180.0)

    sin_h = math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(hour_angle)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_h))))


def clear_sky_ghi_w_m2(elevation_deg: float) -> float:
    """Clear-sky global horizontal irradiance for a sun elevation, in W/m^2.

    The Haurwitz model: ``GHI = 1098 * sin(h) * exp(-0.059 / sin(h))``. One of the
    oldest and simplest clear-sky models, with no inputs but the sun's elevation --
    which is what makes it useful as a *reference*: any gap between it and a
    measured irradiance is atmosphere, not fitted parameters.

    Returns 0 when the sun is down.
    """
    sin_h = math.sin(math.radians(elevation_deg))
    if sin_h <= 0.0:
        return 0.0
    return 1098.0 * sin_h * math.exp(-0.059 / sin_h)


def daylight_illuminance_lux(
    irradiance_w_m2: float,
    transmission: float = 1.0,
    efficacy_lm_per_w: float = K_DAYLIGHT_LM_PER_W,
) -> float:
    """Convert global horizontal irradiance to illuminance on a horizontal plane.

    ``transmission`` is everything standing between the sky and the task.

    Outdoors it is 1.0. **Indoors it is the daylight factor, and it is far
    smaller than people expect**: not the glass's ~0.8 transmission, but the
    share of the *exterior horizontal* illuminance that reaches a desk, after the
    window's size relative to the room, its frame, the glazing, the dirt, and how
    far into the room the desk sits. Typical values are 0.02-0.05 for an
    ordinary perimeter workspace, up to ~0.10 right beside a large window.

    That distinction matters. A bright day is 80 klx outside; putting 0.35 here
    would claim 28 klx on the desk, which is fifty times what a real room sees
    and would make any daylight-linked control look miraculous.
    """
    return max(0.0, irradiance_w_m2) * efficacy_lm_per_w * max(0.0, transmission)


# ---------------------------------------------------------------------------
# The coupling
# ---------------------------------------------------------------------------

@dataclass
class LightEnvironmentEffect:
    """What the environment does to the luminaire this step."""

    ambient_c: float                # the temperature the source cools toward
    cooling_mult: float = 1.0       # multiplies heat transfer away from the source
    solar_heat_w: float = 0.0       # sun falling on the housing
    daylight_lux: float = 0.0       # daylight already on the task surface


@dataclass
class LightEnvironmentCoupling:
    """Maps a weather sample onto a luminaire.

    Defaults model an outdoor fitting -- a street light or a floodlight -- fully
    exposed to sun and wind. For an indoor luminaire set ``outdoor=False``: the
    housing sees no sun and no wind, but the room's daylight still arrives through
    ``window_transmission``.
    """

    outdoor: bool = True
    wind_cooling_gain: float = 0.06        # +6% heat transfer per m/s of wind
    max_cooling_mult: float = 3.0
    solar_absorptivity: float = 0.6        # of the housing
    housing_area_m2: float = 0.05          # sun-facing area of the luminaire
    # Sky -> task. 1.0 outdoors; indoors this is the *daylight factor*, a few
    # percent, not the glazing's transmission. See daylight_illuminance_lux.
    window_transmission: float = 1.0
    daylight_efficacy_lm_per_w: float = K_DAYLIGHT_LM_PER_W

    def apply(self, sample) -> LightEnvironmentEffect:  # noqa: ANN001
        """Translate one weather sample into its effect on the luminaire."""
        ambient = float(getattr(sample, "air_temp_c", 25.0))
        irradiance = max(0.0, float(getattr(sample, "solar_w_m2", 0.0)))

        cooling = 1.0
        solar_heat = 0.0
        if self.outdoor:
            wind = max(0.0, float(getattr(sample, "wind_speed_ms", 0.0)))
            cooling = min(self.max_cooling_mult, 1.0 + self.wind_cooling_gain * wind)
            solar_heat = self.solar_absorptivity * irradiance * max(0.0, self.housing_area_m2)

        return LightEnvironmentEffect(
            ambient_c=ambient,
            cooling_mult=cooling,
            solar_heat_w=solar_heat,
            daylight_lux=daylight_illuminance_lux(
                irradiance, self.window_transmission, self.daylight_efficacy_lm_per_w
            ),
        )


def apply_to_effect(effect, env: LightEnvironmentEffect) -> None:
    """Merge a :class:`LightEnvironmentEffect` into an accumulated fault effect.

    Wind rides the thermal-resistance channel (more cooling is *less* resistance)
    and absorbed sun raises the ambient the source sees, so the lamp solver needs
    no new inputs. Ambient itself is passed separately.
    """
    if env.cooling_mult > 0:
        effect.thermal_resistance_mult /= env.cooling_mult


# ---------------------------------------------------------------------------
# Environment-driven control
# ---------------------------------------------------------------------------

class PhotocellControl:
    """Dusk-to-dawn switching: on whenever daylight falls below a threshold.

    The control on essentially every outdoor light in the world, and the reason
    street lighting energy is a function of latitude and season rather than of a
    timeclock. ``switch_on_lux`` around 50-70 lux is the usual setting; the
    hysteresis band stops it chattering at dusk.
    """

    def __init__(
        self, switch_on_lux: float = 55.0, hysteresis_frac: float = 1.6, level: float = 1.0
    ) -> None:
        self.switch_on_lux = switch_on_lux
        self.switch_off_lux = switch_on_lux * max(1.0, hysteresis_frac)
        self.level = max(0.0, min(1.0, level))
        self._on = False

    def drive_for(self, daylight_lux: float) -> float:
        if self._on and daylight_lux > self.switch_off_lux:
            self._on = False
        elif not self._on and daylight_lux < self.switch_on_lux:
            self._on = True
        return self.level if self._on else 0.0


class DaylightHarvesting:
    """Dim to hold a constant *total* illuminance, counting the daylight.

    The control that actually saves energy in a daylit building: the fitting
    supplies only the difference between the target and what the sky is already
    delivering. With a real weather source behind it, the simulated saving is a
    consequence of the actual sky over an actual place -- which is the whole point
    of coupling a lighting twin to weather at all.

    ``full_output_lux`` is what the installation delivers at full drive; the
    controller assumes output is proportional to drive, which is close enough for
    everything but a filament lamp (whose efficacy collapses as it dims, so it
    under-delivers -- a real and instructive failure of naive daylight linking).
    """

    def __init__(
        self,
        target_lux: float = 500.0,
        full_output_lux: float = 500.0,
        min_level: float = 0.0,
        max_level: float = 1.0,
    ) -> None:
        self.target_lux = target_lux
        self.full_output_lux = max(full_output_lux, 1e-9)
        self.min_level = max(0.0, min_level)
        self.max_level = min(1.0, max_level)

    def drive_for(self, daylight_lux: float) -> float:
        deficit = self.target_lux - max(0.0, daylight_lux)
        if deficit <= 0.0:
            return self.min_level
        return max(self.min_level, min(self.max_level, deficit / self.full_output_lux))
