"""Telemetry: the observable output of a light twin.

Like :class:`simura.sim.telemetry.PackTelemetry` and
:class:`simura.wires.telemetry.WireTelemetry`, this is the single stable,
serializable contract downstream consumers depend on -- so the physics can evolve
without breaking anyone. One :class:`LightTelemetry` describes a luminaire at one
instant: what it is drawing, what it is delivering, how hot it is, what colour it
is, and how much life it has left.

The last two are what a lighting twin is *for*. Electrical metering already tells
a building what its lights cost; it cannot tell it that a fitting is delivering
70% of the light it was commissioned with, or that a phosphor is cooking and the
colour has drifted 400 K. Those need the physics.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Optional


@dataclass(frozen=True)
class LightTelemetry:
    time_s: float
    drive: float                      # commanded dim level, 0..1
    lit: bool
    input_power_w: float
    current_a: float
    voltage_v: float
    luminous_flux_lm: float
    efficacy_lm_per_w: float
    radiant_power_w: float
    color_temp_k: float               # 0 when the source has no meaningful CCT
    source_temp_c: float              # junction / filament / wall temperature
    illuminance_lux: float            # on the reference surface, if one is set
    lumen_maintenance: float          # 0..1, flux left vs a new lamp
    warmup_frac: float                # 0..1, how far through warm-up
    operating_hours_h: float
    switch_cycles: float
    over_temp: bool                   # source above its safe temperature
    below_target: bool                # illuminance under the design target
    weather: Optional[dict] = None    # environmental conditions this step
    daylight_lux: Optional[float] = None   # daylight already on the surface

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "LightTelemetry":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


# Above this, a solid-state junction is outside every manufacturer's maximum and
# the lamp is destroying itself. Filaments and arc tubes run far hotter by design,
# so the check is per-family, applied in :func:`snapshot`.
MAX_JUNCTION_C = 125.0


def snapshot(
    light,
    t: float,
    drive: float,
    point,
    illuminance_lux: float = 0.0,
    target_lux: float = 0.0,
    weather=None,
    daylight_lux: float | None = None,
) -> LightTelemetry:
    """Build a :class:`LightTelemetry` from a lamp's solved operating point.

    ``point`` is the :class:`~simura.lights.lamp.OperatingPoint` the lamp last
    returned, so the frame reports what was actually delivered -- faults, warm-up
    and depreciation included -- rather than what the datasheet promises.
    """
    over_temp = bool(
        light.tech.is_solid_state and point.source_temp_c > MAX_JUNCTION_C
    )
    return LightTelemetry(
        time_s=round(t, 3),
        drive=round(float(drive), 4),
        lit=bool(point.lit),
        input_power_w=round(float(point.input_power_w), 3),
        current_a=round(float(point.current_a), 5),
        voltage_v=round(float(point.voltage_v), 3),
        luminous_flux_lm=round(float(point.luminous_flux_lm), 2),
        efficacy_lm_per_w=round(float(point.efficacy_lm_per_w), 3),
        radiant_power_w=round(float(point.radiant_power_w), 4),
        color_temp_k=round(float(point.color_temp_k), 1),
        source_temp_c=round(float(point.source_temp_c), 2),
        illuminance_lux=round(float(illuminance_lux), 2),
        lumen_maintenance=round(float(point.lumen_maintenance), 4),
        warmup_frac=round(float(point.warmup_frac), 4),
        operating_hours_h=round(float(light.operating_hours_h), 4),
        switch_cycles=float(light.switch_cycles),
        over_temp=over_temp,
        below_target=bool(target_lux > 0 and illuminance_lux < target_lux),
        weather=weather.to_dict() if weather is not None else None,
        daylight_lux=None if daylight_lux is None else round(float(daylight_lux), 2),
    )
