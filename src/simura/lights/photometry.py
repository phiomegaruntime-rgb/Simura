"""Photometry: turning lumens into light on a surface.

A lamp's luminous flux is the total light it emits, in every direction. What
anybody actually cares about is the **illuminance** where they are standing --
lux on a desk, on a road, on a workbench. That conversion is pure geometry, and
it is the part of lighting design that decides how many fittings a room needs and
where they go.

Three relations do all the work::

    Solid angle of a cone   Omega = 2*pi*(1 - cos(theta/2))        [steradian]
    Luminous intensity      I = Phi / Omega                        [candela]
    Illuminance             E = I * cos(alpha) / d^2               [lux]

The last one is the inverse-square law with Lambert's cosine: double the mounting
height and you get a quarter of the light; tilt the surface away from the source
and you lose the cosine. Between them they explain nearly every lighting mistake
ever made.

For a whole room, per-point geometry is the wrong tool -- most of the light
arrives after bouncing off the walls and ceiling. The industry's answer is the
**lumen method**, which folds all of that into a single *utilisation factor*::

    E_average = (Phi_total * UF * LLF) / area

with ``UF`` from the room's shape and surface reflectances, and ``LLF`` the light
loss factor covering lamp ageing and dirt. Both are provided here.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

# Illuminance targets people actually design to, from the standard practice
# tables (EN 12464-1 for interiors, roughly matched by IES RP-8 for roads). Used
# by the planner to answer "is this enough light?" without the caller having to
# know the number.
TASK_ILLUMINANCE_LUX: dict[str, float] = {
    "corridor": 100.0,
    "storage": 150.0,
    "lobby": 200.0,
    "classroom": 300.0,
    "office": 500.0,
    "workshop": 500.0,
    "drawing_office": 750.0,
    "inspection": 1000.0,
    "surgery": 10000.0,
    "residential_general": 150.0,
    "kitchen": 300.0,
    "street_residential": 10.0,
    "street_main": 20.0,
    "car_park": 20.0,
    "sports_hall": 300.0,
    "warehouse_aisle": 200.0,
}


def beam_solid_angle_sr(beam_angle_deg: float) -> float:
    """Solid angle of a cone of full angle ``beam_angle_deg``, in steradians.

    ``360`` (or anything at or above it) is the whole sphere, ``4*pi`` sr -- a bare
    lamp radiating in every direction.
    """
    if beam_angle_deg >= 360.0:
        return 4.0 * math.pi
    half = math.radians(max(beam_angle_deg, 1e-6) / 2.0)
    return 2.0 * math.pi * (1.0 - math.cos(min(half, math.pi)))


def luminous_intensity_cd(flux_lm: float, beam_angle_deg: float) -> float:
    """Average luminous intensity inside the beam, in candela.

    A narrow beam concentrates the same lumens into a smaller solid angle, so a
    spot lamp is far more intense than an omnidirectional one of equal output --
    which is the entire reason optics exist.
    """
    omega = beam_solid_angle_sr(beam_angle_deg)
    return flux_lm / omega if omega > 0 else 0.0


def illuminance_lux(
    intensity_cd: float, distance_m: float, incidence_deg: float = 0.0
) -> float:
    """``E = I*cos(alpha)/d^2`` -- illuminance on a surface from a point source."""
    if distance_m <= 0:
        return 0.0
    cos_a = math.cos(math.radians(max(-89.999, min(89.999, incidence_deg))))
    return intensity_cd * max(0.0, cos_a) / (distance_m * distance_m)


def point_illuminance_lux(
    flux_lm: float,
    beam_angle_deg: float,
    mount_height_m: float,
    offset_m: float = 0.0,
) -> float:
    """Illuminance on a horizontal surface below a lamp, ``offset_m`` to one side.

    The full point calculation: distance and angle of incidence both come from the
    geometry, and a point outside the beam cone gets nothing. Directly beneath a
    lamp (``offset_m = 0``) this reduces to ``I / h^2``.
    """
    if mount_height_m <= 0:
        return 0.0
    distance = math.hypot(mount_height_m, offset_m)
    angle_deg = math.degrees(math.atan2(abs(offset_m), mount_height_m))
    if beam_angle_deg < 360.0 and angle_deg > beam_angle_deg / 2.0:
        return 0.0
    return illuminance_lux(luminous_intensity_cd(flux_lm, beam_angle_deg), distance, angle_deg)


def room_index(length_m: float, width_m: float, mounting_height_m: float) -> float:
    """The room's shape as one number: ``L*W / ((L+W)*H_m)``.

    ``mounting_height_m`` is the height of the luminaires *above the working
    plane*, not above the floor. A tall narrow room has a low index and wastes
    light on its walls; a wide shallow one has a high index and uses it.
    """
    if mounting_height_m <= 0 or (length_m + width_m) <= 0:
        return 0.0
    return (length_m * width_m) / ((length_m + width_m) * mounting_height_m)


def utilisation_factor(
    room_index_value: float,
    ceiling_reflectance: float = 0.7,
    wall_reflectance: float = 0.5,
    floor_reflectance: float = 0.2,
    downward_light_output_ratio: float = 0.85,
) -> float:
    """Fraction of a luminaire's lumens that reaches the working plane.

    Real utilisation factors come from a manufacturer's photometric test file as a
    table against room index and reflectances. This is a smooth fit of the same
    shape: it saturates as the room gets wide relative to its height (there is
    less wall to lose light to), and rises with the surfaces' reflectance because
    light that misses the first time gets another chance.

    Honesty note: a fitted curve, not a photometric file. Good to a few percent
    over the ordinary range of rooms, and quite wrong for anything unusual.
    **Design real installations from the luminaire's own photometric data.**
    """
    k = max(0.0, room_index_value)
    # Geometry: saturating in the room index, the classic shape of a UF table.
    geometry = k / (k + 0.9)
    # Interreflection: how much of the light that misses the plane comes back.
    surfaces = (
        0.55 * ceiling_reflectance + 0.35 * wall_reflectance + 0.10 * floor_reflectance
    )
    bounce = 1.0 + 0.55 * surfaces * (1.0 - geometry)
    uf = downward_light_output_ratio * geometry * bounce
    return max(0.0, min(0.95, uf))


def light_loss_factor(
    lumen_maintenance: float = 1.0,
    dirt_frac: float = 0.0,
    survival_frac: float = 1.0,
) -> float:
    """The lumens a maintained installation actually delivers, as a fraction of new.

    Lighting is designed for the *end* of the maintenance cycle, not for day one:
    lamps depreciate, luminaires get dirty, and a few lamps are always out. Multiply
    the three and you have the number every design must clear.
    """
    return max(0.0, lumen_maintenance) * max(0.0, 1.0 - dirt_frac) * max(0.0, survival_frac)


@dataclass
class RoomLighting:
    """The lumen-method result for a room."""

    average_lux: float
    total_flux_lm: float
    room_index: float
    utilisation_factor: float
    light_loss_factor: float
    power_w: float
    power_density_w_per_m2: float       # the number energy codes are written in
    efficacy_lm_per_w: float
    lux_per_w_per_m2: float             # delivered lux per installed W/m^2

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def lumen_method(
    flux_per_luminaire_lm: float,
    n_luminaires: int,
    length_m: float,
    width_m: float,
    mounting_height_m: float,
    power_per_luminaire_w: float = 0.0,
    ceiling_reflectance: float = 0.7,
    wall_reflectance: float = 0.5,
    floor_reflectance: float = 0.2,
    lumen_maintenance: float = 1.0,
    dirt_frac: float = 0.0,
) -> RoomLighting:
    """Average maintained illuminance in a room, by the lumen method."""
    area = max(length_m * width_m, 1e-9)
    total_flux = flux_per_luminaire_lm * max(n_luminaires, 0)
    ri = room_index(length_m, width_m, mounting_height_m)
    uf = utilisation_factor(ri, ceiling_reflectance, wall_reflectance, floor_reflectance)
    llf = light_loss_factor(lumen_maintenance, dirt_frac)
    average = total_flux * uf * llf / area
    power = power_per_luminaire_w * max(n_luminaires, 0)
    density = power / area
    return RoomLighting(
        average_lux=round(average, 2),
        total_flux_lm=round(total_flux, 1),
        room_index=round(ri, 3),
        utilisation_factor=round(uf, 4),
        light_loss_factor=round(llf, 4),
        power_w=round(power, 2),
        power_density_w_per_m2=round(density, 3),
        efficacy_lm_per_w=round(total_flux / power, 2) if power > 0 else 0.0,
        lux_per_w_per_m2=round(average / density, 2) if density > 0 else 0.0,
    )


def luminaires_for_target(
    target_lux: float,
    flux_per_luminaire_lm: float,
    length_m: float,
    width_m: float,
    mounting_height_m: float,
    ceiling_reflectance: float = 0.7,
    wall_reflectance: float = 0.5,
    floor_reflectance: float = 0.2,
    lumen_maintenance: float = 1.0,
    dirt_frac: float = 0.0,
) -> int:
    """How many luminaires the lumen method says a target illuminance needs.

    Rounded *up* -- under-lighting a space is the failure mode that gets noticed.
    """
    if flux_per_luminaire_lm <= 0 or target_lux <= 0:
        return 0
    area = max(length_m * width_m, 1e-9)
    ri = room_index(length_m, width_m, mounting_height_m)
    uf = utilisation_factor(ri, ceiling_reflectance, wall_reflectance, floor_reflectance)
    llf = light_loss_factor(lumen_maintenance, dirt_frac)
    denom = flux_per_luminaire_lm * uf * llf
    if denom <= 0:
        return 0
    return max(1, math.ceil(target_lux * area / denom))


def task_lux(task: str) -> float:
    """Standard-practice illuminance for a named task, in lux."""
    key = str(task).lower().replace(" ", "_")
    if key not in TASK_ILLUMINANCE_LUX:
        raise ValueError(
            f"unknown lighting task '{task}' (use one of {', '.join(sorted(TASK_ILLUMINANCE_LUX))})"
        )
    return TASK_ILLUMINANCE_LUX[key]
