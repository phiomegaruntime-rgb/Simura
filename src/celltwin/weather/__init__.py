"""Reusable, domain-agnostic weather providers.

This subpackage knows nothing about batteries -- it only produces
:class:`WeatherSample` values through a small :class:`WeatherProvider` interface.
That independence is deliberate: it can be lifted, unchanged, into any project
where the environment drives a system's behaviour. Within CellTwin, the
battery-specific translation lives in :mod:`celltwin.sim.environment`.

    from celltwin.weather import SyntheticProvider
    wx = SyntheticProvider(mean_temp_c=22, tz_offset_h=1)
    print(wx.at(1_704_110_400).air_temp_c)   # weather at a given instant

Providers:

* :class:`StaticProvider`     -- constant conditions (the "no variation" case).
* :class:`SyntheticProvider`  -- deterministic diurnal cycle, offline, for tests.
* :class:`CsvReplayProvider`  -- replay a downloaded/authored CSV.
* :class:`OpenMeteoProvider`  -- live/forecast/historical from the free Open-Meteo API.
* :class:`CachedProvider`     -- cache + offline fallback wrapper for live sources.
"""

from .cache import CachedProvider
from .config import WEATHER_PARAMS, WEATHER_TYPES, build_provider
from .provider import WeatherProvider
from .providers import (
    CsvReplayProvider,
    OpenMeteoProvider,
    StaticProvider,
    SyntheticProvider,
)
from .sample import WeatherSample
from .series import WeatherSeries

__all__ = [
    "WeatherSample",
    "WeatherProvider",
    "WeatherSeries",
    "StaticProvider",
    "SyntheticProvider",
    "CsvReplayProvider",
    "OpenMeteoProvider",
    "CachedProvider",
    "build_provider",
    "WEATHER_TYPES",
    "WEATHER_PARAMS",
]
