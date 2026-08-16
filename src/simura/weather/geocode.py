"""Turn a place name into coordinates (and a timezone).

The live weather provider needs a latitude and a longitude, but nobody thinks in
those. This is the small lookup that lets a UI ask for "Berlin" and get back
somewhere to point :class:`~simura.weather.providers.open_meteo.OpenMeteoProvider`
at -- plus the **IANA timezone**, which is what makes a local clock possible and
therefore what makes "is it morning or evening there?" answerable.

Open-Meteo's geocoding API is used for the same reasons its forecast API is: free,
no API key, and no extra dependency (``urllib`` only). As in that module the
network call lives behind :meth:`_fetch` and the parsing behind
:func:`places_from_payload`, so the parser is unit-tested against a saved payload
with no live request.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


@dataclass(frozen=True)
class Place:
    """One geocoding result: somewhere to put a simulated site."""

    name: str
    latitude: float
    longitude: float
    country: str = ""
    # Region/state, when the API knows one -- what tells two Springfields apart.
    admin1: str = ""
    timezone: str = ""
    elevation_m: float | None = None

    @property
    def label(self) -> str:
        """A human-readable one-liner: "Berlin, Berlin, Germany"."""
        return ", ".join(p for p in (self.name, self.admin1, self.country) if p)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "label": self.label}


def places_from_payload(payload: dict[str, Any]) -> list[Place]:
    """Parse an Open-Meteo geocoding response into :class:`Place` objects.

    A query that matches nothing comes back without a ``results`` key at all,
    which is a normal empty answer rather than an error.
    """
    out: list[Place] = []
    for row in payload.get("results") or []:
        try:
            out.append(
                Place(
                    name=str(row["name"]),
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    country=str(row.get("country", "")),
                    admin1=str(row.get("admin1", "")),
                    timezone=str(row.get("timezone", "")),
                    elevation_m=(
                        float(row["elevation"]) if row.get("elevation") is not None else None
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue  # a malformed row is not worth failing the whole search for
    return out


def _fetch(url: str, timeout_s: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout_s) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def search_places(query: str, count: int = 6, timeout_s: float = 8.0) -> list[Place]:
    """Look up places matching ``query``. Returns ``[]`` for a blank query."""
    query = query.strip()
    if not query:
        return []
    params = {"name": query, "count": max(1, min(count, 20)), "language": "en", "format": "json"}
    url = f"{GEOCODING_URL}?{urllib.parse.urlencode(params)}"
    return places_from_payload(_fetch(url, timeout_s))
