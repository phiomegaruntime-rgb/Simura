"""The floor plan interchange contract.

:class:`FloorPlan` is to this package what :class:`~simura.weather.sample.WeatherSample`
is to the weather package: the single, stable, serializable shape that everything
else consumes. Five importers produce it, four simulators read it, the dashboard
draws it, the 3D world extrudes it, and the library stores it -- and none of them
know about each other.

That single shape is the whole design. A building model is enormous, vendor-shaped
and semi-structured; the moment more than one consumer parses one directly, the
project acquires as many opinions about what a room is as it has features. So the
parsing happens exactly once, at the edge, and produces this:

    plan
      georeference      where on Earth the building stands, and which way it faces
      levels[]          storeys, by elevation
      spaces[]          rooms: a polygon, a height, and what the room is *for*
      walls[]           an axis, a thickness, a height
      openings[]        doors and windows, positioned along their wall
      fidelity          what the import could not read (see fidelity.py)

**Metres, always.** Building files arrive in millimetres, feet, inches and
occasionally survey feet, and the unit is the single most common way a BIM import
goes wrong -- silently, by a factor of a thousand, producing a plausible-looking
plan of a building the size of a desk. Conversion happens in the importer, the
result is metres everywhere below this line, and the original unit is recorded so
a suspicious number can be traced.

**Plain data, always.** No live objects, no parser handles, no file references
that have to still be valid. A plan is JSON, which is what lets it travel into a
``SystemSpec``, into a library entry, into ``localStorage`` in the browser, and
back out unchanged -- exactly as a ``SystemSpec`` is a recipe rather than a
simulator.

The ``id`` is a **content hash**, for the same reason a library entry's is: two
imports of the same bytes are the same plan and should collapse to one, and an
edited building is a different plan rather than a mutation of the old one. What
somebody designed against remains fetchable after the model moved on.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Sequence

from .fidelity import Fidelity
from .geometry import (
    Point,
    Polygon,
    bounds_union,
    ensure_ccw,
    normalize_polygon,
    oriented_extents,
    polygon_area,
    polygon_bounds,
    polygon_centroid,
    polyline_length,
)

# Occupancy classes the plan normalises room names onto.
#
# These are *exactly* the keys `simura.lights` already speaks -- the same strings
# key its task-illuminance table and its installed power-density limits -- plus
# "unknown". That identity is deliberate: it means an imported room arrives with
# a lighting target already attached, and the coupling in `couple.py` is a lookup
# rather than a translation table nobody maintains. A room classified "unknown" is
# one the importer refused to guess about, and the lighting coupling says so
# instead of quietly lighting it to 500 lux.
OCCUPANCY = (
    "office",
    "classroom",
    "corridor",
    "lobby",
    "storage",
    "workshop",
    "drawing_office",
    "inspection",
    "surgery",
    "residential_general",
    "kitchen",
    "sports_hall",
    "warehouse_aisle",
    "car_park",
    "street_residential",
    "street_main",
    "unknown",
)


@dataclass(frozen=True)
class Georeference:
    """Where the building stands, and which way it faces.

    This is the join to :mod:`simura.weather`, and it is the reason a BIM import
    is worth more than its geometry: a model that carries ``IfcSite`` coordinates
    already knows the latitude and longitude the weather provider needs, so
    importing a building *configures the sky over it* with nothing typed in.

    ``north_deg`` is the true-north bearing of the plan's ``+y`` axis, clockwise.
    Project north is almost never true north, and the difference is not cosmetic:
    it decides which facades take morning sun, which is what drives both solar
    gain on the conductors and the daylight a photocell sees.
    """

    latitude: float | None = None
    longitude: float | None = None
    elevation_m: float | None = None
    north_deg: float = 0.0
    address: str = ""

    @property
    def located(self) -> bool:
        """True when there are real coordinates -- i.e. weather can be fetched."""
        return self.latitude is not None and self.longitude is not None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Georeference":
        d = d or {}
        return cls(
            latitude=_opt_float(d.get("latitude")),
            longitude=_opt_float(d.get("longitude")),
            elevation_m=_opt_float(d.get("elevation_m")),
            north_deg=float(d.get("north_deg", 0.0)),
            address=str(d.get("address", "")),
        )


@dataclass(frozen=True)
class Level:
    """A storey: a name, the height its floor sits at, and how tall it is."""

    id: str
    name: str = ""
    elevation_m: float = 0.0
    height_m: float = 3.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Level":
        return cls(
            id=str(d["id"]),
            name=str(d.get("name", "")),
            elevation_m=float(d.get("elevation_m", 0.0)),
            height_m=float(d.get("height_m", 3.0)),
        )


@dataclass(frozen=True)
class Space:
    """A room: a closed polygon, a ceiling height, and what it is for.

    ``occupancy`` is the field that makes a space *simulable* rather than merely
    drawn. It is normalised onto :data:`OCCUPANCY` from whatever the file called
    the room, so "Open Plan Office 2.04" and "BUERO" both arrive as ``office`` and
    both carry the 500 lx a lighting standard asks of one.

    ``inferred`` names the fields on **this** space that the importer supplied
    rather than read. It duplicates what the plan's :class:`~simura.space.fidelity.Fidelity`
    record holds in full, deliberately: a consumer rendering one room should not
    have to hold the whole import log to know that its ceiling height is a guess.
    """

    id: str
    name: str = ""
    level_id: str = ""
    polygon: Polygon = field(default_factory=list)
    height_m: float = 2.7
    occupancy: str = "unknown"
    # Whether the room is climate-controlled. `None` means the file did not say.
    # This is what decides whether a system standing here follows the weather or
    # sits at a setpoint -- see `simura.space.couple.ambient_for`.
    conditioned: bool | None = None
    setpoint_c: float | None = None
    # Surface reflectances, when the model carries them. The lumen method needs
    # all three; where the file is silent, the importer records defaults.
    ceiling_reflectance: float = 0.7
    wall_reflectance: float = 0.5
    floor_reflectance: float = 0.2
    inferred: list[str] = field(default_factory=list)

    # -- measurements -----------------------------------------------------
    @property
    def area_m2(self) -> float:
        return polygon_area(self.polygon)

    @property
    def centroid(self) -> Point:
        return polygon_centroid(self.polygon)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return polygon_bounds(self.polygon)

    @property
    def perimeter_m(self) -> float:
        from .geometry import polygon_perimeter

        return polygon_perimeter(self.polygon)

    def extents(self) -> tuple[float, float, float]:
        """``(length_m, width_m, angle_deg)`` of the best-fit rectangle.

        The lumen method wants a rectangle; a real room is not one. See
        :func:`simura.space.geometry.oriented_extents` for what this claims, and
        note that a consumer using it on a non-rectangular room owes the reader a
        label -- :meth:`rectangular` is how to find out.
        """
        return oriented_extents(self.polygon)

    def rectangular(self, tol: float = 0.02) -> bool:
        """True when the room really is a rectangle, to within ``tol`` of its area.

        The test that decides whether ``extents()`` is a measurement or an
        approximation, so a consumer can say which it used.
        """
        length, width, _ = self.extents()
        box = length * width
        if box <= 0:
            return False
        return abs(box - self.area_m2) / box <= tol

    def contains(self, pt: Point) -> bool:
        from .geometry import point_in_polygon

        return point_in_polygon(pt, self.polygon)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["polygon"] = [[round(x, 5), round(y, 5)] for x, y in self.polygon]
        # Measurements are included so a consumer that never imports this package
        # -- the dashboard, the world -- gets them without recomputing geometry.
        d["area_m2"] = round(self.area_m2, 4)
        cx, cy = self.centroid
        d["centroid"] = [round(cx, 5), round(cy, 5)]
        length, width, angle = self.extents()
        d["length_m"] = round(length, 4)
        d["width_m"] = round(width, 4)
        d["angle_deg"] = round(angle, 3)
        d["rectangular"] = self.rectangular()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Space":
        return cls(
            id=str(d["id"]),
            name=str(d.get("name", "")),
            level_id=str(d.get("level_id", "")),
            polygon=normalize_polygon(d.get("polygon", [])),
            height_m=float(d.get("height_m", 2.7)),
            occupancy=str(d.get("occupancy", "unknown")),
            conditioned=_opt_bool(d.get("conditioned")),
            setpoint_c=_opt_float(d.get("setpoint_c")),
            ceiling_reflectance=float(d.get("ceiling_reflectance", 0.7)),
            wall_reflectance=float(d.get("wall_reflectance", 0.5)),
            floor_reflectance=float(d.get("floor_reflectance", 0.2)),
            inferred=list(d.get("inferred", [])),
        )


@dataclass(frozen=True)
class Wall:
    """A wall, as its centre-line axis plus a thickness and a height.

    Axis-and-thickness rather than a solid, because that is what both consumers
    need and neither needs more: the 2D view strokes the axis at the thickness,
    and the world extrudes a box along it. Storing the swept solid the file
    actually contains would mean carrying a geometry kernel into the browser to
    get back the two numbers that were there all along.
    """

    id: str
    level_id: str = ""
    axis: list[Point] = field(default_factory=list)
    thickness_m: float = 0.2
    height_m: float = 3.0
    exterior: bool = False
    inferred: list[str] = field(default_factory=list)

    @property
    def length_m(self) -> float:
        return polyline_length(self.axis)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["axis"] = [[round(x, 5), round(y, 5)] for x, y in self.axis]
        d["length_m"] = round(self.length_m, 4)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Wall":
        return cls(
            id=str(d["id"]),
            level_id=str(d.get("level_id", "")),
            axis=[(float(p[0]), float(p[1])) for p in d.get("axis", [])],
            thickness_m=float(d.get("thickness_m", 0.2)),
            height_m=float(d.get("height_m", 3.0)),
            exterior=bool(d.get("exterior", False)),
            inferred=list(d.get("inferred", [])),
        )


@dataclass(frozen=True)
class Opening:
    """A door or a window, positioned along its wall.

    ``along_m`` is the distance from the start of the wall axis to the opening's
    centre. Doors matter to routing (a cable goes through one, not through a
    wall) and to the world (a doorway is a gap you can walk through); windows
    matter to daylight, which :mod:`simura.lights` already models.
    """

    id: str
    wall_id: str = ""
    kind: str = "door"  # "door" | "window" | "opening"
    along_m: float = 0.0
    width_m: float = 0.9
    height_m: float = 2.1
    sill_m: float = 0.0
    inferred: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Opening":
        return cls(
            id=str(d["id"]),
            wall_id=str(d.get("wall_id", "")),
            kind=str(d.get("kind", "door")),
            along_m=float(d.get("along_m", 0.0)),
            width_m=float(d.get("width_m", 0.9)),
            height_m=float(d.get("height_m", 2.1)),
            sill_m=float(d.get("sill_m", 0.0)),
            inferred=list(d.get("inferred", [])),
        )


@dataclass
class FloorPlan:
    """A building, reduced to the 2D layout a simulator can stand in.

    See the module docstring for the shape and the reasoning. The one thing worth
    repeating here: ``id`` is derived from the content, so constructing the same
    plan twice gives the same id and importing a changed model gives a new one.
    """

    name: str = ""
    id: str = ""
    georeference: Georeference = field(default_factory=Georeference)
    levels: list[Level] = field(default_factory=list)
    spaces: list[Space] = field(default_factory=list)
    walls: list[Wall] = field(default_factory=list)
    openings: list[Opening] = field(default_factory=list)
    fidelity: Fidelity = field(default_factory=Fidelity)
    # The unit the source file was written in, before conversion to metres.
    # Kept because a plan that is out by 1000x is out by exactly this.
    source_units: str = "m"
    imported_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        # Normalise on the way in, once, so no consumer has to defend against a
        # repeated vertex or an inconsistent winding.
        self.spaces = [
            Space(**{**s.__dict__, "polygon": ensure_ccw(normalize_polygon(s.polygon))})
            for s in self.spaces
        ]
        if not self.id:
            self.id = self.content_hash()

    # -- identity ---------------------------------------------------------
    def content_hash(self) -> str:
        """A stable 16-hex-character fingerprint of the geometry and semantics.

        Deliberately *excludes* ``fidelity`` and ``imported_at``: two importers
        that produce the same building have produced the same plan, even if one
        of them had to guess more to get there. The fidelity record describes the
        import; the hash identifies the building.
        """
        payload = {
            "name": self.name,
            "georeference": self.georeference.to_dict(),
            "levels": [level.to_dict() for level in self.levels],
            "spaces": [s.to_dict() for s in self.spaces],
            "walls": [w.to_dict() for w in self.walls],
            "openings": [o.to_dict() for o in self.openings],
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    # -- lookups ----------------------------------------------------------
    def space(self, space_id: str) -> Space | None:
        return next((s for s in self.spaces if s.id == space_id), None)

    def level(self, level_id: str) -> Level | None:
        return next((level for level in self.levels if level.id == level_id), None)

    def wall(self, wall_id: str) -> Wall | None:
        return next((w for w in self.walls if w.id == wall_id), None)

    def spaces_on(self, level_id: str) -> list[Space]:
        return [s for s in self.spaces if s.level_id == level_id]

    def walls_on(self, level_id: str) -> list[Wall]:
        return [w for w in self.walls if w.level_id == level_id]

    def openings_in(self, wall_id: str) -> list[Opening]:
        return [o for o in self.openings if o.wall_id == wall_id]

    def space_at(self, pt: Point, level_id: str | None = None) -> Space | None:
        """The room a point falls in -- how a placed rack learns where it stands."""
        for s in self.spaces:
            if level_id is not None and s.level_id != level_id:
                continue
            if s.contains(pt):
                return s
        return None

    # -- measurements -----------------------------------------------------
    @property
    def floor_area_m2(self) -> float:
        return sum(s.area_m2 for s in self.spaces)

    def bounds(self) -> tuple[float, float, float, float]:
        """The building's footprint box, spaces and walls together."""
        boxes = [s.bounds for s in self.spaces]
        boxes += [polygon_bounds(w.axis) for w in self.walls if w.axis]
        return bounds_union(boxes)

    def size_m(self) -> tuple[float, float]:
        min_x, min_y, max_x, max_y = self.bounds()
        return (max_x - min_x, max_y - min_y)

    def recentre(self) -> "FloorPlan":
        """The same plan with its footprint centred on the origin.

        The world's ground plane is centred on ``(0, 0)`` and only 320 m across, so
        a model georeferenced to a national grid would otherwise arrive somewhere
        past the fog. Recentring is a *view* decision, so it produces a new plan
        rather than moving the imported one under everybody's feet.
        """
        min_x, min_y, max_x, max_y = self.bounds()
        dx, dy = -(min_x + max_x) / 2.0, -(min_y + max_y) / 2.0
        return FloorPlan(
            name=self.name,
            georeference=self.georeference,
            levels=list(self.levels),
            spaces=[
                Space(**{**s.__dict__, "polygon": [(x + dx, y + dy) for x, y in s.polygon]})
                for s in self.spaces
            ],
            walls=[
                Wall(**{**w.__dict__, "axis": [(x + dx, y + dy) for x, y in w.axis]})
                for w in self.walls
            ],
            openings=list(self.openings),
            fidelity=self.fidelity,
            source_units=self.source_units,
            imported_at=self.imported_at,
        )

    # -- serialization ----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source_units": self.source_units,
            "imported_at": self.imported_at,
            "georeference": self.georeference.to_dict(),
            "levels": [level.to_dict() for level in self.levels],
            "spaces": [s.to_dict() for s in self.spaces],
            "walls": [w.to_dict() for w in self.walls],
            "openings": [o.to_dict() for o in self.openings],
            "fidelity": self.fidelity.to_dict(),
            "floor_area_m2": round(self.floor_area_m2, 3),
            "bounds": [round(v, 4) for v in self.bounds()],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FloorPlan":
        return cls(
            name=str(d.get("name", "")),
            id=str(d.get("id", "")),
            georeference=Georeference.from_dict(d.get("georeference")),
            levels=[Level.from_dict(x) for x in d.get("levels", [])],
            spaces=[Space.from_dict(x) for x in d.get("spaces", [])],
            walls=[Wall.from_dict(x) for x in d.get("walls", [])],
            openings=[Opening.from_dict(x) for x in d.get("openings", [])],
            fidelity=Fidelity.from_dict(d.get("fidelity", {})),
            source_units=str(d.get("source_units", "m")),
            imported_at=float(d.get("imported_at", time.time())),
        )

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "FloorPlan":
        return cls.from_dict(json.loads(text))


def _opt_float(v: Any) -> float | None:
    return None if v is None or v == "" else float(v)


def _opt_bool(v: Any) -> bool | None:
    return None if v is None else bool(v)


def make_levels(elevations: Iterable[float], prefix: str = "level") -> list[Level]:
    """Levels from a list of floor elevations, each as tall as the gap above it.

    Shared by the importers that get storey elevations but no storey heights --
    which is most of them, since a storey's height is a property of the space
    between two floors rather than a thing models usually state.
    """
    els = sorted(float(e) for e in elevations)
    out: list[Level] = []
    for i, elevation in enumerate(els):
        gap = (els[i + 1] - elevation) if i + 1 < len(els) else 3.0
        out.append(
            Level(
                id=f"{prefix}-{i}",
                name=f"Level {i}",
                elevation_m=elevation,
                height_m=gap if gap > 0.1 else 3.0,
            )
        )
    return out


def polygon_from_points(points: Sequence[Sequence[float]]) -> Polygon:
    """Normalised, counter-clockwise ring from raw coordinate pairs."""
    return ensure_ccw(normalize_polygon(points))
