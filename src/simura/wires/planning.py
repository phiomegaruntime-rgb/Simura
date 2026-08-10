"""Wiring logic & planning: the checks an engineer runs before pulling cable.

Two questions, answered without a crash (a *list of problems*, in the style of
:mod:`simura.builder.validate`):

* :func:`evaluate_run` -- for a chosen wire and load, is it within ampacity, is the
  voltage drop acceptable, does it stay under the insulation's temperature rating?
* :func:`recommend_gauge` -- what is the smallest catalog wire that satisfies all
  three constraints for a given current, length and allowable drop?

``round_trip`` doubles resistance for the two-conductor there-and-back path of a
DC circuit (the usual case); the conductor *temperature* is always evaluated per
single conductor.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import WireType, list_wire_types
from .environment import WireEnvironmentCoupling
from .wire import Wire, WireSpec


@dataclass
class RunAssessment:
    """Result of checking one wire against one load."""

    resistance_ohm: float
    voltage_drop_v: float
    voltage_drop_pct: float | None
    power_loss_w: float
    steady_state_temp_c: float
    ampacity_a: float
    ampacity_utilization: float
    temp_rating_c: float
    ambient_temp_c: float | None = None   # ambient used (weather-driven when set)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict:
        from dataclasses import asdict

        return asdict(self)


def evaluate_run(
    spec: WireSpec,
    current_a: float,
    system_voltage_v: float | None = None,
    max_drop_pct: float = 3.0,
    round_trip: bool = False,
    weather=None,
    coupling: WireEnvironmentCoupling | None = None,
) -> RunAssessment:
    """Check ``spec`` carrying ``current_a`` against ampacity/drop/temperature.

    When ``weather`` (a ``WeatherSample``) is supplied the check becomes
    weather-aware: the conductor's steady-state temperature reflects the day's
    ambient, wind cooling and absorbed sun, and the ampacity is **derated for
    ambient** (the standard, conservative correction — it deliberately does not
    credit the wind, which shows up only in the predicted temperature). Without
    ``weather`` the behaviour is unchanged.
    """
    wire = Wire(spec)
    conductors = 2 if round_trip else 1

    # Environmental levers: ambient, wind cooling, absorbed solar heat.
    ambient_c = wire.ambient_c
    cooling_mult = 1.0
    extra_heat_w = 0.0
    if weather is not None:
        coupling = coupling or WireEnvironmentCoupling()
        env = coupling.apply(weather, wire.diameter_m * wire.length_m)
        ambient_c = env.ambient_c
        cooling_mult = env.cooling_mult
        extra_heat_w = env.solar_heat_w

    t_ss = wire.steady_state_temp_c(
        current_a, ambient_c=ambient_c, cooling_mult=cooling_mult, extra_heat_w=extra_heat_w
    )
    r_one = wire.resistance_ohm(t_ss)
    r_total = r_one * conductors
    drop = abs(current_a) * r_total
    loss = current_a * current_a * r_total
    drop_pct = (drop / system_voltage_v * 100.0) if system_voltage_v else None

    # Ampacity: derate for ambient when weather-driven; otherwise the reference rating.
    ampacity = wire.derated_ampacity_a(ambient_c) if weather is not None else wire.ampacity_a

    problems: list[str] = []
    if ampacity <= 0.0:
        util = 9.99  # sentinel: ambient at/above the rating leaves no capacity
        problems.append(
            f"ambient {ambient_c:.0f} C reaches the {wire.temp_rating_c:.0f} C insulation "
            f"rating — no usable ampacity"
        )
    else:
        util = abs(current_a) / ampacity
        if util > 1.0:
            at = f" at {ambient_c:.0f} C" if weather is not None else ""
            problems.append(
                f"over ampacity: {abs(current_a):.1f} A exceeds the {ampacity:.0f} A rating"
                f"{at} ({util * 100:.0f}%)"
            )
    if drop_pct is not None and drop_pct > max_drop_pct:
        problems.append(
            f"voltage drop {drop_pct:.1f}% exceeds the {max_drop_pct:.1f}% limit "
            f"({drop:.2f} V on {system_voltage_v:.0f} V)"
        )
    if t_ss > wire.temp_rating_c:
        problems.append(
            f"conductor reaches {t_ss:.0f} C, over the {wire.temp_rating_c:.0f} C "
            f"insulation rating"
        )

    return RunAssessment(
        resistance_ohm=round(r_total, 8),
        voltage_drop_v=round(drop, 5),
        voltage_drop_pct=None if drop_pct is None else round(drop_pct, 3),
        power_loss_w=round(loss, 4),
        steady_state_temp_c=round(t_ss, 2),
        ampacity_a=round(ampacity, 2),
        ampacity_utilization=round(util, 4),
        temp_rating_c=round(wire.temp_rating_c, 2),
        ambient_temp_c=round(ambient_c, 2) if weather is not None else None,
        problems=problems,
    )


@dataclass
class Recommendation:
    """A sizing recommendation: the chosen wire, why, and its assessment."""

    wire_type: WireType | None
    assessment: RunAssessment | None
    rationale: str
    ok: bool

    def to_dict(self) -> dict:
        return {
            "wire_type": self.wire_type.to_dict() if self.wire_type else None,
            "assessment": self.assessment.to_dict() if self.assessment else None,
            "rationale": self.rationale,
            "ok": self.ok,
        }


def recommend_gauge(
    current_a: float,
    length_m: float,
    system_voltage_v: float | None = None,
    max_drop_pct: float = 3.0,
    material: str = "copper",
    ambient_c: float = 25.0,
    round_trip: bool = True,
    weather=None,
) -> Recommendation:
    """Smallest catalog wire of ``material`` that satisfies every constraint.

    Walks the catalog from smallest cross-section up and returns the first wire
    that passes :func:`evaluate_run`. If none pass, returns the largest available
    with its remaining problems and ``ok=False``. When ``weather`` is supplied the
    sizing is done for that day's conditions (a hot, still day derates ampacity and
    can push the recommendation up a gauge).
    """
    candidates = sorted(
        (w for w in list_wire_types() if w.material == material),
        key=lambda w: w.area_mm2,
    )
    if not candidates:
        return Recommendation(None, None, f"no {material} wires in the catalog", False)

    spec_ambient = weather.air_temp_c if weather is not None else ambient_c
    last: tuple[WireType, RunAssessment] | None = None
    for wt in candidates:
        spec = WireSpec(wire_type=wt.id, length_m=length_m, ambient_temp_c=spec_ambient)
        assessment = evaluate_run(
            spec, current_a, system_voltage_v, max_drop_pct, round_trip, weather=weather
        )
        last = (wt, assessment)
        if assessment.ok:
            rationale = (
                f"{wt.name}: {assessment.ampacity_utilization * 100:.0f}% of ampacity"
            )
            if assessment.voltage_drop_pct is not None:
                rationale += f", {assessment.voltage_drop_pct:.1f}% drop"
            rationale += f", {assessment.steady_state_temp_c:.0f} C conductor"
            return Recommendation(wt, assessment, rationale, True)

    wt, assessment = last  # type: ignore[misc]
    return Recommendation(
        wt,
        assessment,
        f"no catalog {material} wire satisfies the constraints; "
        f"largest ({wt.name}) still has: " + "; ".join(assessment.problems),
        False,
    )
