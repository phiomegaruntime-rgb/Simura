"""Where the building meets the simulators.

An importer that nothing consumes is a viewer. This module is the half that makes
:mod:`simura.space` a *component*: it turns a floor plan into the arguments the
existing physics already takes, for each of the three things a plan can tell a
simulation.

It follows the rule the weather package established and never breaks: **the
domain-agnostic package does not import the domain packages.** Nothing here
imports :mod:`simura.lights` or :mod:`simura.wires`. Every function returns plain
values and plain dicts that happen to be exactly the keyword arguments those
libraries already accept, so the dependency arrow points one way and a plan can
be lifted out of Simura with the couplings intact.

What a plan tells each component
--------------------------------

**Weather — where on Earth this is.** The strongest join, and the least obvious
before you see it. A model that carries ``IfcSite`` coordinates already knows the
latitude and longitude :mod:`simura.weather` needs, so importing a building
*configures the sky over it* with nothing typed in. :func:`weather_spec` returns
the provider spec; it is the same dict a person would otherwise fill in by hand
after looking the address up.

**Lights — how big each room is and what it is for.** :func:`lighting_targets`
turns every space into a call to ``recommend_lamp`` or ``evaluate_installation``,
carrying the room's real extents, its ceiling height, its reflectances and the
lighting task implied by its occupancy. This is the coupling that scales: one
import gives a per-room lighting design for a whole building, and a rollup of
what that costs in installed watts.

**Batteries and wires — what the room does to the environment.** The subtle one.
A rack in a plant room and the same rack in a yard are the same design in two
different environments, and until now that difference had to be typed in as an
ambient temperature somebody guessed. A space says whether it is conditioned, so
:func:`ambient_for` can answer with a *reason*: this room is conditioned, so the
pack sits at its setpoint and the sun never reaches it; this one is not, so the
weather applies in full.

The commitment, again
---------------------

Every function here returns its **basis** alongside its value, and propagates
whether the underlying number was read or inferred. A lighting target computed
from a room whose ceiling height was assumed carries that fact into the result,
so the design report can say so. See :mod:`simura.space.fidelity` for why that is
non-negotiable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .plan import FloorPlan, Space

# Illuminance is specified at the working plane, not the floor: 0.8 m for a desk,
# 0.0 m for a corridor or a store where the floor is the task. Mounting height in
# the lumen method is measured from that plane to the luminaire, so this is what
# gets subtracted from the ceiling height.
WORKING_PLANE_M: dict[str, float] = {
    "office": 0.8,
    "classroom": 0.8,
    "drawing_office": 0.8,
    "inspection": 0.9,
    "surgery": 1.0,
    "kitchen": 0.9,
    "workshop": 0.9,
    "residential_general": 0.8,
    "corridor": 0.0,
    "lobby": 0.0,
    "storage": 0.0,
    "warehouse_aisle": 0.0,
    "sports_hall": 0.0,
    "car_park": 0.0,
    "street_residential": 0.0,
    "street_main": 0.0,
}

# The band a conditioned space is held in when the model does not say. A building
# that states a setpoint gets its own; this is the fallback, and it is recorded
# as one.
DEFAULT_SETPOINT_C = 21.0

# The task grid is inset from the walls, because the strip against a wall is not
# somewhere anybody works and including it drags every uniformity figure down.
# Half a metre is the usual convention.
DEFAULT_TASK_INSET_M = 0.5


# ---------------------------------------------------------------------------
# Weather: where on Earth the building is
# ---------------------------------------------------------------------------

def weather_spec(
    plan: FloorPlan, mode: str = "forecast", cached: bool = True
) -> dict[str, Any] | None:
    """The :mod:`simura.weather` provider spec implied by the model, or ``None``.

    Returns the ``open_meteo`` spec pointed at the building's own coordinates.
    ``None`` when the model carries no georeference -- which is common, and is a
    *fact about the file* rather than a failure, so the caller keeps whatever
    weather it already had rather than being handed coordinates of ``0, 0`` in the
    Gulf of Guinea.
    """
    geo = plan.georeference
    if not geo.located:
        return None
    return {
        "type": "open_meteo",
        "latitude": round(float(geo.latitude), 6),
        "longitude": round(float(geo.longitude), 6),
        "mode": mode,
        "cached": cached,
    }


def orientation_deg(plan: FloorPlan) -> float:
    """True-north bearing of the plan's ``+y`` axis.

    What decides which facades take morning sun -- and therefore which rooms
    daylight-harvest early and which conductors take solar gain when. Zero means
    project north and true north coincide, which most models assert and few mean.
    """
    return float(plan.georeference.north_deg)


# ---------------------------------------------------------------------------
# Batteries and wires: what the room does to the environment
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SpaceContext:
    """The environment a system standing in one room is actually in.

    ``basis`` is the sentence that explains ``ambient_c``, and ``stated`` says
    whether the model declared the room's conditioning or the importer worked it
    out. A caller showing an ambient to somebody should show the basis with it.
    """

    space_id: str
    name: str
    occupancy: str
    indoor: bool
    ambient_c: float
    shading_frac: float
    basis: str
    stated: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def coupling_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for an ``EnvironmentCoupling``.

        The physically meaningful part: **an indoor room is what stops the weather
        reaching the equipment.** ``shading_frac=1`` is not a fudge -- it is the
        statement that no sunlight lands on a cabinet inside a building, which is
        true, and which the existing coupling in :mod:`simura.sim.environment`
        already knows what to do with.
        """
        return {"shading_frac": self.shading_frac}


