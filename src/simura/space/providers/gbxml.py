"""gbXML: the format that already thinks in rooms.

Of the three real building formats this package reads, gbXML is the one whose
model of a building most nearly matches the one Simura needs. It was designed to
hand a building to an energy simulation, so it is *already* a list of spaces with
polygons, a space type from a closed enumeration, a conditioning flag, and a
latitude and longitude -- the four things that turn geometry into something that
can be simulated. IFC has all of it too, buried under a geometry kernel; gbXML
has it in the first two levels of the tree.

That makes it the best format to read this component's parsing story in, and it
is why the test fixtures are written in it.

What is read
------------

``Campus/Location``      latitude, longitude, elevation, postcode
``Building/BuildingStorey``  a level and its elevation
``Space``                a room: its ``PlanarGeometry`` floor loop, its
                         ``spaceType``, its ``conditionType``, its area and volume
``Surface``              walls, from the vertical ones; their exterior/interior
                         status is stated rather than guessed
``Opening``              doors and windows, positioned along their wall

What is not
-----------

Non-vertical surfaces (roofs, floors, slabs) are counted and skipped: they are
real, they are not part of a 2D layout, and saying so is cheaper than leaving
somebody to wonder where they went. Curved surfaces have no gbXML representation
worth reading. Constructions and materials are ignored except where they give a
wall its thickness.

The height question
-------------------

A gbXML ``Space`` states its area and often its volume but rarely its height, and
the height is what the lumen method needs. So it is derived, in order of how much
the file actually said:

1. ``Volume / Area`` when both are present -- a measurement, near enough.
2. The z-extent of the space's own vertical surfaces.
3. The storey height from the level above.
4. 2.7 m, and the plan says so.

Each of the four is a different quality of answer, and which one was used lands in
the fidelity record by name. That is the difference between "the room is 2.7 m
high" and "we had nothing, so we said 2.7".
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from .. import units
from ..fidelity import FidelityLog
from ..geometry import distance, normalize_polygon, polygon_area
from ..occupancy import classify
from ..plan import FloorPlan, Georeference, Level, Opening, Space, Wall
from ..provider import PlanError
from .file import FilePlanProvider

# A surface this far off vertical is a roof or a floor, not a wall. Ten degrees
# is generous enough for a model whose walls are a fraction off plumb and tight
# enough that a shallow-pitched roof never arrives as a very confusing wall.
VERTICAL_TOL = 0.17  # |dz_normal| tolerance, ~10 degrees

DEFAULT_HEIGHT_M = 2.7
DEFAULT_WALL_THICKNESS_M = 0.2


class GbxmlProvider(FilePlanProvider):
    """A floor plan from a gbXML file."""

    format = "gbxml"

    def _parse(self, log: FidelityLog) -> FloorPlan:
        try:
            root = ET.fromstring(self.text())
        except ET.ParseError as exc:
            raise PlanError(f"{self.name} is not valid XML: {exc}") from None
        _strip_namespaces(root)
        if root.tag != "gbXML":
            raise PlanError(f"{self.name} is not a gbXML document (root is <{root.tag}>)")

        scale, unit_name = self._resolve_units(root, log)
        georef = self._read_location(root, log)
        levels = self._read_levels(root, scale, log)
        spaces, surfaces, volumes = self._read_spaces(root, scale, levels, log)
        walls, openings = self._read_surfaces(surfaces, scale, spaces, log)
        spaces = self._resolve_heights(spaces, surfaces, levels, volumes, scale, log)

        if not spaces and not walls:
            raise PlanError(
                f"{self.name} parsed, but contains no spaces and no wall surfaces"
            )

        plan = FloorPlan(
            name=_text(root.find(".//Building/Name")) or _text(root.find(".//Campus/Name")) or self.name,
            georeference=georef,
            levels=levels,
            spaces=spaces,
            walls=walls,
            openings=openings,
            fidelity=log.freeze(),
            source_units=unit_name,
        )
        width, depth = plan.size_m()
        ok, complaint = units.plausible_building(width, depth)
        if not ok:
            log.warn(complaint)
            plan = FloorPlan(**{**plan.__dict__, "id": "", "fidelity": log.freeze()})
        return plan

    # -- units ------------------------------------------------------------
    def _resolve_units(self, root: ET.Element, log: FidelityLog) -> tuple[float, str]:
        raw = root.get("lengthUnit", "")
        mapping = {
            "meters": "m",
            "metres": "m",
            "centimeters": "cm",
            "millimeters": "mm",
            "feet": "ft",
            "inches": "in",
        }
        key = mapping.get(str(raw).strip().lower(), "")
        if key:
            return (units.factor(key), key)
        log.default(
            "plan", "units", "m", "gbXML has no usable lengthUnit attribute; assumed metres"
        )
        return (1.0, "m")

    # -- georeference -----------------------------------------------------
    def _read_location(self, root: ET.Element, log: FidelityLog) -> Georeference:
        loc = root.find(".//Campus/Location")
        if loc is None:
            log.warn(
                "no Campus/Location — the building has no coordinates, so weather "
                "cannot be fetched for it automatically"
            )
            return Georeference()
        log.seen()
        log.used()
        lat = _float(_text(loc.find("Latitude")))
        lon = _float(_text(loc.find("Longitude")))
        # gbXML's Elevation is in the document's length unit; everything else in
        # Location is in degrees, which is a trap worth not falling into.
        elev = _float(_text(loc.find("Elevation")))
        # gbXML's CADModelAzimuth is the bearing of the model's +y axis, which is
        # exactly what `north_deg` means.
        north = _float(_text(root.find(".//Campus/CADModelAzimuth"))) or 0.0
        if north:
            log.seen()
            log.used()
        return Georeference(
            latitude=lat,
            longitude=lon,
            elevation_m=elev,
            north_deg=float(north),
            address=_text(loc.find("ZipcodeOrPostalCode")) or _text(loc.find("Name")),
        )

    # -- levels -----------------------------------------------------------
    def _read_levels(self, root: ET.Element, scale: float, log: FidelityLog) -> list[Level]:
        out: list[Level] = []
        for storey in root.iterfind(".//BuildingStorey"):
            log.seen()
            elevation = _float(storey.get("Level")) or _float(_text(storey.find("Level"))) or 0.0
            out.append(
                Level(
                    id=storey.get("id", f"level-{len(out)}"),
                    name=_text(storey.find("Name")) or storey.get("id", ""),
                    elevation_m=float(elevation) * scale,
                    height_m=3.0,
                )
            )
            log.used()
        out.sort(key=lambda level: level.elevation_m)
        # A storey's height is the gap to the one above it -- derived, so recorded.
        resolved: list[Level] = []
        for i, level in enumerate(out):
            if i + 1 < len(out):
                gap = out[i + 1].elevation_m - level.elevation_m
                if gap > 0.1:
                    height = log.infer(
                        f"level:{level.id}",
                        "height_m",
                        round(gap, 3),
                        "elevation difference to the storey above",
                    )
                    resolved.append(Level(**{**level.__dict__, "height_m": height}))
                    continue
            resolved.append(level)
        if not resolved:
            log.default("plan", "levels", 1, "no BuildingStorey elements; one level assumed")
            resolved = [Level(id="level-0", name="Level 0")]
        return resolved

    # -- spaces -----------------------------------------------------------
    def _read_spaces(
        self, root: ET.Element, scale: float, levels: list[Level], log: FidelityLog
    ) -> tuple[list[Space], list[ET.Element], dict[str, float]]:
        default_level = levels[0].id if levels else "level-0"
        known_levels = {level.id for level in levels}
        spaces: list[Space] = []
        volumes: dict[str, float] = {}
        surfaces = list(root.iterfind(".//Surface"))

        for el in root.iterfind(".//Space"):
            log.seen()
            sid = el.get("id") or f"space-{len(spaces)}"
            loop = el.find("./PlanarGeometry/PolyLoop")
            polygon = _read_loop(loop, scale) if loop is not None else []
            if len(polygon) < 3:
                # A space with no floor loop can often still be recovered from the
                # floor surface that names it -- worth trying before giving up on
                # a room somebody has to light.
                polygon = _floor_loop_for(sid, surfaces, scale)
            if len(polygon) < 3:
                log.skip("Space", "no usable floor polygon (PlanarGeometry or Floor surface)")
                continue

            name = _text(el.find("Name")) or sid
            volume = _float(_text(el.find("Volume")))
            if volume:
                # Stated in the document's length unit cubed.
                volumes[sid] = float(volume) * scale**3
            occupancy, basis = classify(
                name=name, gbxml_space_type=el.get("spaceType", "")
            )
            inferred: list[str] = []
            if occupancy == "unknown":
                log.infer(f"space:{sid}", "occupancy", "unknown", basis)
                inferred.append("occupancy")
            elif not el.get("spaceType"):
                log.infer(f"space:{sid}", "occupancy", occupancy, basis)
                inferred.append("occupancy")

            condition = str(el.get("conditionType", "")).lower()
            conditioned: bool | None
            if not condition:
                conditioned = None
            else:
                conditioned = condition not in ("unconditioned", "naturallyventilatedonly")

            level_id = el.get("buildingStoreyIdRef", "") or default_level
            if level_id not in known_levels:
                level_id = default_level

            spaces.append(
                Space(
                    id=sid,
                    name=name,
                    level_id=level_id,
                    polygon=polygon,
                    height_m=DEFAULT_HEIGHT_M,  # replaced by _resolve_heights
                    occupancy=occupancy,
                    conditioned=conditioned,
                    inferred=inferred,
                )
            )
            log.used()

        return spaces, surfaces, volumes

    # -- heights ----------------------------------------------------------
    def _resolve_heights(
        self,
        spaces: list[Space],
        surfaces: list[ET.Element],
        levels: list[Level],
        volumes: dict[str, float],
        scale: float,
        log: FidelityLog,
    ) -> list[Space]:
        """Four ways to learn a room's height, best first. See the module docstring."""
        by_space = _surfaces_by_space(surfaces)
        level_heights = {level.id: level.height_m for level in levels}
        out: list[Space] = []

        for s in spaces:
            subject = f"space:{s.id}"
            height: float | None = None
            inferred = list(s.inferred)

            volume = volumes.get(s.id)
            if volume and s.area_m2 > 0.5:
                height = volume / s.area_m2
                log.infer(subject, "height_m", round(height, 3), "stated volume / floor area")
                inferred.append("height_m")

            if height is None:
                z_extent = _wall_z_extent(by_space.get(s.id, []), scale)
                if z_extent and z_extent > 1.5:
                    height = z_extent
                    log.infer(
                        subject,
                        "height_m",
                        round(height, 3),
                        "z-extent of the space's own wall surfaces",
                    )
                    inferred.append("height_m")

            if height is None:
                storey = level_heights.get(s.level_id)
                if storey and storey > 1.5:
                    height = storey
                    log.infer(subject, "height_m", round(height, 3), "storey height")
                    inferred.append("height_m")

            if height is None:
                height = log.default(
                    subject,
                    "height_m",
                    DEFAULT_HEIGHT_M,
                    "no volume, no wall surfaces and no storey height in the file",
                )
                inferred.append("height_m")

            out.append(Space(**{**s.__dict__, "height_m": round(float(height), 4), "inferred": inferred}))
        return out

    # -- walls and openings -----------------------------------------------
    def _read_surfaces(
        self,
        surfaces: list[ET.Element],
        scale: float,
        spaces: list[Space],
        log: FidelityLog,
    ) -> tuple[list[Wall], list[Opening]]:
        space_levels = {s.id: s.level_id for s in spaces}
        walls: list[Wall] = []
        openings: list[Opening] = []
        skipped_kinds: dict[str, int] = {}

        for el in surfaces:
            log.seen()
            kind = str(el.get("surfaceType", ""))
            if "wall" not in kind.lower():
                skipped_kinds[kind or "(untyped)"] = skipped_kinds.get(kind or "(untyped)", 0) + 1
                continue

            loop = el.find("./PlanarGeometry/PolyLoop")
            pts3 = _read_loop3(loop, scale) if loop is not None else []
            if len(pts3) < 3:
                log.skip("Surface", "wall surface with no usable PolyLoop")
                continue

            axis = _base_axis(pts3)
            if axis is None:
                log.skip("Surface", "wall surface is not vertical enough to have an axis")
                continue

            zs = [p[2] for p in pts3]
            height = max(zs) - min(zs)
            wid = el.get("id") or f"wall-{len(walls)}"
            adjacent = [a.get("spaceIdRef", "") for a in el.iterfind("./AdjacentSpaceId")]
            level_id = next(
                (space_levels[a] for a in adjacent if a in space_levels),
                spaces[0].level_id if spaces else "level-0",
            )

            inferred = ["thickness_m"]
            log.default(
                f"wall:{wid}",
                "thickness_m",
                DEFAULT_WALL_THICKNESS_M,
                "gbXML surfaces are planes; a wall's thickness lives in its "
                "Construction, which this importer does not read",
            )
            walls.append(
                Wall(
                    id=wid,
                    level_id=level_id,
                    axis=list(axis),
                    thickness_m=DEFAULT_WALL_THICKNESS_M,
                    height_m=round(height, 4) if height > 0.1 else 3.0,
                    exterior=kind.lower().startswith("exterior"),
                    inferred=inferred,
                )
            )
            log.used()

            base_z = min(zs)
            for op in el.iterfind("./Opening"):
                log.seen()
                parsed = _read_opening(op, scale, axis, base_z, wid)
                if parsed is None:
                    log.skip("Opening", "no usable geometry")
                    continue
                openings.append(parsed)
                log.used()

        for kind, count in sorted(skipped_kinds.items()):
            log.skip(
                f"Surface[{kind}]",
                "not a wall — a 2D layout has no place for roofs, slabs or shades",
                count,
            )
        return walls, openings


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def _strip_namespaces(root: ET.Element) -> None:
    """Drop XML namespaces in place, so paths can be written the obvious way.

    gbXML files in the wild are inconsistently namespaced -- same schema, some
    with a default namespace, some without, some with a prefix. Matching on
    ``{http://www.gbxml.org/schema}Space`` would work on exactly the subset that
    happened to be tested.
    """
    for el in root.iter():
        if isinstance(el.tag, str) and el.tag.startswith("{"):
            el.tag = el.tag.split("}", 1)[1]
        for key in list(el.attrib):
            if key.startswith("{"):
                el.attrib[key.split("}", 1)[1]] = el.attrib.pop(key)


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _read_loop(loop: ET.Element, scale: float) -> list[tuple[float, float]]:
    """A PolyLoop projected to the XY plane -- a floor outline."""
    return normalize_polygon([(p[0], p[1]) for p in _read_loop3(loop, scale)])


