"""Build a provider from a plain, JSON-serializable spec dict.

This is what makes weather *declarative*: a system's weather source can live in a
JSON spec, an env var, or an API body as ``{"type": "...", ...params}`` and be
turned into a live provider here. Mirrors ``simura.connect.config`` in spirit.
"""

from __future__ import annotations

from typing import Any

from .cache import CachedProvider
from .provider import WeatherProvider
from .providers import (
    CsvReplayProvider,
    OpenMeteoProvider,
    StaticProvider,
    SyntheticProvider,
)
from .providers.synthetic import SyntheticProvider as _Synthetic

# The set of provider types ``build_provider`` understands. "none" is a sentinel
# meaning "no weather" -- callers should treat it as ``None`` and skip coupling.
WEATHER_TYPES = ("none", "static", "synthetic", "csv", "open_meteo")

# Default params per type, for UIs and documentation.
WEATHER_PARAMS: dict[str, dict[str, Any]] = {
    "none": {},
    "static": {"air_temp_c": 25.0, "wind_speed_ms": 0.0, "solar_w_m2": 0.0},
    "synthetic": {
        "mean_temp_c": 20.0,
        "temp_amplitude_c": 8.0,
        "solar_peak_w_m2": 800.0,
        "wind_mean_ms": 3.0,
        "wind_amplitude_ms": 2.0,
        "tz_offset_h": 0.0,
    },
    "csv": {"path": ""},
    "open_meteo": {
        "latitude": 0.0,
        "longitude": 0.0,
        "mode": "forecast",
    },
}


def build_provider(spec: dict[str, Any]) -> WeatherProvider | None:
    """Turn a ``{"type": ..., ...}`` dict into a provider (``None`` for "none").

    Live sources (``open_meteo``) are wrapped in a :class:`CachedProvider` so they
    are polled sparingly and degrade to an offline fallback on error. Set
    ``"cached": false`` to opt out.
    """
    if not spec:
        return None
    kind = str(spec.get("type", "none")).lower()
    params = {k: v for k, v in spec.items() if k not in ("type", "cached")}

    if kind in ("none", ""):
        return None
    if kind == "static":
        return StaticProvider(**_filter(params, StaticProvider))
    if kind == "synthetic":
        return SyntheticProvider(**_filter(params, SyntheticProvider))
    if kind == "csv":
        path = params.get("path")
        if not path:
            raise ValueError("csv weather provider needs a 'path'")
        cols = params.get("columns")
        return CsvReplayProvider(path=path, columns=cols)
    if kind == "open_meteo":
        provider: WeatherProvider = OpenMeteoProvider(**_filter(params, OpenMeteoProvider))
        if spec.get("cached", True):
            fallback = _Synthetic(
                tz_offset_h=float(params.get("tz_offset_h", 0.0)),
            )
            provider = CachedProvider(provider, fallback=fallback)
        return provider

    raise ValueError(f"unknown weather provider type '{kind}' (use one of {WEATHER_TYPES})")


def _filter(params: dict[str, Any], cls: type) -> dict[str, Any]:
    """Keep only params that ``cls.__init__`` accepts (forgiving of extra keys)."""
    import inspect

    allowed = set(inspect.signature(cls.__init__).parameters) - {"self"}
    return {k: v for k, v in params.items() if k in allowed}
