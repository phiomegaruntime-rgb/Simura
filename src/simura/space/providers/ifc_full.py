"""The same IFC job, done by a real geometry kernel -- if one is installed.

:mod:`simura.space.providers.ifc` reads IFC in pure Python because a repository
people clone to read should not have a binary dependency at its centre. That is
the right default and it is not the right answer for everybody: a model whose
rooms are B-reps, whose walls are swept along curves, or which leans on mapped
representations is a model the native reader will decline to guess about, and
somebody with that model in front of them would rather install a wheel than lose
half their building.

So this is the escape hatch, and it is deliberately built the way SciPy is built
into :mod:`simura.validate`: an **optional extra** (``pip install simura[bim]``),
behind the same :class:`~simura.space.provider.PlanProvider` interface, producing
the same :class:`~simura.space.plan.FloorPlan`. Nothing downstream can tell which
of the two read the file, except by looking at ``fidelity.source_format`` -- which
is exactly where it should be able to tell.

The division of labour is worth stating, because it is the whole reason this
module is short. ``ifcopenshell`` is a geometry kernel: it turns any
representation into triangles. It is *not* a floor-plan extractor, and the part
this component actually cares about -- which room is an office, how high is the
ceiling, where is true north -- is the same property-and-structure reading the
native importer already does. So this module borrows the kernel for the one thing
the kernel is for (turn a shape into a footprint) and reuses everything else.

Install it with::

    pip install "simura[bim]"

and the ``ifc_full`` provider type becomes available. Without it, asking for
``ifc_full`` raises a message saying so rather than failing obscurely -- and
``ifc`` keeps working, as it always does.
"""

from __future__ import annotations

from typing import Any

from ..fidelity import FidelityLog
from ..geometry import Point, normalize_polygon, polygon_area
from ..occupancy import classify
from ..plan import FloorPlan, Georeference, Level, Space, Wall
from ..provider import PlanError

INSTALL_HINT = (
    "the 'ifc_full' provider needs ifcopenshell, which is not installed. "
    "Install it with: pip install \"simura[bim]\" — or use the 'ifc' provider, "
    "which reads IFC with no extra dependency."
)

# Below this, a horizontal slice through a solid is a sliver rather than a room.
MIN_FOOTPRINT_AREA_M2 = 0.5


def available() -> bool:
    """True when ``ifcopenshell`` can be imported."""
    try:
        import ifcopenshell  # noqa: F401
    except Exception:
        return False
    return True


