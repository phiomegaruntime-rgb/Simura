"""IFC: the standard, read without a geometry kernel.

IFC (ISO 16739) is the real interoperability format for buildings, and it is
enormous. A full reader is a geometry kernel, a schema and a decade -- which is
why the answer is normally ``pip install ifcopenshell``, a binary wheel far larger
than the whole of Simura.

This importer takes the other road, and the reasoning is the same one that has
every texture in the 3D world drawn in code rather than shipped as a sprite: this
is a repository people clone in order to *read*, and a dependency you cannot open
is a part of the system nobody can inspect. So the parser is here, in Python, in
one file, and it reads the subset that a 2D layout actually needs:

============================  ====================================================
``IFCPROJECT``/``IFCSIUNIT``  the length unit, converted once
``IFCSITE``                   latitude, longitude, elevation -- the join to weather
``IFCGEOMETRICREPRESENTATIONCONTEXT``  true north
``IFCBUILDINGSTOREY``         levels and their elevations
``IFCSPACE``                  rooms: footprint, height, name, predefined type
``IFCWALL``/``IFCWALLSTANDARDCASE``  axis, thickness, height
``IFCDOOR``/``IFCWINDOW``     openings, positioned along their wall
``IFCLOCALPLACEMENT``         the placement chain, composed to world coordinates
``IFCEXTRUDEDAREASOLID``      the one solid that matters, with its profile
============================  ====================================================

Everything else -- swept discs, B-reps, tessellations, CSG, mapped items, curved
walls -- is counted by type, skipped, and named in the fidelity record. That is
the honest position: this reads most of most buildings, it says which parts it
did not read, and when the answer matters more than the dependency,
:mod:`simura.space.providers.ifc_full` runs the same job through
``ifcopenshell`` and returns the same :class:`~simura.space.plan.FloorPlan`.

Why the subset is the right subset
----------------------------------

Because of what a 2D layout is *for*. Simura does not need to render the
building; it needs to know how big each room is, how high its ceiling is, what it
is for, where the walls run, and where on Earth it stands. Those live in the
structural and property parts of the file, not in the geometry, and the one piece
of geometry they do need -- a profile extruded vertically -- is how essentially
every wall, slab and space in a practical model is authored. A model whose rooms
are B-reps is a model this cannot read, and it will say so rather than produce a
building with three rooms missing.

The placement chain
-------------------

The one genuinely fiddly part, and the one most naive readers get wrong. Every
product in IFC is placed *relative to its parent* -- a wall relative to its
storey, a storey relative to the building, the building relative to the site --
so a wall's coordinates mean nothing until the chain above it has been composed.
Skipping that gives a building whose every storey is stacked on the origin, which
looks plausible enough on the ground floor to ship. :func:`_world_transform`
walks the chain and caches it.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable, NamedTuple

from .. import units
from ..fidelity import FidelityLog
from ..geometry import Point, normalize_polygon
from ..occupancy import classify
from ..plan import FloorPlan, Georeference, Level, Opening, Space, Wall
from ..provider import PlanError
from .file import FilePlanProvider

DEFAULT_HEIGHT_M = 2.7
DEFAULT_WALL_THICKNESS_M = 0.2
DEFAULT_WALL_HEIGHT_M = 3.0

# How finely a circular profile is polygonised. Circular rooms are rare and
# circular columns are common; 24 segments is under 1% area error and small
# enough not to bloat a plan.
CIRCLE_SEGMENTS = 24


class Ref(NamedTuple):
    """A ``#123`` reference to another instance."""

    id: int


class Typed(NamedTuple):
    """A typed value or an entity instance: ``IFCLENGTHMEASURE(304.8)``."""

    name: str
    args: list

    def arg(self, i: int) -> Any:
        return self.args[i] if i < len(self.args) else None


