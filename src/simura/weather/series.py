"""A tiny time-indexed sample series with linear interpolation.

Shared by the providers that hold a set of discrete samples (a replayed CSV, a
batch fetched from an API) and need to answer :meth:`WeatherProvider.at` for an
arbitrary instant. Pure standard library -- no numpy -- so the package stays
dependency-free and trivially extractable.
"""

from __future__ import annotations

import bisect

from .sample import WeatherSample


class WeatherSeries:
    """An ordered list of samples that interpolates between them by timestamp."""

    def __init__(self, samples: list[WeatherSample]) -> None:
        if not samples:
            raise ValueError("WeatherSeries needs at least one sample")
        self._samples = sorted(samples, key=lambda s: s.timestamp)
        self._times = [s.timestamp for s in self._samples]

    def __len__(self) -> int:
        return len(self._samples)

    @property
    def start(self) -> float:
        return self._times[0]

    @property
    def end(self) -> float:
        return self._times[-1]

    def covers(self, timestamp: float) -> bool:
        return self._times[0] <= timestamp <= self._times[-1]

    def at(self, timestamp: float) -> WeatherSample:
        """Linear interpolation, clamped at the ends (nearest sample outside range)."""
        i = bisect.bisect_left(self._times, timestamp)
        if i <= 0:
            return self._samples[0]
        if i >= len(self._samples):
            return self._samples[-1]
        lo = self._samples[i - 1]
        hi = self._samples[i]
        span = hi.timestamp - lo.timestamp
        frac = 0.0 if span <= 0 else (timestamp - lo.timestamp) / span
        return WeatherSample(
            timestamp=timestamp,
            air_temp_c=_lerp(lo.air_temp_c, hi.air_temp_c, frac),
            wind_speed_ms=_lerp(lo.wind_speed_ms, hi.wind_speed_ms, frac),
            solar_w_m2=_lerp(lo.solar_w_m2, hi.solar_w_m2, frac),
            humidity_frac=_lerp_opt(lo.humidity_frac, hi.humidity_frac, frac),
            source=lo.source or hi.source,
        )


def _lerp(a: float, b: float, frac: float) -> float:
    return a + (b - a) * frac


def _lerp_opt(a: float | None, b: float | None, frac: float) -> float | None:
    if a is None or b is None:
        return a if b is None else b
    return _lerp(a, b, frac)
