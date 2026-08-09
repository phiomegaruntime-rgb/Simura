"""A constant-weather provider.

The identity element of the package: it makes "no weather variation" just another
provider, so a caller never needs a special no-weather code path. Equivalent to
the simulator's historical fixed ``ambient_temp_c``.
"""

from __future__ import annotations

from ..sample import WeatherSample


class StaticProvider:
    """Always returns the same conditions, regardless of time."""

    def __init__(
        self,
        air_temp_c: float = 25.0,
        wind_speed_ms: float = 0.0,
        solar_w_m2: float = 0.0,
        humidity_frac: float | None = None,
    ) -> None:
        self.air_temp_c = air_temp_c
        self.wind_speed_ms = wind_speed_ms
        self.solar_w_m2 = solar_w_m2
        self.humidity_frac = humidity_frac

    def at(self, timestamp: float) -> WeatherSample:
        return WeatherSample(
            timestamp=timestamp,
            air_temp_c=self.air_temp_c,
            wind_speed_ms=self.wind_speed_ms,
            solar_w_m2=self.solar_w_m2,
            humidity_frac=self.humidity_frac,
            source="static",
        )