class IfcProvider(FilePlanProvider):
    """A floor plan from an IFC STEP file (``.ifc``)."""

    format = "ifc"

    def __init__(self, path=None, *, data=None, name="", encoding="utf-8") -> None:
        super().__init__(path, data=data, name=name, encoding=encoding)
        self.entities: dict[int, Typed] = {}
        self._by_type: dict[str, list[int]] = {}
        self._placements: dict[int, tuple[float, float, float, float, float]] = {}
        self._matrices: dict[int, tuple[tuple[Point3, Point3, Point3], Point3]] = {}
        self._scale = 1.0

    # -- entry point ------------------------------------------------------
    def _parse(self, log: FidelityLog) -> FloorPlan:
        text = self.text()
        if "ISO-10303-21" not in text[:512] and "IFC" not in text[:2048]:
            raise PlanError(
                f"{self.name} is not an IFC STEP file. IFC-XML and the zipped "
                f"'.ifczip' form are not supported — export as .ifc (STEP)."
            )
        self.entities = _parse_step(text)
        if not self.entities:
            raise PlanError(f"{self.name} has no DATA section entities")
        self._index()

        self._scale, unit_name = self._resolve_units(log)
        georef = self._read_site(log)
        levels = self._read_storeys(log)
        containment = self._read_containment()
        spaces = self._read_spaces(levels, containment, log)
        walls = self._read_walls(levels, containment, log)
        openings = self._read_openings(walls, levels, log)
        self._log_skipped(log)

        if not spaces and not walls:
            raise PlanError(
                f"{self.name} parsed, but no IfcSpace or IfcWall produced usable "
                f"geometry. The model may use B-rep or tessellated geometry, which "
                f"this importer does not read."
            )

        plan = FloorPlan(
            name=self._project_name() or self.name,
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

    # -- entity access ----------------------------------------------------
    def _index(self) -> None:
        for eid, ent in self.entities.items():
            self._by_type.setdefault(ent.name, []).append(eid)

    def of_type(self, *names: str) -> list[int]:
        out: list[int] = []
        for n in names:
            out.extend(self._by_type.get(n.upper(), []))
        return sorted(out)

    def get(self, ref: Any) -> Typed | None:
        if isinstance(ref, Ref):
            return self.entities.get(ref.id)
        if isinstance(ref, int):
            return self.entities.get(ref)
        return None

    def is_a(self, ref: Any, *names: str) -> bool:
        ent = self.get(ref)
        return ent is not None and ent.name in {n.upper() for n in names}

    # -- units ------------------------------------------------------------
    def _resolve_units(self, log: FidelityLog) -> tuple[float, str]:
        """The project's length unit, as metres per unit.

        IFC states it either as an SI unit with a prefix, or as a conversion-based
        unit ("foot") defined as a multiple of an SI one. Both are read; a project
        with neither gets metres and an inference recorded.
        """
        for eid in self.of_type("IFCUNITASSIGNMENT"):
            ent = self.entities[eid]
            for unit_ref in _as_list(ent.arg(0)):
                unit = self.get(unit_ref)
                if unit is None:
                    continue
                if unit.name == "IFCSIUNIT" and _enum(unit.arg(1)) == "LENGTHUNIT":
                    factor = units.si_length_factor(_enum(unit.arg(2)), _enum(unit.arg(3)))
                    name = {0.001: "mm", 0.01: "cm", 1.0: "m"}.get(factor, f"{factor}m")
                    return (factor, name)
                if unit.name == "IFCCONVERSIONBASEDUNIT":
                    if _enum(unit.arg(1)) != "LENGTHUNIT":
                        continue
                    label = str(unit.arg(2) or "").strip().lower()
                    measure = self.get(unit.arg(3))
                    if measure and measure.name == "IFCMEASUREWITHUNIT":
                        value = _numeric(measure.arg(0))
                        base = self.get(measure.arg(1))
                        base_factor = (
                            units.si_length_factor(_enum(base.arg(2)), _enum(base.arg(3)))
                            if base is not None and base.name == "IFCSIUNIT"
                            else 1.0
                        )
                        if value:
                            return (value * base_factor, label or "custom")
                    if units.known(label):
                        return (units.factor(label), label)
        log.default(
            "plan", "units", "m", "no IfcUnitAssignment length unit in the file"
        )
        return (1.0, "m")

    # -- site and north ---------------------------------------------------
    def _read_site(self, log: FidelityLog) -> Georeference:
        north = self._true_north(log)
        for eid in self.of_type("IFCSITE"):
            site = self.entities[eid]
            lat = _compound_angle(site.arg(9))
            lon = _compound_angle(site.arg(10))
            elev = _numeric(site.arg(11))
            if lat is None and lon is None:
                continue
            return Georeference(
                latitude=lat,
                longitude=lon,
                elevation_m=(elev * self._scale) if elev is not None else None,
                north_deg=north,
                address=str(site.arg(2) or site.arg(7) or "").strip(),
            )
        log.warn(
            "no IfcSite RefLatitude/RefLongitude — the building has no coordinates, "
            "so weather cannot be configured from the model"
        )
        return Georeference(north_deg=north)

    def _true_north(self, log: FidelityLog) -> float:
        """Bearing of the model's +y axis, from the representation context.

        IFC stores true north as a direction vector in the plan's own frame, so
        the bearing is the angle from +y to it. Project north is almost never true
        north and the difference decides which facades take morning sun.
        """
        for eid in self.of_type("IFCGEOMETRICREPRESENTATIONCONTEXT"):
            ctx = self.entities[eid]
            direction = self.get(ctx.arg(5))
            if direction is None or direction.name != "IFCDIRECTION":
                continue
            ratios = [_numeric(v) or 0.0 for v in _as_list(direction.arg(0))]
            if len(ratios) >= 2 and (ratios[0] or ratios[1]):
                bearing = math.degrees(math.atan2(ratios[0], ratios[1]))
                return round(bearing % 360.0, 4)
        return 0.0

    def _project_name(self) -> str:
        for eid in self.of_type("IFCPROJECT"):
            name = self.entities[eid].arg(2)
            if name:
                return str(name)
        for eid in self.of_type("IFCBUILDING"):
            name = self.entities[eid].arg(2)
            if name:
                return str(name)
        return ""

    # -- storeys ----------------------------------------------------------
    def _read_storeys(self, log: FidelityLog) -> list[Level]:
        found: list[Level] = []
        for eid in self.of_type("IFCBUILDINGSTOREY"):
            log.seen()
            storey = self.entities[eid]
            elevation = _numeric(storey.arg(9))
            if elevation is None:
                _, _, tz, _, _ = self._world_transform(storey.arg(5))
                elevation = tz / self._scale if self._scale else 0.0
                log.infer(
                    f"level:{eid}",
                    "elevation_m",
                    round(elevation * self._scale, 3),
                    "IfcBuildingStorey has no Elevation; taken from its placement",
                )
            found.append(
                Level(
                    id=f"#{eid}",
                    name=str(storey.arg(2) or storey.arg(7) or f"Level {len(found)}"),
                    elevation_m=round(float(elevation) * self._scale, 4),
                    height_m=DEFAULT_WALL_HEIGHT_M,
                )
            )
            log.used()

        found.sort(key=lambda level: level.elevation_m)
        out: list[Level] = []
        for i, level in enumerate(found):
            height = level.height_m
            if i + 1 < len(found):
                gap = found[i + 1].elevation_m - level.elevation_m
                if gap > 0.1:
                    height = log.infer(
                        f"level:{level.id}",
                        "height_m",
                        round(gap, 3),
                        "elevation difference to the storey above",
                    )
            else:
                log.default(
                    f"level:{level.id}",
                    "height_m",
                    DEFAULT_WALL_HEIGHT_M,
                    "top storey; nothing above it to measure against",
                )
            out.append(Level(**{**level.__dict__, "height_m": height}))

        if not out:
            log.default("plan", "levels", 1, "no IfcBuildingStorey in the file")
            out = [Level(id="level-0", name="Level 0")]
        return out

    def _read_containment(self) -> dict[int, str]:
        """Product id -> level id, from IfcRelContainedInSpatialStructure/Aggregates."""
        out: dict[int, str] = {}
        for eid in self.of_type(
            "IFCRELCONTAINEDINSPATIALSTRUCTURE", "IFCRELAGGREGATES"
        ):
            rel = self.entities[eid]
            related, relating = (
                (rel.arg(4), rel.arg(5))
                if rel.name == "IFCRELCONTAINEDINSPATIALSTRUCTURE"
                else (rel.arg(5), rel.arg(4))
            )
            parent = relating if isinstance(relating, Ref) else None
            if parent is None or not self.is_a(parent, "IFCBUILDINGSTOREY"):
                continue
            for child in _as_list(related):
                if isinstance(child, Ref):
                    out[child.id] = f"#{parent.id}"
        return out

    # -- spaces -----------------------------------------------------------
    def _read_spaces(
        self, levels: list[Level], containment: dict[int, str], log: FidelityLog
    ) -> list[Space]:
        default_level = levels[0].id if levels else "level-0"
        known = {level.id for level in levels}
        out: list[Space] = []

        for eid in self.of_type("IFCSPACE"):
            log.seen()
            space = self.entities[eid]
            shape = self._shape(space.arg(6), eid, log)
            if shape is None or len(shape[0]) < 3:
                log.skip(
                    "IfcSpace",
                    "no readable footprint (needs a FootPrint curve or an "
                    "extruded-area-solid body)",
                )
                continue
            polygon, depth = shape

            tx, ty, _tz, cos_t, sin_t = self._world_transform(space.arg(5))
            polygon = [_apply(p, tx, ty, cos_t, sin_t) for p in polygon]

            name = str(space.arg(2) or "").strip()
            long_name = str(space.arg(7) or "").strip()
            predefined = _enum(space.arg(9))
            occupancy, basis = classify(
                name=name,
                long_name=long_name,
                ifc_predefined_type=predefined,
                object_type=str(space.arg(4) or ""),
            )
            inferred: list[str] = []
            if not predefined or predefined in ("NOTDEFINED", "USERDEFINED"):
                log.infer(f"space:#{eid}", "occupancy", occupancy, basis)
                inferred.append("occupancy")

            height = depth
            if not height or height <= 0.5:
                level = next(
                    (level for level in levels if level.id == containment.get(eid)), None
                )
                if level and level.height_m > 1.5:
                    height = log.infer(
                        f"space:#{eid}", "height_m", level.height_m, "storey height"
                    )
                else:
                    height = log.default(
                        f"space:#{eid}",
                        "height_m",
                        DEFAULT_HEIGHT_M,
                        "the space's body has no extrusion depth and its storey "
                        "has no height",
                    )
                inferred.append("height_m")

            level_id = containment.get(eid, default_level)
            if level_id not in known:
                level_id = default_level

            out.append(
                Space(
                    id=f"#{eid}",
                    name=long_name or name or f"Space {len(out) + 1}",
                    level_id=level_id,
                    polygon=polygon,
                    height_m=round(float(height), 4),
                    occupancy=occupancy,
                    inferred=inferred,
                )
            )
            log.used()
        return out

    # -- walls ------------------------------------------------------------
    def _read_walls(
        self, levels: list[Level], containment: dict[int, str], log: FidelityLog
    ) -> list[Wall]:
        default_level = levels[0].id if levels else "level-0"
        thicknesses = self._material_thicknesses()
        out: list[Wall] = []

        for eid in self.of_type(
            "IFCWALL", "IFCWALLSTANDARDCASE", "IFCWALLELEMENTEDCASE", "IFCCURTAINWALL"
        ):
            log.seen()
            wall = self.entities[eid]
            axis = self._axis_curve(wall.arg(6))
            body = self._shape(wall.arg(6), eid, log, want_axis=False)

            if axis is None and body is not None and len(body[0]) >= 3:
                # No Axis representation: recover the centre-line as the long
                # median of the body footprint. A wall is a long thin rectangle,
                # so this is well defined and, for the common case, exact.
                axis = _median_line(body[0])
            if axis is None or len(axis) < 2:
                log.skip("IfcWall", "no Axis representation and no readable body")
                continue

            tx, ty, _tz, cos_t, sin_t = self._world_transform(wall.arg(5))
            world_axis = [_apply(p, tx, ty, cos_t, sin_t) for p in axis]

            inferred: list[str] = []
            thickness = thicknesses.get(eid)
            if thickness is None and body is not None and len(body[0]) >= 3:
                thickness = _short_side(body[0])
                if thickness:
                    log.infer(
                        f"wall:#{eid}",
                        "thickness_m",
                        round(thickness, 4),
                        "short side of the wall's own extruded footprint",
                    )
                    inferred.append("thickness_m")
            if not thickness or thickness <= 0.01:
                thickness = log.default(
                    f"wall:#{eid}",
                    "thickness_m",
                    DEFAULT_WALL_THICKNESS_M,
                    "no IfcMaterialLayerSet and no readable body footprint",
                )
                inferred.append("thickness_m")

            height = body[1] if body else 0.0
            if not height or height <= 0.3:
                height = log.default(
                    f"wall:#{eid}",
                    "height_m",
                    DEFAULT_WALL_HEIGHT_M,
                    "the wall's body has no extrusion depth",
                )
                inferred.append("height_m")

            out.append(
                Wall(
                    id=f"#{eid}",
                    level_id=containment.get(eid, default_level),
                    axis=world_axis,
                    thickness_m=round(float(thickness), 4),
                    height_m=round(float(height), 4),
                    exterior=self._is_external(eid),
                    inferred=inferred,
                )
            )
            log.used()
        return out

    def _material_thicknesses(self) -> dict[int, float]:
        """Wall id -> total layer-set thickness, the authoritative source.

        A wall's thickness in IFC is not geometry: it is the sum of its material
        layers, associated to the wall through a relationship. Reading it here
        means a wall gets its *stated* thickness and only falls back to measuring
        its footprint when the model does not say.
        """
        out: dict[int, float] = {}
        for eid in self.of_type("IFCRELASSOCIATESMATERIAL"):
            rel = self.entities[eid]
            material = self.get(rel.arg(5))
            if material is None:
                continue
            layer_set = None
            if material.name == "IFCMATERIALLAYERSETUSAGE":
                layer_set = self.get(material.arg(0))
            elif material.name == "IFCMATERIALLAYERSET":
                layer_set = material
            if layer_set is None or layer_set.name != "IFCMATERIALLAYERSET":
                continue
            total = 0.0
            for layer_ref in _as_list(layer_set.arg(0)):
                layer = self.get(layer_ref)
                if layer is not None and layer.name == "IFCMATERIALLAYER":
                    total += (_numeric(layer.arg(1)) or 0.0) * self._scale
            if total <= 0:
                continue
            for obj in _as_list(rel.arg(4)):
                if isinstance(obj, Ref):
                    out[obj.id] = total
        return out

    def _is_external(self, eid: int) -> bool:
        """Whether the model says this element is external, via Pset_WallCommon."""
        for rel_id in self.of_type("IFCRELDEFINESBYPROPERTIES"):
            rel = self.entities[rel_id]
            if not any(
                isinstance(o, Ref) and o.id == eid for o in _as_list(rel.arg(4))
            ):
                continue
            pset = self.get(rel.arg(5))
            if pset is None or pset.name != "IFCPROPERTYSET":
                continue
            for prop_ref in _as_list(pset.arg(4)):
                prop = self.get(prop_ref)
                if prop is None or prop.name != "IFCPROPERTYSINGLEVALUE":
                    continue
                if str(prop.arg(0) or "").strip().lower() != "isexternal":
                    continue
                value = prop.arg(2)
                if isinstance(value, Typed):
                    return _enum(value.arg(0)) in ("T", "TRUE") or value.arg(0) is True
        return False

    # -- openings ---------------------------------------------------------
    def _read_openings(
        self, walls: list[Wall], levels: list[Level], log: FidelityLog
    ) -> list[Opening]:
        """Doors and windows, found through the void-and-fill relationship pair.

        IFC does not attach a door to a wall. It attaches an *opening* to the wall
        (``IfcRelVoidsElement``) and then fills that opening with a door
        (``IfcRelFillsElement``). Following both is what lets a door know which
        wall it is in -- and it is why a naive reader finds doors floating in
        space with no host.
        """
        by_id = {w.id: w for w in walls}
        elevations = {level.id: level.elevation_m for level in levels}
        voids: dict[int, int] = {}  # opening id -> wall id
        for eid in self.of_type("IFCRELVOIDSELEMENT"):
            rel = self.entities[eid]
            host, opening = rel.arg(4), rel.arg(5)
            if isinstance(host, Ref) and isinstance(opening, Ref):
                voids[opening.id] = host.id

        fills: dict[int, int] = {}  # opening id -> door/window id
        for eid in self.of_type("IFCRELFILLSELEMENT"):
            rel = self.entities[eid]
            opening, filler = rel.arg(4), rel.arg(5)
            if isinstance(opening, Ref) and isinstance(filler, Ref):
                fills[opening.id] = filler.id

        out: list[Opening] = []
        for opening_id, wall_id in voids.items():
            wall = by_id.get(f"#{wall_id}")
            if wall is None or len(wall.axis) < 2:
                continue
            log.seen()
            opening = self.entities.get(opening_id)
            if opening is None:
                continue

            filler = self.entities.get(fills.get(opening_id, -1))
            kind = "opening"
            width = height = None
            sill = 0.0
            along = 0.0
            if filler is not None:
                if filler.name.startswith("IFCDOOR"):
                    kind = "door"
                elif filler.name.startswith("IFCWINDOW"):
                    kind = "window"
                height = _numeric(filler.arg(8))
                width = _numeric(filler.arg(9))
                if height:
                    height *= self._scale
                if width:
                    width *= self._scale

            # The opening's own solid is authoritative, and it is what a viewer
            # subtracts from the wall. Everything else is a fallback.
            #
            # The naive reading -- project the opening's placement origin onto the
            # wall and call that the centre, take the width off the door -- is
            # wrong twice over. An IFC profile is positioned within its placement,
            # so the origin is frequently a *corner* of the opening rather than
            # its middle; and a door's `OverallWidth` is the leaf, while the hole
            # in the wall is the structural opening around it. Both errors put a
            # door half a leaf-width off, which is what a door overlapping the
            # wall beside it looks like.
            base = elevations.get(wall.level_id, 0.0)
            extent = _extent_along(self._solid_corners(opening.arg(6), opening.arg(5)), wall.axis)

            if extent is not None:
                along, solid_width, low, high = extent
                # Only take the width from the solid when it is a plausible hole.
                # A degenerate profile would otherwise cut the wall in half.
                if solid_width > 0.15:
                    width = solid_width
                if high - low > 0.3:
                    height = high - low
                sill = max(0.0, low - base)
            else:
                tx, ty, tz, _cos, _sin = self._world_transform(opening.arg(5))
                along = _project_along(wall.axis, (tx, ty))
                log.infer(
                    f"opening:#{opening_id}",
                    "along_m",
                    round(along, 3),
                    "the opening has no readable solid, so its position was taken "
                    "from its placement origin -- which the schema does not "
                    "require to be the centre of the hole",
                )
                if kind == "window":
                    sill = max(0.0, tz - base)

            if not width:
                width = log.default(
                    f"opening:#{opening_id}",
                    "width_m",
                    0.9 if kind == "door" else 1.2,
                    "neither the filling element nor the opening states a width",
                )
            if not height:
                height = log.default(
                    f"opening:#{opening_id}",
                    "height_m",
                    2.1 if kind == "door" else 1.4,
                    "neither the filling element nor the opening states a height",
                )

            # Keep the hole inside the wall it is cut in.
            #
            # An opening that runs past the end of its wall is either a placement
            # this importer read imperfectly or a model where the two disagree.
            # Either way, drawing it where the file says leaves a door frame
            # hanging in mid-air off the end of a wall -- so it is pulled back
            # inside, and the fact is recorded rather than quietly corrected.
            half = float(width) / 2.0
            if wall.length_m > float(width):
                clamped = min(max(along, half), wall.length_m - half)
                if abs(clamped - along) > 0.01:
                    log.infer(
                        f"opening:#{opening_id}",
                        "along_m",
                        round(clamped, 3),
                        f"the opening ran past the end of its wall; moved "
                        f"{abs(clamped - along):.2f} m to sit inside it",
                    )
                    along = clamped
            else:
                along = wall.length_m / 2.0

            out.append(
                Opening(
                    id=f"#{opening_id}",
                    wall_id=wall.id,
                    kind=kind,
                    along_m=round(along, 4),
                    width_m=round(float(width), 4),
                    height_m=round(float(height), 4),
                    sill_m=round(float(sill), 4),
                )
            )
            log.used()
        return out

    # -- geometry ---------------------------------------------------------
    def _shape(
        self, rep_ref: Any, owner: int, log: FidelityLog, want_axis: bool = True
    ) -> tuple[list[Point], float] | None:
        """``(footprint polygon, extrusion depth)`` for a product's shape.

        Prefers an explicit ``FootPrint`` representation (a plan-view curve, which
        is exactly what this component wants) and falls back to the ``Body``, from
        which an extruded-area solid gives both the outline and the height in one.
        """
        shape = self.get(rep_ref)
        if shape is None or shape.name != "IFCPRODUCTDEFINITIONSHAPE":
            return None

        footprint: list[Point] | None = None
        body: tuple[list[Point], float] | None = None

        for rep_id in _as_list(shape.arg(2)):
            rep = self.get(rep_id)
            if rep is None or rep.name != "IFCSHAPEREPRESENTATION":
                continue
            identifier = str(rep.arg(1) or "").strip().lower()
            rep_type = str(rep.arg(2) or "").strip().lower()

            if identifier in ("footprint", "plan") and want_axis:
                for item in _as_list(rep.arg(3)):
                    ring = self._curve(item)
                    if ring and len(ring) >= 3:
                        footprint = ring
                        break
            elif identifier == "body" or rep_type in ("sweptsolid", "brep", "clipping"):
                for item in _as_list(rep.arg(3)):
                    solid = self._extruded(item, owner, log)
                    if solid:
                        body = solid
                        break

        if footprint is not None:
            return (footprint, body[1] if body else 0.0)
        return body

    def _axis_curve(self, rep_ref: Any) -> list[Point] | None:
        """A wall's ``Axis`` representation: its centre line, straight from the file."""
        shape = self.get(rep_ref)
        if shape is None or shape.name != "IFCPRODUCTDEFINITIONSHAPE":
            return None
        for rep_id in _as_list(shape.arg(2)):
            rep = self.get(rep_id)
            if rep is None or rep.name != "IFCSHAPEREPRESENTATION":
                continue
            if str(rep.arg(1) or "").strip().lower() != "axis":
                continue
            for item in _as_list(rep.arg(3)):
                pts = self._curve(item, closed=False)
                if pts and len(pts) >= 2:
                    return pts
        return None

    def _extruded(
        self, item_ref: Any, owner: int, log: FidelityLog
    ) -> tuple[list[Point], float] | None:
        """An ``IfcExtrudedAreaSolid`` as its profile outline and its depth."""
        item = self.get(item_ref)
        if item is None:
            return None
        if item.name == "IFCBOOLEANCLIPPINGRESULT":
            # A wall clipped by a roof plane is still that wall's footprint; the
            # first operand is the solid, the second is what was cut away.
            return self._extruded(item.arg(1), owner, log)
        if item.name == "IFCMAPPEDITEM":
            source = self.get(item.arg(0))
            if source is not None and source.name == "IFCREPRESENTATIONMAP":
                rep = self.get(source.arg(1))
                if rep is not None:
                    for sub in _as_list(rep.arg(3)):
                        found = self._extruded(sub, owner, log)
                        if found:
                            return found
            return None
        if item.name != "IFCEXTRUDEDAREASOLID":
            log.skip(
                f"Ifc geometry [{item.name.title().replace('Ifc', 'Ifc')}]",
                "only extruded-area solids are read; this needs a geometry kernel",
            )
            return None

        profile = self._profile(item.arg(0))
        if not profile:
            return None
        depth = (_numeric(item.arg(3)) or 0.0) * self._scale

        # The solid's own Position places the profile within the product.
        placement = self.get(item.arg(1))
        if placement is not None and placement.name == "IFCAXIS2PLACEMENT3D":
            tx, ty, _tz, cos_t, sin_t = self._axis2placement3d(placement)
            profile = [_apply(p, tx, ty, cos_t, sin_t) for p in profile]

        return (profile, depth)

    def _profile(self, ref: Any) -> list[Point] | None:
        """The outline of a profile definition, in metres, in its own frame."""
        prof = self.get(ref)
        if prof is None:
            return None

        if prof.name == "IFCRECTANGLEPROFILEDEF":
            x_dim = (_numeric(prof.arg(3)) or 0.0) * self._scale
            y_dim = (_numeric(prof.arg(4)) or 0.0) * self._scale
            ring = [
                (-x_dim / 2, -y_dim / 2),
                (x_dim / 2, -y_dim / 2),
                (x_dim / 2, y_dim / 2),
                (-x_dim / 2, y_dim / 2),
            ]
            return self._place_profile(ring, prof.arg(2))

        if prof.name in ("IFCARBITRARYCLOSEDPROFILEDEF", "IFCARBITRARYPROFILEDEFWITHVOIDS"):
            # Voids are ignored deliberately: a column standing in a room does not
            # change the room's outline, and subtracting it would make the plan
            # harder to read for no gain in what is computed from it.
            ring = self._curve(prof.arg(2))
            return ring if ring and len(ring) >= 3 else None

        if prof.name == "IFCCIRCLEPROFILEDEF":
            radius = (_numeric(prof.arg(3)) or 0.0) * self._scale
            ring = [
                (
                    radius * math.cos(2 * math.pi * i / CIRCLE_SEGMENTS),
                    radius * math.sin(2 * math.pi * i / CIRCLE_SEGMENTS),
                )
                for i in range(CIRCLE_SEGMENTS)
            ]
            return self._place_profile(ring, prof.arg(2))

        return None

    def _place_profile(self, ring: list[Point], placement_ref: Any) -> list[Point]:
        placement = self.get(placement_ref)
        if placement is None or placement.name != "IFCAXIS2PLACEMENT2D":
            return ring
        location = self.get(placement.arg(0))
        tx, ty = _point2(location, self._scale) if location else (0.0, 0.0)
        cos_t, sin_t = 1.0, 0.0
        direction = self.get(placement.arg(1))
        if direction is not None and direction.name == "IFCDIRECTION":
            ratios = [_numeric(v) or 0.0 for v in _as_list(direction.arg(0))]
            if len(ratios) >= 2:
                norm = math.hypot(ratios[0], ratios[1]) or 1.0
                cos_t, sin_t = ratios[0] / norm, ratios[1] / norm
        return [_apply(p, tx, ty, cos_t, sin_t) for p in ring]

    def _curve(self, ref: Any, closed: bool = True) -> list[Point] | None:
        """An ``IfcPolyline`` or a polyline-only ``IfcCompositeCurve``, in metres."""
        curve = self.get(ref)
        if curve is None:
            return None
        if curve.name == "IFCPOLYLINE":
            pts = [
                _point2(self.get(p), self._scale)
                for p in _as_list(curve.arg(0))
                if self.get(p) is not None
            ]
            pts = [p for p in pts if p is not None]
            return normalize_polygon(pts) if closed else pts
        if curve.name == "IFCINDEXEDPOLYCURVE":
            points_list = self.get(curve.arg(0))
            if points_list is not None and points_list.name == "IFCCARTESIANPOINTLIST2D":
                coords = _as_list(points_list.arg(0))
                pts = [
                    (
                        (_numeric(c[0]) or 0.0) * self._scale,
                        (_numeric(c[1]) or 0.0) * self._scale,
                    )
                    for c in coords
                    if isinstance(c, list) and len(c) >= 2
                ]
                return normalize_polygon(pts) if closed else pts
        if curve.name == "IFCCOMPOSITECURVE":
            pts: list[Point] = []
            for seg_ref in _as_list(curve.arg(0)):
                seg = self.get(seg_ref)
                if seg is None or seg.name != "IFCCOMPOSITECURVESEGMENT":
                    continue
                sub = self._curve(seg.arg(2), closed=False)
                if sub:
                    pts.extend(sub)
            if pts:
                return normalize_polygon(pts) if closed else pts
        return None

    # -- placement --------------------------------------------------------
    def _world_transform(self, ref: Any) -> tuple[float, float, float, float, float]:
        """``(x, y, z, cos, sin)`` for a placement, composed up the whole chain.

        Cached per placement: a storey's chain is walked once no matter how many
        walls hang off it.
        """
        if not isinstance(ref, Ref):
            return (0.0, 0.0, 0.0, 1.0, 0.0)
        if ref.id in self._placements:
            return self._placements[ref.id]

        placement = self.entities.get(ref.id)
        if placement is None or placement.name != "IFCLOCALPLACEMENT":
            return (0.0, 0.0, 0.0, 1.0, 0.0)

        parent = self._world_transform(placement.arg(0))
        relative = self.get(placement.arg(1))
        local = (
            self._axis2placement3d(relative)
            if relative is not None and relative.name == "IFCAXIS2PLACEMENT3D"
            else (0.0, 0.0, 0.0, 1.0, 0.0)
        )

        px, py, pz, pc, ps = parent
        lx, ly, lz, lc, ls = local
        world = (
            px + lx * pc - ly * ps,
            py + lx * ps + ly * pc,
            pz + lz,
            pc * lc - ps * ls,
            ps * lc + pc * ls,
        )
        self._placements[ref.id] = world
        return world

    def _axis2placement3d(
        self, placement: Typed
    ) -> tuple[float, float, float, float, float]:
        location = self.get(placement.arg(0))
        tx, ty, tz = (0.0, 0.0, 0.0)
        if location is not None and location.name == "IFCCARTESIANPOINT":
            coords = [(_numeric(c) or 0.0) * self._scale for c in _as_list(location.arg(0))]
            tx = coords[0] if coords else 0.0
            ty = coords[1] if len(coords) > 1 else 0.0
            tz = coords[2] if len(coords) > 2 else 0.0

        cos_t, sin_t = 1.0, 0.0
        ref_dir = self.get(placement.arg(2))
        if ref_dir is not None and ref_dir.name == "IFCDIRECTION":
            ratios = [_numeric(v) or 0.0 for v in _as_list(ref_dir.arg(0))]
            if len(ratios) >= 2 and (ratios[0] or ratios[1]):
                norm = math.hypot(ratios[0], ratios[1]) or 1.0
                cos_t, sin_t = ratios[0] / norm, ratios[1] / norm
        return (tx, ty, tz, cos_t, sin_t)


    # -- placements, in three dimensions --------------------------------------

    def _axis2placement_matrix(
        self, placement: Typed
    ) -> tuple[tuple[Point3, Point3, Point3], Point3]:
        """An ``IfcAxis2Placement3D`` as three basis vectors and a translation.

        The 2D form used elsewhere carries a rotation about Z and nothing else,
        which is all a wall or a storey ever needs. An **opening** needs more:
        its profile stands in the wall's elevation plane, so its placement tips
        the local Z away from vertical, and a Z-only rotation cannot express that
        at all. Reading the full axis triad is what lets an opening's solid be
        put where the file actually says it is.

        The construction is the one the schema prescribes: ``Axis`` is local Z,
        ``RefDirection`` is projected perpendicular to it to give local X, and Y
        follows from the cross product. Either may be absent, in which case the
        identity applies.
        """
        location = self.get(placement.arg(0))
        translation: Point3 = (0.0, 0.0, 0.0)
        if location is not None and location.name == "IFCCARTESIANPOINT":
            coords = [(_numeric(c) or 0.0) * self._scale for c in _as_list(location.arg(0))]
            translation = (
                coords[0] if coords else 0.0,
                coords[1] if len(coords) > 1 else 0.0,
                coords[2] if len(coords) > 2 else 0.0,
            )

        z_axis = _direction(self.get(placement.arg(1))) or (0.0, 0.0, 1.0)
        ref = _direction(self.get(placement.arg(2))) or _perpendicular(z_axis)
        # Gram-Schmidt: X is whatever is left of RefDirection once the part along
        # Z is taken out of it.
        dot = _dot(ref, z_axis)
        x_axis = _normalize(
            (ref[0] - dot * z_axis[0], ref[1] - dot * z_axis[1], ref[2] - dot * z_axis[2])
        ) or _perpendicular(z_axis)
        y_axis = _cross(z_axis, x_axis)
        return ((x_axis, y_axis, z_axis), translation)

    def _world_matrix(self, ref: Any) -> tuple[tuple[Point3, Point3, Point3], Point3]:
        """The full 3D transform for a placement, composed up the whole chain."""
        if not isinstance(ref, Ref):
            return (_IDENTITY, (0.0, 0.0, 0.0))
        cached = self._matrices.get(ref.id)
        if cached is not None:
            return cached

        placement = self.entities.get(ref.id)
        if placement is None or placement.name != "IFCLOCALPLACEMENT":
            return (_IDENTITY, (0.0, 0.0, 0.0))

        parent_basis, parent_t = self._world_matrix(placement.arg(0))
        relative = self.get(placement.arg(1))
        if relative is not None and relative.name == "IFCAXIS2PLACEMENT3D":
            local_basis, local_t = self._axis2placement_matrix(relative)
        else:
            local_basis, local_t = (_IDENTITY, (0.0, 0.0, 0.0))

        basis = (
            _transform_dir(parent_basis, local_basis[0]),
            _transform_dir(parent_basis, local_basis[1]),
            _transform_dir(parent_basis, local_basis[2]),
        )
        translation = _add(parent_t, _transform_dir(parent_basis, local_t))
        self._matrices[ref.id] = (basis, translation)
        return (basis, translation)

    def _solid_corners(self, rep_ref: Any, placement_ref: Any) -> list[Point3]:
        """Every corner of a product's extruded solid, in world coordinates.

        This is the footprint a viewer subtracts from a wall. Reading it — rather
        than guessing from a placement origin and a filling element's stated
        width — is what puts a door where the model put it.
        """
        shape = self.get(rep_ref)
        if shape is None or shape.name != "IFCPRODUCTDEFINITIONSHAPE":
            return []
        basis, translation = self._world_matrix(placement_ref)

        out: list[Point3] = []
        for rep_id in _as_list(shape.arg(2)):
            rep = self.get(rep_id)
            if rep is None or rep.name != "IFCSHAPEREPRESENTATION":
                continue
            for item_ref in _as_list(rep.arg(3)):
                item = self.get(item_ref)
                if item is None:
                    continue
                if item.name == "IFCBOOLEANCLIPPINGRESULT":
                    item = self.get(item.arg(1))
                if item is None or item.name != "IFCEXTRUDEDAREASOLID":
                    continue
                profile = self._profile(item.arg(0))
                if not profile:
                    continue
                depth = (_numeric(item.arg(3)) or 0.0) * self._scale
                direction = _direction(self.get(item.arg(2))) or (0.0, 0.0, 1.0)

                # The solid's own Position, then the product's placement.
                position = self.get(item.arg(1))
                if position is not None and position.name == "IFCAXIS2PLACEMENT3D":
                    solid_basis, solid_t = self._axis2placement_matrix(position)
                else:
                    solid_basis, solid_t = (_IDENTITY, (0.0, 0.0, 0.0))

                for px, py in profile:
                    for depth_along in (0.0, depth):
                        local = (
                            px + direction[0] * depth_along,
                            py + direction[1] * depth_along,
                            direction[2] * depth_along,
                        )
                        in_product = _add(solid_t, _transform_dir(solid_basis, local))
                        out.append(_add(translation, _transform_dir(basis, in_product)))
        return out

    # -- reporting --------------------------------------------------------
    def _log_skipped(self, log: FidelityLog) -> None:
        """Name the product types that were present and never read.

        Counting what was *ignored by type* is as important as counting what
        failed to parse: a model full of IfcFurnishingElement is fine, and a model
        full of IfcSlab where the walls should be is a model this importer is the
        wrong tool for. Only the reader can tell which, so give them the list.
        """
        interesting = {
            "IFCSLAB": "floors and roofs are not part of a 2D layout",
            "IFCCOLUMN": "columns do not bound a room; they stand in one",
            "IFCBEAM": "structure above the ceiling plane",
            "IFCSTAIR": "vertical circulation is not modelled",
            "IFCSTAIRFLIGHT": "vertical circulation is not modelled",
            "IFCRAILING": "not part of a 2D layout",
            "IFCFURNISHINGELEMENT": "furniture does not affect the layout",
            "IFCFLOWTERMINAL": "services are not modelled",
            "IFCBUILDINGELEMENTPROXY": "an untyped element; nothing says what it is",
            "IFCROOF": "not part of a 2D layout",
            "IFCPLATE": "not part of a 2D layout",
            "IFCMEMBER": "not part of a 2D layout",
            "IFCCOVERING": "finishes do not change the room outline",
        }
        for name, reason in interesting.items():
            count = len(self._by_type.get(name, []))
            if count:
                # Counted as *seen* as well as skipped: coverage is only
                # meaningful against the entities an importer could plausibly
                # have used. Measuring it against every instance in the file --
                # every cartesian point, every ownership record -- would report
                # 8% for a model that was read perfectly.
                log.seen(count)
                log.skip(_ifc_label(name), reason, count)


# ---------------------------------------------------------------------------
# The STEP file itself
# ---------------------------------------------------------------------------

_INSTANCE_RE = re.compile(r"#(\d+)\s*=\s*([A-Za-z0-9_]+)\s*\(", re.ASCII)


def _parse_step(text: str) -> dict[int, Typed]:
    """Parse the DATA section of a STEP physical file into ``{id: Typed}``.

    Records are split on semicolons *outside* string literals, which is the one
    piece of lexing that matters: a room called ``Store; rear`` is not two
    records, and a naive split on ``;`` produces a corrupted file with no error.
    """
    start = text.find("DATA;")
    body = text[start + 5 :] if start >= 0 else text
    end = body.find("ENDSEC;")
    if end >= 0:
        body = body[:end]

    out: dict[int, Typed] = {}
    for record in _records(body):
        match = _INSTANCE_RE.match(record)
        if not match:
            continue
        eid = int(match.group(1))
        name = match.group(2).upper()
        args = _parse_args(record[match.end() : record.rfind(")")])
        out[eid] = Typed(name, args)
    return out


def _records(body: str) -> Iterable[str]:
    """Split on top-level semicolons, respecting strings and comments.

    Two pieces of lexing, both of which a naive ``body.split(";")`` gets wrong and
    neither of which announces itself when it fails:

    * **Strings.** A room called ``Store; rear`` is not two records.
    * **Comments.** ``/* ... */`` is legal anywhere in a STEP file and exporters
      use it freely -- to label storeys, to mark revisions. Left in place it
      glues itself to the front of the next instance, whose ``#123=`` then no
      longer starts the record, and that instance vanishes from the model with
      no error anywhere. A file with a comment above every storey loses every
      storey.
    """
    buf: list[str] = []
    in_string = False
    i = 0
    while i < len(body):
        ch = body[i]
        if not in_string and ch == "/" and body[i : i + 2] == "/*":
            end = body.find("*/", i + 2)
            i = len(body) if end < 0 else end + 2
            continue
        if in_string:
            if ch == "'":
                # '' inside a string is an escaped quote, not the end of one.
                if i + 1 < len(body) and body[i + 1] == "'":
                    buf.append("''")
                    i += 2
                    continue
                in_string = False
            buf.append(ch)
        elif ch == "'":
            in_string = True
            buf.append(ch)
        elif ch == ";":
            record = "".join(buf).strip()
            if record:
                yield record
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        yield tail


def _parse_args(text: str) -> list:
    """Parse a STEP argument list body (without its enclosing parentheses)."""
    args: list = []
    stack: list[list] = [args]
    buf: list[str] = []
    in_string = False
    i = 0

    def flush() -> None:
        nonlocal buf
        token = "".join(buf).strip()
        buf = []
        if token:
            stack[-1].append(_atom(token))

    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "'":
                if i + 1 < len(text) and text[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                in_string = False
                stack[-1].append("".join(buf[1:]))
                buf = []
            else:
                buf.append(ch)
            i += 1
            continue

        if ch == "'":
            flush()
            in_string = True
            buf.append(ch)
        elif ch == "(":
            token = "".join(buf).strip()
            buf = []
            child: list = []
            if token and re.fullmatch(r"[A-Za-z0-9_]+", token):
                # A typed value: IFCLENGTHMEASURE(304.8)
                stack[-1].append(Typed(token.upper(), child))
            else:
                stack[-1].append(child)
            stack.append(child)
        elif ch == ")":
            flush()
            if len(stack) > 1:
                stack.pop()
        elif ch == ",":
            flush()
        else:
            buf.append(ch)
        i += 1

    flush()
    return args


def _atom(token: str):
    """One scalar STEP token: a ref, an enum, a number, or a sentinel."""
    if token.startswith("#"):
        try:
            return Ref(int(token[1:]))
        except ValueError:
            return token
    if token == "$":
        return None
    if token == "*":
        return "*"
    if len(token) >= 2 and token.startswith(".") and token.endswith("."):
        inner = token[1:-1].upper()
        if inner == "T":
            return True
        if inner == "F":
            return False
        return Typed("ENUM", [inner])
    try:
        value = float(token)
    except ValueError:
        return token
    # `-0` is how a STEP file writes a west longitude or a south latitude of less
    # than one degree, and `int("-0")` is `0` with the sign thrown away -- which
    # puts the building in the wrong hemisphere. Keeping it as negative zero
    # preserves the sign for `math.copysign` to read back.
    if value == 0.0 and token.lstrip().startswith("-"):
        return -0.0
    return value if any(c in token for c in ".eE") else int(token)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _ifc_label(name: str) -> str:
    """``IFCBUILDINGSTOREY`` -> ``IfcBuildingStorey``, for a readable skip list."""
    return "Ifc" + name[3:].capitalize() if name.upper().startswith("IFC") else name


Point3 = tuple[float, float, float]

_IDENTITY: tuple[Point3, Point3, Point3] = (
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
)


def _direction(entity: Typed | None) -> Point3 | None:
    if entity is None or entity.name != "IFCDIRECTION":
        return None
    ratios = [_numeric(v) or 0.0 for v in _as_list(entity.arg(0))]
    if len(ratios) < 3:
        ratios = ratios + [0.0] * (3 - len(ratios))
    return _normalize((ratios[0], ratios[1], ratios[2]))


def _normalize(v: Point3) -> Point3 | None:
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if length < 1e-9:
        return None
    return (v[0] / length, v[1] / length, v[2] / length)


def _perpendicular(z: Point3) -> Point3:
    """Any unit vector perpendicular to ``z`` -- the schema's default X axis."""
    candidate: Point3 = (1.0, 0.0, 0.0) if abs(z[0]) < 0.9 else (0.0, 1.0, 0.0)
    dot = _dot(candidate, z)
    return (
        _normalize(
            (candidate[0] - dot * z[0], candidate[1] - dot * z[1], candidate[2] - dot * z[2])
        )
        or (1.0, 0.0, 0.0)
    )


def _dot(a: Point3, b: Point3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Point3, b: Point3) -> Point3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _add(a: Point3, b: Point3) -> Point3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _transform_dir(basis: tuple[Point3, Point3, Point3], v: Point3) -> Point3:
    """``v`` expressed in the frame whose axes are ``basis``."""
    x, y, z = basis
    return (
        x[0] * v[0] + y[0] * v[1] + z[0] * v[2],
        x[1] * v[0] + y[1] * v[1] + z[1] * v[2],
        x[2] * v[0] + y[2] * v[1] + z[2] * v[2],
    )


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _enum(value: Any) -> str:
    if isinstance(value, Typed) and value.name == "ENUM":
        return str(value.args[0]) if value.args else ""
    if isinstance(value, str):
        return value.strip(".").upper()
    return ""


def _numeric(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, Typed) and value.args:
        return _numeric(value.args[0])
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _compound_angle(value: Any) -> float | None:
    """IFC compound-plane-angle ``(deg, min, sec[, millionths])`` to decimal degrees.

    The sign lives on the *degrees* component alone, so a location at 51 deg 30' S
    is ``(-51, 30, 0)`` and naively summing gives -50.5. Getting this wrong puts
    the building in the wrong hemisphere by half a degree, which is exactly the
    kind of error that survives review because the number still looks reasonable.
    """
    parts = [
        _numeric(v)
        for v in _as_list(value)
        if _numeric(v) is not None or isinstance(v, (int, float))
    ]
    parts = [p for p in parts if p is not None]
    if not parts:
        return None
    # copysign, not `< 0`: the degrees component is negative *zero* for any
    # location within one degree of the equator or the prime meridian, and
    # `-0.0 < 0` is False.
    sign = math.copysign(1.0, parts[0])
    total = abs(parts[0])
    if len(parts) > 1:
        total += abs(parts[1]) / 60.0
    if len(parts) > 2:
        total += abs(parts[2]) / 3600.0
    if len(parts) > 3:
        total += abs(parts[3]) / 3_600_000_000.0
    return round(sign * total, 8)


def _point2(entity: Typed | None, scale: float) -> Point | None:
    if entity is None or entity.name not in ("IFCCARTESIANPOINT", "IFCPOINT"):
        return None
    coords = [(_numeric(c) or 0.0) * scale for c in _as_list(entity.arg(0))]
    if len(coords) < 2:
        return None
    return (coords[0], coords[1])


def _apply(p: Point, tx: float, ty: float, cos_t: float, sin_t: float) -> Point:
    return (tx + p[0] * cos_t - p[1] * sin_t, ty + p[0] * sin_t + p[1] * cos_t)



def _extent_along(
    corners: list[Point3], axis: list[Point]
) -> tuple[float, float, float, float] | None:
    """Where a solid sits on a wall: ``(centre, width, bottom, top)`` in metres.

    Projects every corner of the solid onto the wall's axis and takes the span.
    That is the measurement a boolean subtraction would make, and it is immune to
    where the profile's own origin happens to sit or which way the placement is
    turned -- the two things that put a naively-placed door half a leaf out.
    """
    if len(corners) < 2 or len(axis) < 2:
        return None
    (ax, ay), (bx, by) = axis[0], axis[-1]
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length <= 0:
        return None
    ux, uy = dx / length, dy / length

    alongs = [(c[0] - ax) * ux + (c[1] - ay) * uy for c in corners]
    zs = [c[2] for c in corners]
    lo, hi = min(alongs), max(alongs)
    return ((lo + hi) / 2.0, hi - lo, min(zs), max(zs))


def _project_along(axis: list[Point], pt: Point) -> float:
    (ax, ay), (bx, by) = axis[0], axis[-1]
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 0:
        return 0.0
    t = ((pt[0] - ax) * dx + (pt[1] - ay) * dy) / length_sq
    return max(0.0, min(1.0, t)) * math.sqrt(length_sq)


def _median_line(ring: list[Point]) -> list[Point] | None:
    """The centre line of a long thin footprint -- a wall's axis, recovered.

    Takes the footprint's minimum-area rectangle and returns the line joining the
    midpoints of its two short sides. Exact for a rectangular wall, and sensible
    for anything close to one.
    """
    from ..geometry import oriented_extents, polygon_centroid

    length, width, angle = oriented_extents(ring)
    if length <= 0 or width <= 0:
        return None
    cx, cy = polygon_centroid(ring)
    rad = math.radians(angle)
    half = length / 2.0
    return [
        (cx - half * math.cos(rad), cy - half * math.sin(rad)),
        (cx + half * math.cos(rad), cy + half * math.sin(rad)),
    ]


def _short_side(ring: list[Point]) -> float:
    from ..geometry import oriented_extents

    return oriented_extents(ring)[1]




