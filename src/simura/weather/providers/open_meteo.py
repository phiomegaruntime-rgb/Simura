"""Live weather from the Open-Meteo API.

Open-Meteo is free and needs **no API key**, which keeps this open-source project
frictionless to clone and run. It serves current, forecast, and historical
("archive") data. We request the four fields the coupling cares about --
temperature, wind, shortwave (solar) radiation, and humidity -- for a window of
hours, parse them into a :class:`~simura.weather.series.WeatherSeries`, and
interpolate.

Only the standard library is used (``urllib``), so there is no extra dependency.
The network call lives behind :meth:`_fetch`, and parsing behind
:meth:`from_payload`, so the parser is unit-tested against a saved fixture with no
live request. Wrap this in :class:`~simura.weather.cache.CachedProvider` in
production so a transient outage falls back instead of raising.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ..sample import WeatherSample
from ..series import WeatherSeries

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

HOURLY_FIELDS = (
    "temperature_2m",
    "wind_speed_10m",
    "shortwave_radiation",
    "relative_humidity_2m",
)


class OpenMeteoProvider:
    """Fetch and interpolate live weather for a latitude/longitude."""

    def __init__(
        self,
        latitude: float,
        longitude: float,
        mode: str = "forecast",
        past_days: int = 1,
        forecast_days: int = 7,
        start_date: str | None = None,
        end_date: str | None = None,
        timeout_s: float = 10.0,
        prefetch: bool = False,
    ) -> None:
        if mode not in ("forecast", "archive"):
            raise ValueError("mode must be 'forecast' or 'archive'")
        if mode == "archive" and not (start_date and end_date):
            raise ValueError("archive mode requires start_date and end_date (YYYY-MM-DD)")
        self.latitude = latitude
        self.longitude = longitude
        self.mode = mode
        self.past_days = past_days
        self.forecast_days = forecast_days
        self.start_date = start_date
        self.end_date = end_date
        self.timeout_s = timeout_s
        self._series: WeatherSeries | None = None
        if prefetch:
            self._load()

    # -- public -----------------------------------------------------------
    def at(self, timestamp: float) -> WeatherSample:
        if self._series is None:
            self._load()
        assert self._series is not None
        return self._series.at(timestamp)

    # -- url / fetch (network seam) --------------------------------------
    def _url(self) -> str:
        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "hourly": ",".join(HOURLY_FIELDS),
            "windspeed_unit": "ms",
            "timezone": "GMT",
        }
        if self.mode == "forecast":
            base = FORECAST_URL
            params["past_days"] = self.past_days
            params["forecast_days"] = self.forecast_days
        else:
            base = ARCHIVE_URL
            params["start_date"] = self.start_date
            params["end_date"] = self.end_date
        return f"{base}?{urllib.parse.urlencode(params)}"

    def _fetch(self) -> dict:
        """Perform the HTTP GET and return the decoded JSON. Overridable for tests."""
        req = urllib.request.Request(self._url(), headers={"User-Agent": "simura-weather"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))

    def _load(self) -> None:
        self._series = self.from_payload(self._fetch())

    # -- parsing (pure, unit-tested) -------------------------------------
    @staticmethod
    def from_payload(payload: dict) -> WeatherSeries:
        """Parse an Open-Meteo hourly response into a :class:`WeatherSeries`."""
        hourly = payload.get("hourly") or {}
        times = hourly.get("time") or []
        if not times:
            raise ValueError("Open-Meteo response has no hourly.time data")
        temp = hourly.get("temperature_2m") or []
        wind = hourly.get("wind_speed_10m") or []
        solar = hourly.get("shortwave_radiation") or []
        hum = hourly.get("relative_humidity_2m") or []

        samples: list[WeatherSample] = []
        for i, t_str in enumerate(times):
            ts = _parse_gmt(t_str)
            samples.append(
                WeatherSample(
                    timestamp=ts,
                    air_temp_c=_get(temp, i, 0.0),
                    wind_speed_ms=_get(wind, i, 0.0),
                    solar_w_m2=_get(solar, i, 0.0),
                    humidity_frac=_get_humidity(hum, i),
                    source="open-meteo",
                )
            )
        return WeatherSeries(samples)


def _parse_gmt(t_str: str) -> float:
    """Open-Meteo GMT timestamps look like '2026-08-06T14:00' (naive UTC)."""
    dt = datetime.fromisoformat(t_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _get(arr: list, i: int, default: float) -> float:
    if i < len(arr) and arr[i] is not None:
        return float(arr[i])
    return default


def _get_humidity(arr: list, i: int) -> float | None:
    if i < len(arr) and arr[i] is not None:
        return float(arr[i]) / 100.0  # percent -> fraction
    return None
