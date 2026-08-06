"""The weather interchange contract.

:class:`WeatherSample` is to this package what ``PackTelemetry`` is to the
simulator: the single, stable, serializable shape that everything else consumes.
It is deliberately domain-neutral -- it describes *weather*, not batteries -- so
this whole subpackage can be lifted into any project where the environment drives
a system's behaviour (thermal loads, solar yield, HVAC, crop or road models).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any


@dataclass(frozen=True)
class WeatherSample:
    """Weather conditions at a single instant.

    ``timestamp`` is Unix epoch seconds (UTC). Units are SI-ish and explicit in
    the field names so there is never any ambiguity at a coupling boundary.
    ``humidity_frac`` is 0..1 (not %). ``source`` names the provider that
    produced the sample, purely for traceability.
    """

    timestamp: float
    air_temp_c: float
    wind_speed_ms: float = 0.0
    solar_w_m2: float = 0.0
    humidity_frac: float | None = None
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WeatherSample":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})