def ambient_for(
    plan: FloorPlan,
    space_id: str,
    sample: Any = None,
    indoor_setpoint_c: float = DEFAULT_SETPOINT_C,
) -> SpaceContext | None:
    """The ambient a system in ``space_id`` stands in, and why.

    ``sample`` is an optional :class:`~simura.weather.sample.WeatherSample` (duck
    typed, so this module still imports nothing). It is used only for a room the
    weather actually reaches.

    Three cases, and the third is the one worth reading:

    * the model says the room is **conditioned** -> its setpoint, sun excluded;
    * the model says it is **not** -> the weather, in full;
    * the model **does not say** -> treated as outdoor, and ``stated`` is false.

    Defaulting an unknown room to indoors would be the comfortable choice and the
    wrong one: it hides the weather coupling behind a guess, and a battery that
    quietly stops responding to a heatwave because a BIM field was blank is a
    worse outcome than one that responds to weather it should have been shielded
    from. The unshielded answer is at least visibly wrong.
    """
    space = plan.space(space_id)
    if space is None:
        return None

    outdoor_c = float(getattr(sample, "air_temp_c", 20.0)) if sample is not None else 20.0

    if space.conditioned is True:
        setpoint = space.setpoint_c if space.setpoint_c is not None else indoor_setpoint_c
        stated_setpoint = space.setpoint_c is not None
        basis = (
            f"the model marks {space.name or space.id} as conditioned, so it holds "
            f"{setpoint:.1f} °C"
            + ("" if stated_setpoint else " (no setpoint in the model; assumed)")
        )
        return SpaceContext(
            space_id=space.id,
            name=space.name,
            occupancy=space.occupancy,
            indoor=True,
            ambient_c=float(setpoint),
            shading_frac=1.0,
            basis=basis,
            stated=True,
        )

    if space.conditioned is False:
        return SpaceContext(
            space_id=space.id,
            name=space.name,
            occupancy=space.occupancy,
            indoor=False,
            ambient_c=outdoor_c,
            shading_frac=0.0,
            basis=(
                f"the model marks {space.name or space.id} as unconditioned, so the "
                f"weather applies in full"
            ),
            stated=True,
        )

    return SpaceContext(
        space_id=space.id,
        name=space.name,
        occupancy=space.occupancy,
        indoor=False,
        ambient_c=outdoor_c,
        shading_frac=0.0,
        basis=(
            f"the model does not say whether {space.name or space.id} is "
            f"conditioned, so the weather is applied unshielded — see the plan's "
            f"fidelity record"
        ),
        stated=False,
    )


def space_at(plan: FloorPlan, x_m: float, y_m: float, level_id: str | None = None):
    """The room a placed thing stands in -- how a rack learns where it is.

    The 3D world's whole use of this component in one call: a rack is placed at a
    position, and this says which room that position is in, which is what gives it
    an ambient, an occupancy and a name without anybody typing one.
    """
    return plan.space_at((float(x_m), float(y_m)), level_id)


# ---------------------------------------------------------------------------
# Lights: how big each room is and what it is for
# ---------------------------------------------------------------------------

@dataclass
class LightingTarget:
    """One room, ready to be handed to :mod:`simura.lights`.

    :meth:`kwargs` is literally the argument list of
    ``simura.lights.planning.recommend_lamp`` -- that identity is the point, and
    it is why the occupancy vocabulary was made to match the lighting task
    vocabulary rather than translated between them.
    """

    space_id: str
    name: str
    level_id: str
    task: str
    length_m: float
    width_m: float
    area_m2: float
    mounting_height_m: float
    ceiling_height_m: float
    working_plane_m: float
    ceiling_reflectance: float
    wall_reflectance: float
    floor_reflectance: float
    polygon: list[list[float]] = field(default_factory=list)
    # True when the room really is a rectangle, so length x width is a
    # measurement. False means it is a best-fit rectangle and every lumen-method
    # number derived from it is an approximation of a shape it is not.
    rectangular: bool = True
    # Fields on this room the importer supplied rather than read.
    inferred: list[str] = field(default_factory=list)
    # Why this room cannot be designed as-is, if it cannot.
    problems: list[str] = field(default_factory=list)

    @property
    def designable(self) -> bool:
        return not self.problems

    def kwargs(self) -> dict[str, Any]:
        """Keyword arguments for ``recommend_lamp`` / ``evaluate_installation``."""
        return {
            "length_m": self.length_m,
            "width_m": self.width_m,
            "mounting_height_m": self.mounting_height_m,
            "task": self.task,
            "ceiling_reflectance": self.ceiling_reflectance,
            "wall_reflectance": self.wall_reflectance,
            "floor_reflectance": self.floor_reflectance,
        }

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["designable"] = self.designable
        return d


