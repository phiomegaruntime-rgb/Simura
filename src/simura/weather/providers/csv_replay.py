"""Replay historical (or hand-authored) weather from a CSV file.

Turn a downloaded weather export -- or a small hand-written scenario -- into a
provider. Rows are read once into a :class:`~simura.weather.series.WeatherSeries`
and interpolated by timestamp, so the sim can query any instant between rows.
Pure standard library (``csv``); no pandas, no numpy.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone

from ..sample import WeatherSample
from ..series import WeatherSeries

# Default column names; override via ``columns`` for a foreign export.
DEFAULT_COLUMNS = {
    "timestamp": "timestamp",
    "air_temp_c": "air_temp_c",
    "wind_speed_ms": "wind_speed_ms",
    "solar_w_m2": "solar_w_m2",
    "humidity_frac": "humidity_frac",
}


def parse_timestamp(raw: str) -> float:
    """Parse a cell as epoch seconds (numeric) or an ISO-8601 datetime (UTC)."""
    raw = raw.strip()
    try:
        return float(raw)
    except ValueError:
        pass
    text = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


class CsvReplayProvider:
    """Interpolates weather from the rows of a CSV file."""

    def __init__(self, path: str, columns: dict[str, str] | None = None) -> None:
        self.path = path
        cols = {**DEFAULT_COLUMNS, **(columns or {})}
        self._series = WeatherSeries(_load_rows(path, cols))

    def at(self, timestamp: float) -> WeatherSample:
        s = self._series.at(timestamp)
        # Re-stamp source so downstream can see where it came from.
        return WeatherSample(
            timestamp=s.timestamp,
            air_temp_c=s.air_temp_c,
            wind_speed_ms=s.wind_speed_ms,
            solar_w_m2=s.solar_w_m2,
            humidity_frac=s.humidity_frac,
            source="csv",
        )


def _num(row: dict[str, str], key: str, default: float = 0.0) -> float:
    val = row.get(key)
    if val is None or val.strip() == "":
        return default
    return float(val)


def _load_rows(path: str, cols: dict[str, str]) -> list[WeatherSample]:
    samples: list[WeatherSample] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or cols["timestamp"] not in reader.fieldnames:
            raise ValueError(
                f"CSV must have a '{cols['timestamp']}' column; got {reader.fieldnames}"
            )
        for row in reader:
            hum_key = cols["humidity_frac"]
            hum = None
            if hum_key in row and row[hum_key] not in (None, ""):
                hum = float(row[hum_key])
            samples.append(
                WeatherSample(
                    timestamp=parse_timestamp(row[cols["timestamp"]]),
                    air_temp_c=_num(row, cols["air_temp_c"]),
                    wind_speed_ms=_num(row, cols["wind_speed_ms"]),
                    solar_w_m2=_num(row, cols["solar_w_m2"]),
                    humidity_frac=hum,
                    source="csv",
                )
            )
    if not samples:
        raise ValueError(f"no rows found in {path}")
    return samples