def _read_loop3(loop: ET.Element, scale: float) -> list[tuple[float, float, float]]:
    """A PolyLoop as 3D points, in metres."""
    out: list[tuple[float, float, float]] = []
    for cp in loop.iterfind("./CartesianPoint"):
        coords = [_float(_text(c)) for c in cp.iterfind("./Coordinate")]
        coords = [c for c in coords if c is not None]
        if len(coords) >= 2:
            out.append(
                (
                    coords[0] * scale,
                    coords[1] * scale,
                    (coords[2] if len(coords) > 2 else 0.0) * scale,
                )
            )
    return out


def _base_axis(
    pts3: list[tuple[float, float, float]]
) -> list[tuple[float, float]] | None:
    """The XY line a vertical surface projects onto: its wall axis.

    A vertical rectangle collapses, seen from above, to a line segment. The axis
    is its two furthest-apart points. A surface that does *not* collapse -- a roof
    or a floor -- has real area in plan, and is rejected here rather than turned
    into a nonsense wall.
    """
    xy = [(p[0], p[1]) for p in pts3]
    ring = normalize_polygon(xy)
    if len(ring) < 2:
        return None
    # Real area in plan means it is not a wall.
    if len(ring) >= 3:
        span = max(distance(a, b) for a in ring for b in ring) or 1.0
        if polygon_area(ring) > VERTICAL_TOL * span * span:
            return None
    best = (0.0, ring[0], ring[-1])
    for i, a in enumerate(ring):
        for b in ring[i + 1 :]:
            d = distance(a, b)
            if d > best[0]:
                best = (d, a, b)
    if best[0] < 0.05:
        return None
    return [best[1], best[2]]