def lighting_targets(
    plan: FloorPlan,
    level_id: str | None = None,
    mounting_height_m: float | None = None,
    min_area_m2: float = 1.0,
) -> list[LightingTarget]:
    """Every room in the plan, as a lighting-design problem.

    ``mounting_height_m`` overrides the derived value for every room; leave it
    ``None`` and each room gets ``ceiling height - working plane``, which is what
    the lumen method means by mounting height and what varies room to room.

    A room the plan cannot honestly design is still returned, with its reason in
    ``problems`` -- so a building rollup reports "38 of 41 rooms designed, 3
    without an occupancy" rather than silently covering 38.
    """
    out: list[LightingTarget] = []
    for space in plan.spaces:
        if level_id is not None and space.level_id != level_id:
            continue
        if space.area_m2 < min_area_m2:
            continue
        out.append(_target(space, mounting_height_m))
    return out


def _target(space: Space, mounting_height_m: float | None) -> LightingTarget:
    length, width, _angle = space.extents()
    rectangular = space.rectangular()
    plane = WORKING_PLANE_M.get(space.occupancy, 0.8)
    mount = (
        float(mounting_height_m)
        if mounting_height_m is not None
        else max(0.5, space.height_m - plane)
    )

    problems: list[str] = []
    if space.occupancy == "unknown":
        problems.append(
            "no occupancy could be worked out for this room, so there is no "
            "illuminance target to design to — name it or set its type"
        )
    if not rectangular:
        problems.append(
            f"the room is not rectangular, so the lumen method is being applied to "
            f"a {length:.1f} x {width:.1f} m best-fit rectangle "
            f"({length * width:.1f} m² against the room's actual {space.area_m2:.1f} m²)"
        )
    if "height_m" in space.inferred:
        problems.append(
            "the ceiling height was assumed rather than read from the model, and "
            "mounting height is what the room index is built on"
        )

    return LightingTarget(
        space_id=space.id,
        name=space.name,
        level_id=space.level_id,
        task=space.occupancy if space.occupancy != "unknown" else "office",
        length_m=round(length, 4),
        width_m=round(width, 4),
        area_m2=round(space.area_m2, 4),
        mounting_height_m=round(mount, 4),
        ceiling_height_m=round(space.height_m, 4),
        working_plane_m=plane,
        ceiling_reflectance=space.ceiling_reflectance,
        wall_reflectance=space.wall_reflectance,
        floor_reflectance=space.floor_reflectance,
        polygon=[[round(x, 4), round(y, 4)] for x, y in space.polygon],
        rectangular=rectangular,
        inferred=list(space.inferred),
        problems=problems,
    )


def task_grid(
    plan: FloorPlan, space_id: str, spacing_m: float = 0.5, inset_m: float | None = None
) -> list[tuple[float, float]]:
    """Grid points inside a room's real outline, for an illuminance field.

    This is what lets :func:`simura.lights.layout.solve_layout` be evaluated over
    the room a building actually has rather than over the rectangle that stands in
    for it -- which matters most in exactly the rooms where the rectangle is
    worst: L-shapes, and anything with a re-entrant corner where the lumen method
    quietly reports a uniformity the corner never sees.
    """
    from .geometry import grid_points

    space = plan.space(space_id)
    if space is None:
        return []
    inset = DEFAULT_TASK_INSET_M if inset_m is None else float(inset_m)
    return grid_points(space.polygon, spacing_m, inset)


# ---------------------------------------------------------------------------
# The whole building, at a glance
# ---------------------------------------------------------------------------

def summary(plan: FloorPlan) -> dict[str, Any]:
    """A rollup of what was imported -- the header of every plan view."""
    from .occupancy import counts

    width, depth = plan.size_m()
    geo = plan.georeference
    return {
        "id": plan.id,
        "name": plan.name,
        "levels": len(plan.levels),
        "spaces": len(plan.spaces),
        "walls": len(plan.walls),
        "openings": len(plan.openings),
        "floor_area_m2": round(plan.floor_area_m2, 2),
        "size_m": [round(width, 2), round(depth, 2)],
        "occupancies": counts(s.occupancy for s in plan.spaces),
        "unknown_rooms": sum(1 for s in plan.spaces if s.occupancy == "unknown"),
        "non_rectangular_rooms": sum(1 for s in plan.spaces if not s.rectangular()),
        "located": geo.located,
        "latitude": geo.latitude,
        "longitude": geo.longitude,
        "north_deg": geo.north_deg,
        "weather": weather_spec(plan),
        "source_units": plan.source_units,
        "fidelity": plan.fidelity.to_dict(),
    }