class IfcFullProvider:
    """A floor plan from IFC, with geometry resolved by ``ifcopenshell``."""

    format = "ifc_full"

    def __init__(self, path: str, *, name: str = "") -> None:
        self.path = str(path)
        self.name = name or self.path.rsplit("/", 1)[-1]
        self._plan: FloorPlan | None = None

    def plan(self) -> FloorPlan:
        if self._plan is None:
            self._plan = self._build()
        return self._plan

    def _build(self) -> FloorPlan:
        try:
            import ifcopenshell
            import ifcopenshell.geom as geom
            import ifcopenshell.util.unit as unit_util
        except Exception as exc:  # pragma: no cover - depends on the environment
            raise PlanError(f"{INSTALL_HINT} ({exc})") from None

        log = FidelityLog(self.format, self.name)
        log.hash_file(self.path)
        try:
            model = ifcopenshell.open(self.path)
        except Exception as exc:
            raise PlanError(f"ifcopenshell could not open {self.name}: {exc}") from None

        scale = float(unit_util.calculate_unit_scale(model) or 1.0)
        settings = geom.settings()
        # World coordinates means the kernel composes the placement chain, which is
        # the part the native reader has to do by hand.
        settings.set(settings.USE_WORLD_COORDS, True)

        levels = self._levels(model, scale, log)
        spaces = self._spaces(model, geom, settings, levels, log)
        walls = self._walls(model, geom, settings, levels, log)
        georef = self._site(model, scale, log)

        if not spaces and not walls:
            raise PlanError(
                f"{self.name} opened, but produced no spaces and no walls with "
                f"readable geometry"
            )

        return FloorPlan(
            name=getattr(next(iter(model.by_type("IfcProject")), None), "Name", "")
            or self.name,
            georeference=georef,
            levels=levels,
            spaces=spaces,
            walls=walls,
            fidelity=log.freeze(),
            source_units="m",
        )

    # -- pieces -----------------------------------------------------------
    def _levels(self, model: Any, scale: float, log: FidelityLog) -> list[Level]:
        found: list[Level] = []
        for storey in model.by_type("IfcBuildingStorey"):
            log.seen()
            found.append(
                Level(
                    id=str(storey.GlobalId or storey.id()),
                    name=str(storey.Name or f"Level {len(found)}"),
                    elevation_m=float(getattr(storey, "Elevation", 0.0) or 0.0) * scale,
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
            out.append(Level(**{**level.__dict__, "height_m": height}))
        return out or [Level(id="level-0", name="Level 0")]

    def _spaces(
        self, model: Any, geom: Any, settings: Any, levels: list[Level], log: FidelityLog
    ) -> list[Space]:
        default_level = levels[0].id if levels else "level-0"
        out: list[Space] = []
        for product in model.by_type("IfcSpace"):
            log.seen()
            footprint, height = _footprint(product, geom, settings, log)
            if footprint is None:
                log.skip("IfcSpace", "ifcopenshell produced no shape for this space")
                continue

            sid = str(product.GlobalId or product.id())
            name = str(product.Name or "")
            long_name = str(getattr(product, "LongName", "") or "")
            predefined = str(getattr(product, "PredefinedType", "") or "")
            occupancy, basis = classify(
                name=name, long_name=long_name, ifc_predefined_type=predefined
            )
            inferred: list[str] = []
            if occupancy == "unknown" or predefined.upper() in ("", "NOTDEFINED"):
                log.infer(f"space:{sid}", "occupancy", occupancy, basis)
                inferred.append("occupancy")

            out.append(
                Space(
                    id=sid,
                    name=long_name or name or f"Space {len(out) + 1}",
                    level_id=_storey_of(product) or default_level,
                    polygon=footprint,
                    height_m=round(height, 4) if height > 0.5 else 2.7,
                    occupancy=occupancy,
                    inferred=inferred,
                )
            )
            log.used()
        return out

    def _walls(
        self, model: Any, geom: Any, settings: Any, levels: list[Level], log: FidelityLog
    ) -> list[Wall]:
        from .ifc import _median_line, _short_side

        default_level = levels[0].id if levels else "level-0"
        out: list[Wall] = []
        for product in model.by_type("IfcWall"):
            log.seen()
            footprint, height = _footprint(product, geom, settings, log)
            if footprint is None or len(footprint) < 3:
                log.skip("IfcWall", "ifcopenshell produced no shape for this wall")
                continue
            axis = _median_line(footprint)
            if axis is None:
                continue
            wid = str(product.GlobalId or product.id())
            thickness = _short_side(footprint)
            log.infer(
                f"wall:{wid}",
                "thickness_m",
                round(thickness, 4),
                "short side of the resolved solid's footprint",
            )
            out.append(
                Wall(
                    id=wid,
                    level_id=_storey_of(product) or default_level,
                    axis=axis,
                    thickness_m=round(thickness, 4),
                    height_m=round(height, 4) if height > 0.3 else 3.0,
                    inferred=["thickness_m"],
                )
            )
            log.used()
        return out

    def _site(self, model: Any, scale: float, log: FidelityLog) -> Georeference:
        from .ifc import _compound_angle

        for site in model.by_type("IfcSite"):
            lat = _compound_angle(list(site.RefLatitude or []))
            lon = _compound_angle(list(site.RefLongitude or []))
            if lat is None and lon is None:
                continue
            return Georeference(
                latitude=lat,
                longitude=lon,
                elevation_m=float(getattr(site, "RefElevation", 0.0) or 0.0) * scale,
            )
        log.warn("no IfcSite coordinates — weather cannot be configured from the model")
        return Georeference()


def _footprint(
    product: Any, geom: Any, settings: Any, log: FidelityLog
) -> tuple[list[Point] | None, float]:
    """A solid's plan outline and its height, from the kernel's triangle mesh.

    The kernel gives vertices; the footprint is their convex outline in plan and
    the height is their z-extent. Using the convex outline rather than a true
    horizontal section is the deliberate simplification: a section needs a
    half-space intersection to be correct for a concave room, and a room's convex
    outline is what a lighting calculation wants anyway. Concave rooms are
    recorded as such by ``Space.rectangular()`` being false downstream.
    """
    from ..geometry import convex_hull

    try:
        shape = geom.create_shape(settings, product)
    except Exception:
        return (None, 0.0)

    verts = list(getattr(shape.geometry, "verts", []) or [])
    if len(verts) < 9:
        return (None, 0.0)

    xy = [(verts[i], verts[i + 1]) for i in range(0, len(verts) - 2, 3)]
    zs = [verts[i + 2] for i in range(0, len(verts) - 2, 3)]
    ring = normalize_polygon(convex_hull(xy))
    if len(ring) < 3 or polygon_area(ring) < MIN_FOOTPRINT_AREA_M2:
        return (None, 0.0)
    return (ring, max(zs) - min(zs))


def _storey_of(product: Any) -> str:
    """The GlobalId of the storey a product is contained in, if any."""
    for rel in getattr(product, "ContainedInStructure", []) or []:
        structure = getattr(rel, "RelatingStructure", None)
        if structure is not None and structure.is_a("IfcBuildingStorey"):
            return str(structure.GlobalId or structure.id())
    decomposes = getattr(product, "Decomposes", []) or []
    for rel in decomposes:
        parent = getattr(rel, "RelatingObject", None)
        if parent is not None and parent.is_a("IfcBuildingStorey"):
            return str(parent.GlobalId or parent.id())
    return ""
