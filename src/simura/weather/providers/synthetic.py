"""A deterministic, offline synthetic-weather model.

This is the workhorse for tests, CI, and offline demos: it never touches the
network, yet produces a physically plausible *diurnal* cycle -- air temperature
peaking in the afternoon, solar irradiance rising and falling with the sun and
zero at night, and mild wind variation. Being a pure function of the timestamp
(plus a seed for the wind noise) it is fully reproducible.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from ..sample import WeatherSample

SECONDS_PER_DAY = 86_400.0


class SyntheticProvider:
    """A smooth diurnal weather cycle derived analytically from the timestamp.

    ``tz_offset_h`` shifts the local solar clock so that solar noon (peak
    irradiance) and the mid-afternoon temperature peak land at sensible local
    hours for the modelled location. ``seed`` makes the small hour-to-hour wind
    variation reproducible.
    """

    def __init__(
        self,
        mean_temp_c: float = 20.0,
        temp_amplitude_c: float = 8.0,
        solar_peak_w_m2: float = 800.0,
        wind_mean_ms: float = 3.0,
        wind_amplitude_ms: float = 2.0,
        humidity_frac: float = 0.5,
        tz_offset_h: float = 0.0,
        seed: int = 0,
    ) -> None:
        self.mean_temp_c = mean_temp_c
        self.temp_amplitude_c = temp_amplitude_c
        self.solar_peak_w_m2 = solar_peak_w_m2
        self.wind_mean_ms = wind_mean_ms
        self.wind_amplitude_ms = wind_amplitude_ms
        self.humidity_frac = humidity_frac
        self.tz_offset_h = tz_offset_h
        self.seed = seed

    def _local_hour(self, timestamp: float) -> float:
        """Local hour-of-day in [0, 24), applying the timezone offset."""
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        h = dt.hour + dt.minute / 60.0 + dt.second / 3600.0 + self.tz_offset_h
        return h % 24.0

    def at(self, timestamp: float) -> WeatherSample:
        h = self._local_hour(timestamp)

        # Temperature: sinusoid with its minimum near dawn (~05:00) and peak in
        # the mid-afternoon (~15:00). Shift the cosine so trough sits at 05:00.
        temp = self.mean_temp_c - self.temp_amplitude_c * math.cos(
            2.0 * math.pi * (h - 5.0) / 24.0
        )

        # Solar: a half-sine over daylight (06:00..18:00), zero at night, peak at
        # local solar noon.
        if 6.0 <= h <= 18.0:
            solar = self.solar_peak_w_m2 * math.sin(math.pi * (h - 6.0) / 12.0)
        else:
            solar = 0.0

        # Wind: mean plus a smooth, seeded per-hour perturbation (deterministic).
        day_index = math.floor(timestamp / SECONDS_PER_DAY)
        phase = (self.seed * 2654435761 + day_index) % 997 / 997.0
        wind = self.wind_mean_ms + self.wind_amplitude_ms * math.sin(
            2.0 * math.pi * (h / 24.0 + phase)
        )
        wind = max(0.0, wind)

        return WeatherSample(
            timestamp=timestamp,
            air_temp_c=round(temp, 3),
            wind_speed_ms=round(wind, 3),
            solar_w_m2=round(solar, 1),
            humidity_frac=self.humidity_frac,
            source="synthetic",
        )
