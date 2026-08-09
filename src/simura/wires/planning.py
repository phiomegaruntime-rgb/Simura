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
) -> RunAssessment:
    """Check ``spec`` carrying ``current_a`` against ampacity/drop/temperature."""
    wire = Wire(spec)
    conductors = 2 if round_trip else 1

    t_ss = wire.steady_state_temp_c(current_a)
    r_one = wire.resistance_ohm(t_ss)
    r_total = r_one * conductors
    drop = abs(current_a) * r_total
    loss = current_a * current_a * r_total
    util = wire.ampacity_utilization(current_a)
    drop_pct = (drop / system_voltage_v * 100.0) if system_voltage_v else None

    problems: list[str] = []
    if util > 1.0:
        problems.append(
            f"over ampacity: {abs(current_a):.1f} A exceeds the {wire.ampacity_a:.0f} A rating "
            f"({util * 100:.0f}%)"
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
        ampacity_a=round(wire.ampacity_a, 2),
        ampacity_utilization=round(util, 4),
        temp_rating_c=round(wire.temp_rating_c, 2),
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
) -> Recommendation:
    """Smallest catalog wire of ``material`` that satisfies every constraint.

    Walks the catalog from smallest cross-section up and returns the first wire
    that passes :func:`evaluate_run`. If none pass, returns the largest available
    with its remaining problems and ``ok=False``.
    """
    candidates = sorted(
        (w for w in list_wire_types() if w.material == material),
        key=lambda w: w.area_mm2,
    )
    if not candidates:
        return Recommendation(None, None, f"no {material} wires in the catalog", False)

    last: tuple[WireType, RunAssessment] | None = None
    for wt in candidates:
        spec = WireSpec(wire_type=wt.id, length_m=length_m, ambient_temp_c=ambient_c)
        assessment = evaluate_run(spec, current_a, system_voltage_v, max_drop_pct, round_trip)
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
