"""Concrete weather providers, all satisfying :class:`~simura.weather.provider.WeatherProvider`."""

from .csv_replay import CsvReplayProvider
from .open_meteo import OpenMeteoProvider
from .static import StaticProvider
from .synthetic import SyntheticProvider

__all__ = [
    "StaticProvider",
    "SyntheticProvider",
    "CsvReplayProvider",
    "OpenMeteoProvider",
]
