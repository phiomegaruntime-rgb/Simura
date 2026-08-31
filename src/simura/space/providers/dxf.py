"""DXF: the drawing everybody actually has.

IFC is the right answer and gbXML is the convenient one, but the file a person
can produce from any CAD package in two clicks, without a consultant and without
a plug-in, is a DXF. If this component only read the formats a well-run BIM
process emits, it would be useless to most of the people who would benefit from
it, so DXF is a first-class source.

What makes it hard is what makes it easy: DXF has **no idea what a building is**.
It is lines on layers. There is no ``Space``, no room name, no storey, no wall
thickness, no unit half the time. Everything this importer produces is therefore
inferred from convention rather than read from structure, and it says so on every
single value.

The convention it reads
-----------------------

Drawing conventions are not a standard, but they are remarkably consistent --
every office in the world puts walls on a layer with "wall" in the name, and the
AIA/ISO 13567 layer schemes (``A-WALL``, ``A-AREA-IDEN``) make that formal. So:

* **Walls** come from ``LINE`` and ``LWPOLYLINE`` entities on a layer whose name
  contains a wall keyword.
* **Rooms** come from **closed** polylines on a room/area layer. This is the part
  that makes a DXF simulable: a closed loop on ``A-AREA`` is somebody having
  already drawn the room boundary.
* **Room names** come from ``TEXT``/``MTEXT`` whose insertion point falls *inside*
  one of those loops -- which is where a room label is, by definition.
* Everything else -- arcs, splines, blocks, hatches, dimensions -- is counted and
  skipped.

If a drawing has no room layer, the import still succeeds and produces walls with
no spaces, and the fidelity record says exactly that. Walls with no rooms is a
useful plan: it is enough to walk through in the world, and enough to route a
cable along.

The unit problem, at its worst
------------------------------

``$INSUNITS`` is the header variable that says what a drawing is drawn in, and it
is very often ``0`` -- unitless. That leaves the importer with a pile of numbers
and no scale, and no honest way out other than a guess with a stated basis:
buildings are tens of metres across, so a drawing spanning 45,000 units is
millimetres. See :func:`simura.space.units.guess_scale`, and note that the guess
is recorded as an inference on the plan itself rather than buried.
"""

from __future__ import annotations

from typing import Iterator

from .. import units
from ..fidelity import FidelityLog
from ..geometry import (
    normalize_polygon,
    point_in_polygon,
    polygon_area,
    polygon_bounds,
)
from ..occupancy import classify
from ..plan import FloorPlan, Level, Space, Wall
from ..provider import PlanError
from .file import FilePlanProvider

# Layer-name keywords, matched case-insensitively as substrings. Substrings are
# right here (unlike room *names*, where whole words matter): layer names are
# machine-ish tokens like `A-WALL-FULL` and `I-WALL-MOVE`, and the useful part is
# always a fragment of a longer compound.
WALL_LAYERS = ("wall", "wand", "waende", "wände", "mur", "muro", "partition", "-wal")
ROOM_LAYERS = ("room", "space", "area", "raum", "rooms", "zone", "local", "piece")
DOOR_LAYERS = ("door", "tuer", "tür", "porte", "puerta")

# Entities this importer knows how to turn into geometry. Anything else is
# counted, named and skipped.
GEOMETRY_ENTITIES = ("LINE", "LWPOLYLINE", "POLYLINE")

DEFAULT_WALL_THICKNESS_M = 0.2
DEFAULT_WALL_HEIGHT_M = 3.0
DEFAULT_ROOM_HEIGHT_M = 2.7

# A closed polyline smaller than this is a door swing, a symbol or a hatch
# boundary, not a room. Two square metres is smaller than any room a person
# occupies and larger than every symbol.
MIN_ROOM_AREA_M2 = 2.0