def _read_opening(
    op: ET.Element,
    scale: float,
    axis: list[tuple[float, float]],
    base_z: float,
    wall_id: str,
) -> Opening | None:
    """One Opening, positioned along its wall's axis."""
    loop = op.find("./PlanarGeometry/PolyLoop")
    pts3 = _read_loop3(loop, scale) if loop is not None else []

    if pts3:
        xs = [(p[0], p[1]) for p in pts3]
        zs = [p[2] for p in pts3]
        cx = sum(p[0] for p in xs) / len(xs)
        cy = sum(p[1] for p in xs) / len(xs)
        along = _project_along(axis, (cx, cy))
        width = max(distance(a, b) for a in xs for b in xs) if len(xs) > 1 else 0.9
        height = max(zs) - min(zs)
        sill = min(zs) - base_z
    else:
        rect = op.find("./RectangularGeometry")
        if rect is None:
            return None
        width = (_float(_text(rect.find("Width"))) or 0.9) * scale
        height = (_float(_text(rect.find("Height"))) or 2.1) * scale
        cp = rect.find("./CartesianPoint")
        coords = (
            [(_float(_text(c)) or 0.0) * scale for c in cp.iterfind("./Coordinate")]
            if cp is not None
            else []
        )
        # RectangularGeometry's CartesianPoint is in the surface's own 2D frame:
        # u along the wall, v up it. That is already the number we want.
        along = (coords[0] if coords else 0.0) + width / 2.0
        sill = coords[1] if len(coords) > 1 else 0.0

    kind = str(op.get("openingType", "")).lower()
    if "door" in kind:
        opening_kind = "door"
    elif "window" in kind or "glaz" in kind or "fixed" in kind or "operable" in kind:
        opening_kind = "window"
    else:
        opening_kind = "opening"

    return Opening(
        id=op.get("id") or f"{wall_id}-opening",
        wall_id=wall_id,
        kind=opening_kind,
        along_m=round(float(along), 4),
        width_m=round(float(width), 4),
        height_m=round(float(height), 4) if height > 0.05 else 2.1,
        sill_m=round(max(0.0, float(sill)), 4),
    )


