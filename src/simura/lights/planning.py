"""Lighting logic & planning: the checks a designer runs before ordering fittings.

Two questions, answered without a crash (a *list of problems*, in the style of
:mod:`simura.wires.planning` and :mod:`simura.builder.validate`):

* :func:`evaluate_installation` -- for a chosen lamp and a chosen number of them,
  is the space bright enough for the task, is the light even, is the colour right,
  and does the installed power clear the energy code?
* :func:`recommend_lamp` -- which catalog lamp, and how many, meets the target at
  the lowest installed power?

The photometry is the lumen method (:mod:`simura.lights.photometry`); what this
module adds is *judgement* -- the thresholds a design is actually held to, and the
maintenance factor that decides whether it still passes in five years' time.

Maintained, not initial
-----------------------

The single most common lighting mistake is designing for day one. Lamps
depreciate, luminaires collect dirt, and a design that just barely hits 500 lux
new will be delivering 350 lux long before anyone replaces anything. So every
check here can run at the end of a maintenance cycle rather than the start: pass
``maintenance_hours`` and the lamps are aged that far before their output is
counted. :func:`recommend_lamp` does it by default, at 8000 hours -- roughly
three years of office use -- because a recommendation that only holds when the
lamps are new is not a recommendation.

That ageing is also what makes the comparison fair across technologies. A
fluorescent tube and an LED that match on day one do not match three years later,
and the lamp that wins on installed power at 8000 hours is frequently not the one
that wins at zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .catalog import LampType, list_lamp_types
from .environment import LightEnvironmentCoupling
from .lamp import Light, LightSpec
from .photometry import (
    RoomLighting,
    lumen_method,
    luminaires_for_target,
    task_lux,
)

# Installed power limits (W/m^2) at which a design starts to look wasteful. These
# are the shape of the limits in the common energy codes (ASHRAE 90.1 building-area
# method, EN 15193) rather than any one code's exact table.
POWER_DENSITY_LIMIT_W_M2: dict[str, float] = {
    "corridor": 5.0,
    "storage": 6.0,
    "lobby": 8.0,
    "classroom": 9.0,
    "office": 9.0,
    "workshop": 11.0,
    "drawing_office": 12.0,
    "inspection": 15.0,
    "surgery": 25.0,
    "residential_general": 6.0,
    "kitchen": 9.0,
    "sports_hall": 12.0,
    "warehouse_aisle": 8.0,
    "street_residential": 3.0,
    "street_main": 4.0,
    "car_park": 3.0,
}

# Minimum colour rendering index expected for a task. Below this, colours in the
# space read wrong -- which matters in a kitchen and not at all in a car park.
MIN_CRI: dict[str, float] = {
    "office": 80.0,
    "classroom": 80.0,
    "kitchen": 80.0,
    "drawing_office": 80.0,
    "inspection": 90.0,
    "surgery": 90.0,
    "residential_general": 80.0,
    "lobby": 80.0,
    "workshop": 70.0,
    "sports_hall": 65.0,
    "corridor": 40.0,
    "storage": 40.0,
    "warehouse_aisle": 60.0,
    "street_residential": 20.0,
    "street_main": 20.0,
    "car_park": 20.0,
}


@dataclass
class InstallationAssessment:
    """Result of checking one lighting design against one task."""

    lamp_id: str | None
    n_luminaires: int
    target_lux: float
    maintained_lux: float
    initial_lux: float
    flux_per_luminaire_lm: float
    power_w: float
    power_density_w_per_m2: float
    efficacy_lm_per_w: float
    color_temp_k: float
    cri: float
    room: RoomLighting
    lumen_maintenance: float
    ambient_temp_c: float | None = None   # ambient used (weather-driven when set)
    annual_energy_kwh: float | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


def evaluate_installation(
    spec: LightSpec,
    n_luminaires: int,
    length_m: float,
    width_m: float,
    mounting_height_m: float = 2.5,
    task: str = "office",
    target_lux: float | None = None,
    ceiling_reflectance: float = 0.7,
    wall_reflectance: float = 0.5,
    floor_reflectance: float = 0.2,
    maintenance_hours: float = 0.0,
    dirt_frac: float = 0.1,
    annual_hours: float = 2500.0,
    weather=None,
    coupling: LightEnvironmentCoupling | None = None,
) -> InstallationAssessment:
    """Check a lighting design against illuminance, colour and installed power.

    ``maintenance_hours`` ages every lamp before its output is counted, so the
    answer is the *maintained* illuminance rather than the day-one one.

    When ``weather`` (a ``WeatherSample``) is supplied the check is done for that
    day's conditions: the ambient moves the source temperature, which moves the
    light output -- upward for a cold fluorescent lamp brought indoors, downward
    for an LED on a hot roof. Without it the lamp is evaluated at 25 °C.
    """
    target = float(target_lux) if target_lux is not None else task_lux(task)

    # Age the lamp to the end of its maintenance cycle before measuring it.
    aged = LightSpec.from_dict(
        {**spec.to_dict(), "operating_hours_h": spec.operating_hours_h + maintenance_hours}
    )
    light = Light(aged)
    light.time_lit_s = 1e9          # fully warmed up

    ambient_c = None
    if weather is not None:
        env = (coupling or LightEnvironmentCoupling()).apply(weather)
        ambient_c = env.ambient_c + env.solar_heat_w * light.r_th

    point = light.operating_point(1.0, ambient_c)

    # The same lamp brand new, so the report can show what maintenance costs.
    fresh = Light(spec)
    fresh.time_lit_s = 1e9
    fresh_point = fresh.operating_point(1.0, ambient_c)

    room = lumen_method(
        flux_per_luminaire_lm=point.luminous_flux_lm,
        n_luminaires=n_luminaires,
        length_m=length_m,
        width_m=width_m,
        mounting_height_m=mounting_height_m,
        power_per_luminaire_w=point.input_power_w,
        ceiling_reflectance=ceiling_reflectance,
        wall_reflectance=wall_reflectance,
        floor_reflectance=floor_reflectance,
        lumen_maintenance=1.0,          # already aged into the flux above
        dirt_frac=dirt_frac,
    )
    initial = lumen_method(
        flux_per_luminaire_lm=fresh_point.luminous_flux_lm,
        n_luminaires=n_luminaires,
        length_m=length_m,
        width_m=width_m,
        mounting_height_m=mounting_height_m,
        power_per_luminaire_w=fresh_point.input_power_w,
        ceiling_reflectance=ceiling_reflectance,
        wall_reflectance=wall_reflectance,
        floor_reflectance=floor_reflectance,
    )

    cri = light.tech.cri
    problems: list[str] = []

    if room.average_lux < target:
        shortfall = (1.0 - room.average_lux / target) * 100.0 if target > 0 else 0.0
        at = f" at {ambient_c:.0f} °C" if ambient_c is not None else ""
        problems.append(
            f"under-lit: {room.average_lux:.0f} lux maintained{at} against a "
            f"{target:.0f} lux target ({shortfall:.0f}% short)"
        )
    elif room.average_lux > target * 2.0:
        problems.append(
            f"over-lit: {room.average_lux:.0f} lux is more than twice the "
            f"{target:.0f} lux target — wasted energy"
        )

    limit = POWER_DENSITY_LIMIT_W_M2.get(task)
    if limit is not None and room.power_density_w_per_m2 > limit:
        problems.append(
            f"installed power {room.power_density_w_per_m2:.1f} W/m² exceeds the "
            f"{limit:.1f} W/m² guideline for {task.replace('_', ' ')} lighting"
        )

    min_cri = MIN_CRI.get(task)
    if min_cri is not None and cri < min_cri:
        problems.append(
            f"colour rendering CRI {cri:.0f} is below the {min_cri:.0f} expected "
            f"for {task.replace('_', ' ')} lighting"
        )

    if point.source_temp_c > 125.0 and light.tech.is_solid_state:
        problems.append(
            f"junction reaches {point.source_temp_c:.0f} °C, past the 125 °C "
            f"maximum — the lamp will not reach its rated life"
        )

    if not light.tech.dimmable and light.tech.restrike_s > 300:
        problems.append(
            f"{light.tech.name} needs {light.tech.restrike_s / 60:.0f} minutes to "
            f"restrike after a power interruption — unsuitable where light must "
            f"return immediately"
        )

    return InstallationAssessment(
        lamp_id=spec.lamp_type,
        n_luminaires=n_luminaires,
        target_lux=round(target, 1),
        maintained_lux=room.average_lux,
        initial_lux=initial.average_lux,
        flux_per_luminaire_lm=round(point.luminous_flux_lm, 1),
        power_w=room.power_w,
        power_density_w_per_m2=room.power_density_w_per_m2,
        efficacy_lm_per_w=round(point.efficacy_lm_per_w, 2),
        color_temp_k=round(point.color_temp_k, 0),
        cri=round(cri, 1),
        room=room,
        lumen_maintenance=round(point.lumen_maintenance, 4),
        ambient_temp_c=round(ambient_c, 2) if ambient_c is not None else None,
        annual_energy_kwh=round(room.power_w * annual_hours / 1000.0, 1),
        problems=problems,
    )


@dataclass
class Recommendation:
    """A lamp recommendation: the chosen lamp, how many, why, and its assessment."""

    lamp_type: LampType | None
    n_luminaires: int
    assessment: InstallationAssessment | None
    rationale: str
    ok: bool
    alternatives: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lamp_type": self.lamp_type.to_dict() if self.lamp_type else None,
            "n_luminaires": self.n_luminaires,
            "assessment": self.assessment.to_dict() if self.assessment else None,
            "rationale": self.rationale,
            "ok": self.ok,
            "alternatives": self.alternatives,
        }


def recommend_lamp(
    length_m: float,
    width_m: float,
    mounting_height_m: float = 2.5,
    task: str = "office",
    target_lux: float | None = None,
    family: str | None = None,
    ceiling_reflectance: float = 0.7,
    wall_reflectance: float = 0.5,
    floor_reflectance: float = 0.2,
    maintenance_hours: float = 8000.0,
    dirt_frac: float = 0.1,
    annual_hours: float = 2500.0,
    weather=None,
    coupling: LightEnvironmentCoupling | None = None,
) -> Recommendation:
    """The catalog lamp that meets the target at the lowest installed power.

    Every candidate is sized (how many of *this* lamp does the room need?), then
    checked in full, and the ones that pass are ranked by installed watts. That
    ordering is what makes the comparison interesting: the cheapest lamp to buy is
    almost never the cheapest to run, and the technology that wins depends on the
    room -- a cold store rules out fluorescent, a gallery rules out sodium, and a
    space that needs instant light rules out every high-pressure discharge lamp.

    Optionally restricted to one ``family`` ("solid_state", "incandescent",
    "discharge_lp", "discharge_hp"), which is how you ask what the *best possible*
    filament or discharge answer would have been.
    """
    target = float(target_lux) if target_lux is not None else task_lux(task)
    candidates = list_lamp_types(family=family)
    if not candidates:
        return Recommendation(None, 0, None, f"no lamps in the catalog for family '{family}'", False)

    scored: list[tuple[float, LampType, int, InstallationAssessment]] = []
    failed: list[tuple[float, LampType, int, InstallationAssessment]] = []

    for lamp in candidates:
        spec = LightSpec(lamp_type=lamp.id)
        aged = Light(
            LightSpec.from_dict({**spec.to_dict(), "operating_hours_h": maintenance_hours})
        )
        aged.time_lit_s = 1e9
        flux = aged.operating_point(1.0).luminous_flux_lm
        if flux <= 0:
            continue

        n = luminaires_for_target(
            target_lux=target,
            flux_per_luminaire_lm=flux,
            length_m=length_m,
            width_m=width_m,
            mounting_height_m=mounting_height_m,
            ceiling_reflectance=ceiling_reflectance,
            wall_reflectance=wall_reflectance,
            floor_reflectance=floor_reflectance,
            dirt_frac=dirt_frac,
        )
        if n <= 0:
            continue

        assessment = evaluate_installation(
            spec, n, length_m, width_m, mounting_height_m, task, target,
            ceiling_reflectance, wall_reflectance, floor_reflectance,
            maintenance_hours, dirt_frac, annual_hours, weather, coupling,
        )
        if assessment.ok:
            scored.append((assessment.power_w, lamp, n, assessment))
        else:
            failed.append((assessment.power_w, lamp, n, assessment))

    if not scored:
        if not failed:
            return Recommendation(None, 0, None, "no catalog lamp produces usable light", False)
        # Report the *closest* failure, not an arbitrary one: fewest unmet
        # constraints first, then lowest installed power among those.
        failed.sort(key=lambda f: (len(f[3].problems), f[0]))
        _, lamp, n, assessment = failed[0]
        return Recommendation(
            lamp, n, assessment,
            f"no catalog lamp satisfies every constraint; the closest is "
            f"{n} x {lamp.name}, which still has: " + "; ".join(assessment.problems),
            False,
            _alternatives(failed[:8]),
        )

    scored.sort(key=lambda s: s[0])
    _, lamp, n, assessment = scored[0]
    rationale = (
        f"{n} x {lamp.name}: {assessment.maintained_lux:.0f} lux maintained on a "
        f"{assessment.target_lux:.0f} lux target, {assessment.power_density_w_per_m2:.1f} W/m², "
        f"{assessment.annual_energy_kwh:.0f} kWh/year"
    )
    return Recommendation(lamp, n, assessment, rationale, True, _alternatives(scored[:8]))


def _alternatives(
    ranked: list[tuple[float, LampType, int, InstallationAssessment]]
) -> list[dict[str, Any]]:
    """Flatten a ranked candidate list into the comparison rows a UI shows."""
    return [
        {
            "lamp_id": lamp.id,
            "name": lamp.name,
            "family": lamp.to_dict()["family"],
            "n_luminaires": n,
            "power_w": a.power_w,
            "power_density_w_per_m2": a.power_density_w_per_m2,
            "maintained_lux": a.maintained_lux,
            "annual_energy_kwh": a.annual_energy_kwh,
            "efficacy_lm_per_w": a.efficacy_lm_per_w,
            "color_temp_k": a.color_temp_k,
            "cri": a.cri,
            "ok": a.ok,
            "problems": a.problems,
        }
        for _, lamp, n, a in ranked
    ]