class DxfProvider(FilePlanProvider):
    """A floor plan from an ASCII DXF drawing.

    ``wall_layers`` / ``room_layers`` override the built-in keyword lists, for a
    drawing that follows an office convention this does not know. Passing them is
    also the honest way to import a drawing whose layers are called ``0`` and
    ``Layer1``.
    """

    format = "dxf"

    def __init__(
        self,
        path: str | None = None,
        *,
        data: bytes | None = None,
        name: str = "",
        wall_layers: tuple[str, ...] | None = None,
        room_layers: tuple[str, ...] | None = None,
        scale: float | None = None,
        wall_height_m: float = DEFAULT_WALL_HEIGHT_M,
        wall_thickness_m: float = DEFAULT_WALL_THICKNESS_M,
        room_height_m: float = DEFAULT_ROOM_HEIGHT_M,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__(path, data=data, name=name, encoding=encoding)
        self.wall_layers = tuple(w.lower() for w in (wall_layers or WALL_LAYERS))
        self.room_layers = tuple(r.lower() for r in (room_layers or ROOM_LAYERS))
        self.scale = scale
        self.wall_height_m = float(wall_height_m)
        self.wall_thickness_m = float(wall_thickness_m)
        self.room_height_m = float(room_height_m)

    def _parse(self, log: FidelityLog) -> FloorPlan:
        text = self.text()
        if "SECTION" not in text or "ENTITIES" not in text:
            raise PlanError(
                f"{self.name} does not look like an ASCII DXF "
                f"(no SECTION/ENTITIES). Binary DXF is not supported — "
                f"re-export as ASCII DXF."
            )

        header, entities = _read_dxf(text)
        for e in entities:
            log.seen()

        scale, unit_name = self._resolve_scale(header, entities, log)

        polylines: list[dict] = []
        lines: list[dict] = []
        labels: list[tuple[tuple[float, float], str]] = []
        skipped: dict[str, int] = {}

        for e in entities:
            kind = e["type"]
            layer = str(e.get("layer", "")).lower()
            if kind == "LINE":
                lines.append(e)
            elif kind in ("LWPOLYLINE", "POLYLINE"):
                polylines.append(e)
            elif kind in ("TEXT", "MTEXT"):
                if e.get("text") and e.get("points"):
                    x, y = e["points"][0]
                    labels.append(((x * scale, y * scale), str(e["text"])))
            else:
                skipped[kind] = skipped.get(kind, 0) + 1
            del layer

        spaces = self._build_spaces(polylines, labels, scale, log)
        walls = self._build_walls(lines, polylines, scale, log)

        for kind, count in sorted(skipped.items()):
            log.skip(
                f"DXF {kind}",
                "not a line or a polyline — a 2D layout is built from straight runs",
                count,
            )

        if not spaces and not walls:
            raise PlanError(
                f"{self.name} has no lines or polylines on any layer matching "
                f"{self.wall_layers} or {self.room_layers}. Pass wall_layers / "
                f"room_layers to name this drawing's own layer convention."
            )
        if not spaces:
            log.warn(
                "no closed polylines on a room layer, so the plan has walls but no "
                "rooms — nothing here can be lit or given an occupancy until room "
                "boundaries exist"
            )

        level = Level(id="level-0", name="Level 0", elevation_m=0.0, height_m=self.wall_height_m)
        log.default(
            "plan",
            "levels",
            1,
            "a DXF drawing is one sheet; it carries no storey structure",
        )

        plan = FloorPlan(
            name=self.name,
            levels=[level],
            spaces=spaces,
            walls=walls,
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
    def _resolve_scale(
        self, header: dict[str, list], entities: list[dict], log: FidelityLog
    ) -> tuple[float, str]:
        if self.scale is not None:
            log.infer("plan", "units", self.scale, "scale supplied by the caller")
            return (float(self.scale), "custom")

        code = header.get("$INSUNITS", [None])[0]
        unit = units.DXF_INSUNITS.get(int(code), "") if code is not None else ""
        if unit and units.known(unit):
            return (units.factor(unit), unit)

        extent = _drawing_extent(header, entities)
        factor, guessed, basis = units.guess_scale(extent)
        log.infer("plan", "units", guessed, f"$INSUNITS is unset or unitless; {basis}")
        return (factor, guessed)

    # -- rooms ------------------------------------------------------------
    def _build_spaces(
        self,
        polylines: list[dict],
        labels: list[tuple[tuple[float, float], str]],
        scale: float,
        log: FidelityLog,
    ) -> list[Space]:
        spaces: list[Space] = []
        for e in polylines:
            if not _layer_matches(e.get("layer", ""), self.room_layers):
                continue
            if not e.get("closed"):
                log.skip(
                    "DXF LWPOLYLINE (room layer)",
                    "polyline is not closed, so it does not bound a room",
                )
                continue
            ring = normalize_polygon([(x * scale, y * scale) for x, y in e["points"]])
            if len(ring) < 3 or polygon_area(ring) < MIN_ROOM_AREA_M2:
                log.skip(
                    "DXF LWPOLYLINE (room layer)",
                    f"closed loop smaller than {MIN_ROOM_AREA_M2:g} m² — a symbol "
                    f"or a door swing rather than a room",
                )
                continue

            sid = f"space-{len(spaces)}"
            label = _label_inside(ring, labels)
            occupancy, basis = classify(name=label)
            inferred = ["height_m", "occupancy"]
            log.default(
                f"space:{sid}",
                "height_m",
                self.room_height_m,
                "DXF is a 2D drawing and states no ceiling height",
            )
            log.infer(
                f"space:{sid}",
                "occupancy",
                occupancy,
                basis if label else "no text label falls inside this room boundary",
            )
            spaces.append(
                Space(
                    id=sid,
                    name=label or f"Room {len(spaces) + 1}",
                    level_id="level-0",
                    polygon=ring,
                    height_m=self.room_height_m,
                    occupancy=occupancy,
                    inferred=inferred,
                )
            )
            log.used()
        return spaces

    # -- walls ------------------------------------------------------------
    def _build_walls(
        self, lines: list[dict], polylines: list[dict], scale: float, log: FidelityLog
    ) -> list[Wall]:
        walls: list[Wall] = []

        def add(axis: list[tuple[float, float]]) -> None:
            wid = f"wall-{len(walls)}"
            log.default(
                f"wall:{wid}",
                "thickness_m",
                self.wall_thickness_m,
                "a DXF wall is a line; its thickness is not in the drawing",
            )
            log.default(
                f"wall:{wid}",
                "height_m",
                self.wall_height_m,
                "a DXF wall is a line; its height is not in the drawing",
            )
            walls.append(
                Wall(
                    id=wid,
                    level_id="level-0",
                    axis=axis,
                    thickness_m=self.wall_thickness_m,
                    height_m=self.wall_height_m,
                    inferred=["thickness_m", "height_m"],
                )
            )
            log.used()

        for e in lines:
            if not _layer_matches(e.get("layer", ""), self.wall_layers):
                continue
            pts = [(x * scale, y * scale) for x, y in e["points"]]
            if len(pts) >= 2:
                add([pts[0], pts[-1]])

        for e in polylines:
            if not _layer_matches(e.get("layer", ""), self.wall_layers):
                continue
            pts = normalize_polygon([(x * scale, y * scale) for x, y in e["points"]])
            if len(pts) < 2:
                continue
            ring = pts + [pts[0]] if e.get("closed") else pts
            # A polyline is a run of walls, not one wall: splitting it into
            # segments is what lets each stretch carry its own length, and it is
            # the shape the world extrudes and the router walks.
            for i in range(len(ring) - 1):
                add([ring[i], ring[i + 1]])

        return walls


# ---------------------------------------------------------------------------
# The DXF file itself
# ---------------------------------------------------------------------------

def _read_dxf(text: str) -> tuple[dict[str, list], list[dict]]:
    """Split an ASCII DXF into its header variables and its entities.

    A DXF is a flat stream of ``(group code, value)`` pairs on alternating lines,
    with structure implied by ``0`` records. That makes a full parser large and a
    *useful* parser small: track which section we are in, start a new entity on
    each ``0``, and accumulate the codes that matter.
    """
    header: dict[str, list] = {}
    entities: list[dict] = []
    section = ""
    current: dict | None = None
    header_var = ""

    for code, value in _pairs(text):
        if code == 0:
            if section == "ENTITIES" and current is not None:
                entities.append(current)
                current = None
            if value == "SECTION":
                section = ""
            elif value == "ENDSEC":
                section = ""
            elif section == "ENTITIES":
                current = {"type": value, "points": [], "layer": "", "closed": False}
            continue

        if code == 2 and not section:
            section = value
            continue

        if section == "HEADER":
            if code == 9:
                header_var = value
                header.setdefault(header_var, [])
            elif header_var:
                header[header_var].append(_maybe_number(value))
            continue

        if current is None:
            continue

        if code == 8:
            current["layer"] = value
        elif code in (10, 11):
            current.setdefault("_x", []).append(_number(value))
        elif code in (20, 21):
            xs = current.get("_x") or [0.0]
            current["points"].append((xs[-1], _number(value)))
        elif code == 70 and current["type"] in ("LWPOLYLINE", "POLYLINE"):
            current["closed"] = bool(int(_number(value)) & 1)
        elif code in (1, 3) and current["type"] in ("TEXT", "MTEXT"):
            current["text"] = str(current.get("text", "")) + value

    if current is not None:
        entities.append(current)

    # Old-style POLYLINE carries its vertices as following VERTEX entities, so
    # they are folded back into their owner here rather than complicating the
    # loop above. Ignoring this would silently lose every wall in a drawing saved
    # by an older package -- which is exactly the drawing most likely to turn up.
    folded: list[dict] = []
    for e in entities:
        if e["type"] == "VERTEX" and folded and folded[-1]["type"] == "POLYLINE":
            folded[-1]["points"].extend(e["points"])
        elif e["type"] == "SEQEND":
            continue
        else:
            folded.append(e)

    return header, folded


def _pairs(text: str) -> Iterator[tuple[int, str]]:
    """The ``(code, value)`` stream, tolerating whichever line ending it has."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for i in range(0, len(lines) - 1, 2):
        raw = lines[i].strip()
        if not raw:
            continue
        try:
            code = int(raw)
        except ValueError:
            continue
        yield code, lines[i + 1].strip()


def _number(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0


def _maybe_number(value: str) -> float | str:
    try:
        return float(value)
    except ValueError:
        return value


def _layer_matches(layer: str, keywords: tuple[str, ...]) -> bool:
    name = str(layer).lower()
    return any(k in name for k in keywords)


def _label_inside(
    ring: list[tuple[float, float]], labels: list[tuple[tuple[float, float], str]]
) -> str:
    """The text label whose insertion point falls in this room, if there is one."""
    for pt, text in labels:
        if point_in_polygon(pt, ring):
            return text.strip()
    return ""


def _drawing_extent(header: dict[str, list], entities: list[dict]) -> float:
    """The longest side of the drawing, for guessing its unit.

    Prefers ``$EXTMIN``/``$EXTMAX`` when the file states them, because they are
    the drawing's own answer; falls back to the entity coordinates, because a
    surprising number of files carry stale or absent extents.
    """
    lo, hi = header.get("$EXTMIN"), header.get("$EXTMAX")
    if lo and hi and len(lo) >= 2 and len(hi) >= 2:
        try:
            span = max(float(hi[0]) - float(lo[0]), float(hi[1]) - float(lo[1]))
            if span > 0:
                return span
        except (TypeError, ValueError):
            pass
    pts = [p for e in entities for p in e.get("points", [])]
    if not pts:
        return 0.0
    min_x, min_y, max_x, max_y = polygon_bounds(pts)
    return max(max_x - min_x, max_y - min_y)
