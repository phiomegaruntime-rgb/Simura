"""How long the cable actually is.

The single most valuable thing a building gives an electrical simulation, and the
number that until now had to be typed in from somebody's memory.

:mod:`simura.wires` computes voltage drop, ohmic loss and conductor temperature
from a length in metres. Every one of those scales with that length, so the whole
answer rests on it -- and in the 2D wiring planner it is a guess, while in the 3D
world it is the distance the player walked, which is honest but only exists
because there *is* a player. With a floor plan, the length can be *computed*, from
the building the run will actually be installed in.

The model
---------

A cable does not fly. It runs along a tray at ceiling level, through the openings
between rooms, and drops down to the equipment at each end::

    length = drop_start + sum(horizontal legs) + drop_end + slack

with the horizontal legs found as the shortest path through a graph whose nodes
are **room centres and doorways**, and whose edges are straight runs across a
room from one opening to another. That graph is the building's own connectivity:
two rooms are joined if a door joins them, and the path a cable takes between
them is the path a person walks.

This is deliberately not a visibility graph or a maze solve over a raster of the
plan. Both would produce a shorter number, and both would be wrong in the same
way -- an installed cable does not cut the corner diagonally across an open plan
office, and it does not pass through a wall because the geometry did not stop it.
Room-to-room through the openings is what the conduit does.

What the result carries
-----------------------

A :class:`Route` is not just a number. It carries the **legs**, so a person can
see where the length went; the rooms it passes through, so the ambient along the
run can vary; and its ``problems``, so a route that had to be estimated says so
rather than returning a confident total. That last part is this component's usual
commitment: a computed length is worth having precisely because it is checkable,
and a length nobody can check is no better than the guess it replaced.

Ambient along the run
---------------------

A run that leaves a conditioned office, crosses an unconditioned plant room and
ends in a yard is three different ambients, and :mod:`simura.wires` derates
ampacity against ambient. :meth:`Route.hottest_ambient` gives the worst one,
because a conductor's rating is decided by the worst metre of it -- which is the
correct and slightly counter-intuitive answer, and the reason a route needs to
know which rooms it passed through rather than only how far it went.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import asdict, dataclass, field
from typing import Any

from .geometry import Point, distance
from .plan import FloorPlan, Opening, Space

# How far either side of an opening to look for the rooms it joins. A doorway's
# own midpoint sits inside the wall, which is in neither room, so the probe has to
# step clear of the wall's own thickness before asking.
DOORWAY_PROBE_M = 0.35

# Installed cable is longer than the geometric path: it is dressed into trays,
# looped at terminations and pulled with slack for future re-termination. Five
# percent is the low end of what an estimator would add, chosen so the number
# stays defensible; it is a parameter because every office has its own rule.
DEFAULT_SLACK_FRAC = 0.05

# Where the tray runs, as a height above the floor. Equipment sits on the floor,
# so this is what a drop costs at each end -- twice.
DEFAULT_TRAY_HEIGHT_M = 2.6


@dataclass
class Leg:
    """One straight stretch of the run, and what kind of stretch it is."""

    kind: str  # "drop" | "horizontal" | "riser"
    length_m: float
    from_point: tuple[float, float] | None = None
    to_point: tuple[float, float] | None = None
    space_id: str = ""
    space_name: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Route:
    """A cable run through a building: how long, through where, and how sure."""

    length_m: float
    horizontal_m: float
    vertical_m: float
    slack_m: float
    legs: list[Leg] = field(default_factory=list)
    path: list[tuple[float, float]] = field(default_factory=list)
    space_ids: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def hottest_ambient(self, plan: FloorPlan, sample: Any = None) -> float | None:
        """The worst ambient any metre of this run is in.

        A conductor's ampacity is set by its hottest point, not its average, so a
        run that spends 30 m in a cool corridor and 2 m in a plant room is rated
        for the plant room. Returns ``None`` when no room on the route says
        anything about its environment.
        """
        from .couple import ambient_for

        temps = [
            ctx.ambient_c
            for sid in self.space_ids
            if (ctx := ambient_for(plan, sid, sample)) is not None
        ]
        return max(temps) if temps else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "length_m": round(self.length_m, 4),
            "horizontal_m": round(self.horizontal_m, 4),
            "vertical_m": round(self.vertical_m, 4),
            "slack_m": round(self.slack_m, 4),
            "legs": [leg.to_dict() for leg in self.legs],
            "path": [[round(x, 4), round(y, 4)] for x, y in self.path],
            "space_ids": list(self.space_ids),
            "problems": list(self.problems),
            "ok": self.ok,
        }

    def wire_kwargs(self, wire_type: str, ambient_temp_c: float = 25.0) -> dict[str, Any]:
        """The ``simura.wires`` spec for this run: a type, a length, an ambient.

        Exactly what ``/api/wires/evaluate`` and a network ``segment`` already
        take, so a routed length drops into the existing solve with nothing
        translated.
        """
        return {
            "wire_type": wire_type,
            "length_m": round(self.length_m, 4),
            "ambient_temp_c": float(ambient_temp_c),
        }


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Node:
    key: str
    point: Point
    level_id: str
    space_id: str = ""


def doorway_point(plan: FloorPlan, opening: Opening) -> Point | None:
    """Where an opening is, in plan coordinates.

    An opening is stored as a distance along its wall, because that is how it
    survives the wall being moved. Turning it back into a point is this one
    calculation, and it lives here rather than on the dataclass because it needs
    the wall.
    """
    wall = plan.wall(opening.wall_id)
    if wall is None or len(wall.axis) < 2:
        return None
    return _along_axis(wall.axis, opening.along_m)


def _along_axis(axis: list[Point], along_m: float) -> Point:
    """The point ``along_m`` metres from the start of a polyline."""
    remaining = max(0.0, float(along_m))
    for i in range(len(axis) - 1):
        seg = distance(axis[i], axis[i + 1])
        if seg <= 0:
            continue
        if remaining <= seg:
            t = remaining / seg
            return (
                axis[i][0] + (axis[i + 1][0] - axis[i][0]) * t,
                axis[i][1] + (axis[i + 1][1] - axis[i][1]) * t,
            )
        remaining -= seg
    return axis[-1]


def doorway_spaces(plan: FloorPlan, opening: Opening) -> tuple[Point | None, list[str]]:
    """The rooms an opening joins, found geometrically.

    Probing perpendicular to the wall on both sides rather than trusting a
    relationship in the file, because the three importers disagree about whether
    that relationship even exists -- gbXML states it, IFC implies it through a
    void-and-fill chain, and DXF has never heard of it. Geometry is the one thing
    all three do have.
    """
    point = doorway_point(plan, opening)
    wall = plan.wall(opening.wall_id)
    if point is None or wall is None or len(wall.axis) < 2:
        return (point, [])

    dx = wall.axis[-1][0] - wall.axis[0][0]
    dy = wall.axis[-1][1] - wall.axis[0][1]
    norm = math.hypot(dx, dy) or 1.0
    # Perpendicular to the wall, stepping clear of its own thickness.
    step = wall.thickness_m / 2.0 + DOORWAY_PROBE_M
    nx, ny = -dy / norm * step, dx / norm * step

    found: list[str] = []
    for probe in ((point[0] + nx, point[1] + ny), (point[0] - nx, point[1] - ny)):
        space = plan.space_at(probe, wall.level_id or None)
        if space is not None and space.id not in found:
            found.append(space.id)
    return (point, found)


def _build_graph(
    plan: FloorPlan,
) -> tuple[
    dict[str, _Node], dict[str, list[tuple[str, float, str]]], dict[str, list[str]]
]:
    """Rooms and doorways as nodes; a straight run across a room as an edge.

    Also returns which rooms each doorway joins. A leg between two doorways is
    the commonest leg there is -- straight across a corridor -- and without that
    mapping it is the one leg that cannot say which room it crossed, which is
    exactly the room whose ambient the conductor is sitting in.
    """
    nodes: dict[str, _Node] = {}
    edges: dict[str, list[tuple[str, float, str]]] = {}

    def add_edge(a: str, b: str, weight: float, kind: str) -> None:
        edges.setdefault(a, []).append((b, weight, kind))
        edges.setdefault(b, []).append((a, weight, kind))

    for space in plan.spaces:
        key = f"space:{space.id}"
        nodes[key] = _Node(key, space.centroid, space.level_id, space.id)

    # Doorways, and the rooms they join.
    door_rooms: dict[str, list[str]] = {}
    for opening in plan.openings:
        if opening.kind == "window":
            continue
        point, rooms = doorway_spaces(plan, opening)
        if point is None or not rooms:
            continue
        key = f"door:{opening.id}"
        wall = plan.wall(opening.wall_id)
        nodes[key] = _Node(key, point, wall.level_id if wall else "", "")
        door_rooms[key] = rooms
        for space_id in rooms:
            space_key = f"space:{space_id}"
            if space_key in nodes:
                add_edge(
                    key, space_key, distance(point, nodes[space_key].point), "horizontal"
                )

    # Two doorways in the same room: a run goes between them directly rather than
    # detouring via the middle of the room, which is what a tray does.
    by_room: dict[str, list[str]] = {}
    for door_key, rooms in door_rooms.items():
        for space_id in rooms:
            by_room.setdefault(space_id, []).append(door_key)
    for space_id, doors in by_room.items():
        for i, a in enumerate(doors):
            for b in doors[i + 1 :]:
                add_edge(a, b, distance(nodes[a].point, nodes[b].point), "horizontal")

    # Risers: rooms on adjacent storeys whose footprints overlap. A stairwell or a
    # services riser is exactly this, and without it a two-storey building has two
    # disconnected graphs and every cross-floor route fails.
    levels = sorted(plan.levels, key=lambda level: level.elevation_m)
    for lower, upper in zip(levels, levels[1:]):
        rise = max(0.1, upper.elevation_m - lower.elevation_m)
        for below in plan.spaces_on(lower.id):
            for above in plan.spaces_on(upper.id):
                if below.contains(above.centroid) or above.contains(below.centroid):
                    add_edge(
                        f"space:{below.id}", f"space:{above.id}", rise, "riser"
                    )

    return nodes, edges, door_rooms


def _shortest_path(
    nodes: dict[str, _Node],
    edges: dict[str, list[tuple[str, float, str]]],
    start: str,
    goal: str,
) -> tuple[list[str], list[str]] | None:
    """Dijkstra. Returns ``(node keys, edge kinds)`` or ``None`` if unreachable."""
    dist = {start: 0.0}
    prev: dict[str, tuple[str, str]] = {}
    queue: list[tuple[float, str]] = [(0.0, start)]
    seen: set[str] = set()

    while queue:
        cost, key = heapq.heappop(queue)
        if key in seen:
            continue
        seen.add(key)
        if key == goal:
            break
        for neighbour, weight, kind in edges.get(key, []):
            if neighbour in seen:
                continue
            candidate = cost + weight
            if candidate < dist.get(neighbour, math.inf):
                dist[neighbour] = candidate
                prev[neighbour] = (key, kind)
                heapq.heappush(queue, (candidate, neighbour))

    if goal not in dist:
        return None

    path: list[str] = [goal]
    kinds: list[str] = []
    while path[-1] != start:
        parent, kind = prev[path[-1]]
        kinds.append(kind)
        path.append(parent)
    return (path[::-1], kinds[::-1])


# ---------------------------------------------------------------------------
# The public call
# ---------------------------------------------------------------------------

def route(
    plan: FloorPlan,
    start: Point,
    end: Point,
    *,
    start_level: str | None = None,
    end_level: str | None = None,
    tray_height_m: float = DEFAULT_TRAY_HEIGHT_M,
    equipment_height_m: float = 0.0,
    slack_frac: float = DEFAULT_SLACK_FRAC,
) -> Route:
    """Route a cable from one point in the building to another.

    ``start`` and ``end`` are plan coordinates in metres. Levels default to the
    plan's first level, so a single-storey building needs neither.

    Always returns a :class:`Route`. When the two points cannot be connected
    through the building's own openings -- which happens honestly, in a plan with
    no doors in it -- the straight-line distance is returned with the reason in
    ``problems``, because a stated estimate is more useful than an exception and
    far more useful than a silent one.
    """
    levels = plan.levels or []
    default_level = levels[0].id if levels else ""
    start_level = start_level or default_level
    end_level = end_level or default_level

    problems: list[str] = []
    legs: list[Leg] = []

    drop = max(0.0, tray_height_m - equipment_height_m)
    if drop > 0:
        legs.append(
            Leg(
                kind="drop",
                length_m=round(drop, 4),
                description=f"rise from the equipment to the tray at {tray_height_m:.1f} m",
            )
        )

    start_space = plan.space_at(start, start_level or None)
    end_space = plan.space_at(end, end_level or None)

    if start_space is None or end_space is None:
        straight = distance(start, end)
        missing = "start" if start_space is None else "end"
        problems.append(
            f"the {missing} point is not inside any room in the plan, so the run "
            f"could not be traced through the building; the straight-line distance "
            f"is used instead"
        )
        legs.append(
            Leg(
                kind="horizontal",
                length_m=round(straight, 4),
                from_point=start,
                to_point=end,
                description="straight line (not routed)",
            )
        )
        return _assemble(legs, [start, end], [], problems, drop, slack_frac)

    if start_space.id == end_space.id and start_level == end_level:
        straight = distance(start, end)
        legs.append(
            Leg(
                kind="horizontal",
                length_m=round(straight, 4),
                from_point=start,
                to_point=end,
                space_id=start_space.id,
                space_name=start_space.name,
                description=f"across {start_space.name or start_space.id}",
            )
        )
        return _assemble(
            legs, [start, end], [start_space.id], problems, drop, slack_frac
        )

    nodes, edges, door_rooms = _build_graph(plan)
    start_key, end_key = "__start", "__end"
    nodes[start_key] = _Node(start_key, start, start_level, start_space.id)
    nodes[end_key] = _Node(end_key, end, end_level, end_space.id)
    _attach(nodes, edges, start_key, start_space, plan)
    _attach(nodes, edges, end_key, end_space, plan)

    found = _shortest_path(nodes, edges, start_key, end_key)
    if found is None:
        straight = distance(start, end)
        problems.append(
            f"no path through the building's openings joins "
            f"{start_space.name or start_space.id} to {end_space.name or end_space.id} "
            f"— the plan may have no doors, or none that were imported; the "
            f"straight-line distance is used instead"
        )
        legs.append(
            Leg(
                kind="horizontal",
                length_m=round(straight, 4),
                from_point=start,
                to_point=end,
                description="straight line (not routed)",
            )
        )
        return _assemble(
            legs, [start, end], [start_space.id, end_space.id], problems, drop, slack_frac
        )

    keys, kinds = found
    path_points: list[Point] = []
    space_ids: list[str] = []
    for i in range(len(keys) - 1):
        a, b = nodes[keys[i]], nodes[keys[i + 1]]
        kind = kinds[i]
        space_id = a.space_id or b.space_id or _shared_room(door_rooms, keys[i], keys[i + 1])
        space = plan.space(space_id) if space_id else None
        if space_id and space_id not in space_ids:
            space_ids.append(space_id)
        length = (
            abs(_elevation(plan, b.level_id) - _elevation(plan, a.level_id))
            if kind == "riser"
            else distance(a.point, b.point)
        )
        legs.append(
            Leg(
                kind=kind,
                length_m=round(length, 4),
                from_point=a.point if kind != "riser" else None,
                to_point=b.point if kind != "riser" else None,
                space_id=space_id,
                space_name=space.name if space else "",
                description=(
                    f"riser between {a.level_id} and {b.level_id}"
                    if kind == "riser"
                    else f"through {space.name or space_id}"
                    if space
                    else "through the building"
                ),
            )
        )
        if kind != "riser":
            path_points.extend([a.point, b.point])

    if drop > 0:
        legs.append(
            Leg(
                kind="drop",
                length_m=round(drop, 4),
                description="drop from the tray to the equipment",
            )
        )

    return _assemble(legs, path_points or [start, end], space_ids, problems, 0.0, slack_frac)


def _attach(
    nodes: dict[str, _Node],
    edges: dict[str, list[tuple[str, float, str]]],
    key: str,
    space: Space,
    plan: FloorPlan,
) -> None:
    """Join a loose endpoint to its room's doorways, and to the room itself."""
    point = nodes[key].point
    space_key = f"space:{space.id}"
    if space_key in nodes:
        weight = distance(point, nodes[space_key].point)
        edges.setdefault(key, []).append((space_key, weight, "horizontal"))
        edges.setdefault(space_key, []).append((key, weight, "horizontal"))
    for other_key, node in nodes.items():
        if not other_key.startswith("door:"):
            continue
        if not space.contains(_nudge(node.point, point)):
            continue
        weight = distance(point, node.point)
        edges.setdefault(key, []).append((other_key, weight, "horizontal"))
        edges.setdefault(other_key, []).append((key, weight, "horizontal"))