def _project_along(axis: list[tuple[float, float]], pt: tuple[float, float]) -> float:
    """Distance from the axis start to the foot of ``pt`` on it, in metres."""
    (ax, ay), (bx, by) = axis[0], axis[-1]
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 0:
        return 0.0
    t = ((pt[0] - ax) * dx + (pt[1] - ay) * dy) / length_sq
    return max(0.0, min(1.0, t)) * (length_sq**0.5)


def _surfaces_by_space(surfaces: list[ET.Element]) -> dict[str, list[ET.Element]]:
    out: dict[str, list[ET.Element]] = {}
    for el in surfaces:
        for adj in el.iterfind("./AdjacentSpaceId"):
            sid = adj.get("spaceIdRef", "")
            if sid:
                out.setdefault(sid, []).append(el)
    return out



def _floor_loop_for(
    space_id: str, surfaces: list[ET.Element], scale: float
) -> list[tuple[float, float]]:
    """A space's outline recovered from whichever surface is its floor."""
    for el in surfaces:
        kind = str(el.get("surfaceType", "")).lower()
        if "floor" not in kind and "slab" not in kind:
            continue
        if not any(a.get("spaceIdRef") == space_id for a in el.iterfind("./AdjacentSpaceId")):
            continue
        loop = el.find("./PlanarGeometry/PolyLoop")
        if loop is None:
            continue
        ring = _read_loop(loop, scale)
        if len(ring) >= 3:
            return ring
    return []


def _wall_z_extent(surfaces: list[ET.Element], scale: float) -> float | None:
    """Floor-to-ceiling height implied by a space's own wall surfaces."""
    zs: list[float] = []
    for el in surfaces:
        if "wall" not in str(el.get("surfaceType", "")).lower():
            continue
        loop = el.find("./PlanarGeometry/PolyLoop")
        if loop is None:
            continue
        zs.extend(p[2] for p in _read_loop3(loop, scale))
    if len(zs) < 2:
        return None
    return max(zs) - min(zs)
