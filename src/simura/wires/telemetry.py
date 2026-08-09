"""Telemetry: the observable output of a wire twin.

Like :class:`simura.sim.telemetry.PackTelemetry`, this is the single stable,
serializable contract downstream consumers depend on -- so the physics can evolve
without breaking anyone. One :class:`WireTelemetry` describes a conductor at one
instant under one current.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields


@dataclass(frozen=True)
class WireTelemetry:
    time_s: float
    current_a: float
    resistance_ohm: float
    voltage_drop_v: float
    power_loss_w: float
    temp_c: float
    ampacity_a: float
    ampacity_utilization: float     # |I| / ampacity (1.0 == at the limit)
    temp_rating_c: float
    over_ampacity: bool             # |I| > ampacity
    over_temp: bool                 # temp_c > temp_rating_c

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WireTelemetry":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


def snapshot(wire, t: float, current_a: float, effect=None) -> WireTelemetry:
    """Build a :class:`WireTelemetry` from a wire's current state.

    Uses the effective (fault-adjusted) resistance/current/ratings stashed by the
    last :meth:`Wire.step`, so a faulty joint or degraded insulation shows up in
    what is *measured*, not just in the physics.
    """
    r = getattr(wire, "_last_resistance_ohm", wire.resistance_ohm(wire.temp_c))
    i = getattr(wire, "_last_current_a", current_a)
    ampacity = wire.effective_ampacity_a(effect)
    temp_rating = wire.effective_temp_rating_c(effect)
    util = abs(i) / ampacity if ampacity > 0 else 0.0

    return WireTelemetry(
        time_s=round(t, 3),
        current_a=round(float(i), 4),
        resistance_ohm=round(float(r), 8),
        voltage_drop_v=round(float(i * r), 5),
        power_loss_w=round(float(i * i * r), 4),
        temp_c=round(float(wire.temp_c), 3),
        ampacity_a=round(float(ampacity), 3),
        ampacity_utilization=round(float(util), 4),
        temp_rating_c=round(float(temp_rating), 2),
        over_ampacity=bool(abs(i) > ampacity),
        over_temp=bool(wire.temp_c > temp_rating),
    )