def _nudge(door: Point, toward: Point, step: float = DOORWAY_PROBE_M) -> Point:
    """A doorway's point, stepped slightly into the room the endpoint is in.

    A doorway sits *in* a wall, so ``space.contains(door_point)`` is false for
    both rooms it joins. Stepping toward the endpoint asks the question that was
    meant: is this doorway on the boundary of the room I am standing in?
    """
    dx, dy = toward[0] - door[0], toward[1] - door[1]
    norm = math.hypot(dx, dy) or 1.0
    return (door[0] + dx / norm * step, door[1] + dy / norm * step)


def _shared_room(door_rooms: dict[str, list[str]], a: str, b: str) -> str:
    """The room two doorways both open onto -- the room the leg crosses."""
    rooms_a, rooms_b = door_rooms.get(a, []), door_rooms.get(b, [])
    shared = [r for r in rooms_a if r in rooms_b]
    return shared[0] if shared else ""


def _elevation(plan: FloorPlan, level_id: str) -> float:
    level = plan.level(level_id)
    return level.elevation_m if level else 0.0


def _assemble(
    legs: list[Leg],
    path: list[Point],
    space_ids: list[str],
    problems: list[str],
    trailing_drop: float,
    slack_frac: float,
) -> Route:
    if trailing_drop > 0:
        legs.append(
            Leg(
                kind="drop",
                length_m=round(trailing_drop, 4),
                description="drop from the tray to the equipment",
            )
        )
    horizontal = sum(leg.length_m for leg in legs if leg.kind == "horizontal")
    vertical = sum(leg.length_m for leg in legs if leg.kind in ("drop", "riser"))
    subtotal = horizontal + vertical
    slack = subtotal * max(0.0, float(slack_frac))
    return Route(
        length_m=round(subtotal + slack, 4),
        horizontal_m=round(horizontal, 4),
        vertical_m=round(vertical, 4),
        slack_m=round(slack, 4),
        legs=legs,
        path=path,
        space_ids=space_ids,
        problems=problems,
    )


def wall_run(plan: FloorPlan, wall_id: str) -> float:
    """The length of one wall -- the trivial route, for a run along a single wall."""
    wall = plan.wall(wall_id)
    return wall.length_m if wall else 0.0

