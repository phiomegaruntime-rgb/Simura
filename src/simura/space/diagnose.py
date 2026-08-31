"""Why does this model look wrong?

The fidelity record answers "what could the importer not read". This answers a
different and equally common question: **the import succeeded, and the result is
still not the building.**

Those are separate failures and they need separate reporting. A model can parse
perfectly and still produce a plan nobody can use, because of the handful of
things that go wrong in real files and are invisible in a summary:

* **One stray coordinate.** A single room or wall placed at the survey origin
  while everything else sits near zero. The plan's bounds are then kilometres
  across, everything real is a speck in one corner, and any view of it looks like
  one enormous flat shape. This is the commonest cause by a distance, and a room
  count of 20 tells you nothing about it.
* **A unit that was read but is still wrong.** A model authored in millimetres
  and *declared* in metres parses cleanly and comes out 1000x too big.
* **Degenerate rooms.** Polygons with two vertices, or zero area, from a
  representation the importer half-understood.
* **A sealed storey.** Walls but no doorways, so there is no way into the
  building — which matters the moment somebody tries to walk through it.

Everything here is a *measurement of the plan*, not a judgement about the file.
It reports what is there and lets a person decide, in the same spirit as the
fidelity record: the alternative is an importer that silently drops whatever it
finds surprising, which is how a building loses three rooms and nobody notices.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from .geometry import distance
from .plan import FloorPlan

# A room or wall this many times further from the plan's centre than the typical
# one is reported as an outlier. Generous: a real building has wings, and a
# campus has outbuildings. What this is looking for is the item that is three
# orders of magnitude out, not the one at the end of a corridor.
OUTLIER_FACTOR = 8.0

# Below this, a "room" is not a room. Half a square metre is smaller than any
# occupiable space and larger than the numerical noise a transform chain leaves.
MIN_REAL_ROOM_M2 = 0.5

# Above this, a single room is almost certainly a site boundary, a gross-floor-
# area annotation, or a polygon with a stray vertex in it.
SUSPICIOUS_ROOM_M2 = 5_000.0

# Above this, a single wall is a property line rather than a wall.
SUSPICIOUS_WALL_M = 200.0


@dataclass
class Finding:
    """One thing about the plan a person should look at."""

    severity: str  # "error" | "warning" | "note"
    what: str
    detail: str
    subjects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "what": self.what,
            "detail": self.detail,
            "subjects": self.subjects[:20],
        }


def diagnose(plan: FloorPlan) -> list[Finding]:
    """Everything measurably odd about a plan, worst first."""
    findings: list[Finding] = []
    findings += _extent_findings(plan)
    findings += _room_findings(plan)
    findings += _wall_findings(plan)
    findings += _outlier_findings(plan)
    findings += _access_findings(plan)
    order = {"error": 0, "warning": 1, "note": 2}
    return sorted(findings, key=lambda f: order.get(f.severity, 3))


# ---------------------------------------------------------------------------

def _extent_findings(plan: FloorPlan) -> list[Finding]:
    width, depth = plan.size_m()
    span = max(width, depth)
    out: list[Finding] = []

    if span > 2000:
        out.append(
            Finding(
                "error",
                f"the plan spans {span:,.0f} m",
                "A building is tens of metres across. This is either a unit that "
                "was read but is wrong, or -- far more likely -- one item placed "
                "at the survey origin while everything else sits near zero. Check "
                "the outliers below before doubting the units.",
            )
        )
    elif span < 3:
        out.append(
            Finding(
                "error",
                f"the plan spans {span * 1000:,.0f} mm",
                "The whole model is smaller than a room. The source unit is "
                f"recorded as '{plan.source_units}'; if that is wrong, re-import "
                "with an explicit scale.",
            )
        )

    # The gap between the footprint and what the rooms actually occupy. A large
    # one is the signature of a stray coordinate: the rooms are all real and all
    # crowded into a corner of an enormous box.
    room_area = plan.floor_area_m2
    box = width * depth
    if box > 0 and room_area > 0 and room_area / box < 0.02 and box > 400:
        out.append(
            Finding(
                "error",
                f"the rooms fill {room_area / box * 100:.2f}% of the plan's footprint",
                f"{room_area:,.0f} m² of rooms inside a {width:,.0f} x {depth:,.0f} m "
                "box. Real buildings fill a good fraction of their own bounds; this "
                "shape is what one mislocated item does to them.",
            )
        )
    return out


def _room_findings(plan: FloorPlan) -> list[Finding]:
    out: list[Finding] = []
    if not plan.spaces:
        out.append(
            Finding(
                "warning",
                "no rooms",
                "The plan has walls but no spaces, so nothing can be lit, given an "
                "occupancy, or stood in. For IFC this usually means the model has "
                "no IfcSpace entities -- Revit only exports them when 'Export "
                "rooms/spaces' is ticked.",
            )
        )
        return out

    tiny = [s for s in plan.spaces if s.area_m2 < MIN_REAL_ROOM_M2]
    if tiny:
        out.append(
            Finding(
                "warning",
                f"{len(tiny)} room(s) with essentially no area",
                "A polygon the importer could not resolve into a real outline. "
                "These contribute nothing and will not appear when the plan is drawn.",
                [s.id for s in tiny],
            )
        )

    huge = [s for s in plan.spaces if s.area_m2 > SUSPICIOUS_ROOM_M2]
    if huge:
        out.append(
            Finding(
                "error",
                f"{len(huge)} room(s) larger than {SUSPICIOUS_ROOM_M2:,.0f} m²",
                "Almost certainly a site boundary, a gross-floor-area annotation, "
                "or a polygon with one stray vertex in it. A single one of these "
                "drags the plan's bounds out and makes every other room a speck.",
                [f"{s.id} ({s.area_m2:,.0f} m²)" for s in huge],
            )
        )

    degenerate = [s for s in plan.spaces if len(s.polygon) < 3]
    if degenerate:
        out.append(
            Finding(
                "warning",
                f"{len(degenerate)} room(s) with fewer than three vertices",
                "Not a closed outline. These were read but cannot be drawn.",
                [s.id for s in degenerate],
            )
        )
    return out


def _wall_findings(plan: FloorPlan) -> list[Finding]:
    out: list[Finding] = []
    long_walls = [w for w in plan.walls if w.length_m > SUSPICIOUS_WALL_M]
    if long_walls:
        out.append(
            Finding(
                "error",
                f"{len(long_walls)} wall(s) longer than {SUSPICIOUS_WALL_M:.0f} m",
                "A property line, a grid line, or a wall whose axis was recovered "
                "from the wrong representation. One of these is enough to make the "
                "3D view look like a single enormous plane.",
                [f"{w.id} ({w.length_m:,.0f} m)" for w in long_walls],
            )
        )

    tall = [w for w in plan.walls if w.height_m > 20]
    if tall:
        out.append(
            Finding(
                "warning",
                f"{len(tall)} wall(s) over 20 m tall",
                "Plausible for an atrium and not for anything else. Check the "
                "extrusion depth was converted from the model's own units.",
                [f"{w.id} ({w.height_m:,.0f} m)" for w in tall],
            )
        )
    return out


def _outlier_findings(plan: FloorPlan) -> list[Finding]:
    """The one item standing a long way from all the others."""
    points: list[tuple[str, tuple[float, float]]] = [
        (f"room {s.id}", s.centroid) for s in plan.spaces if s.polygon
    ]
    points += [
        (f"wall {w.id}", _midpoint(w.axis)) for w in plan.walls if len(w.axis) >= 2
    ]
    if len(points) < 4:
        return []

    xs = [p[1][0] for p in points]
    ys = [p[1][1] for p in points]
    centre = (statistics.median(xs), statistics.median(ys))
    spreads = [distance(centre, p[1]) for p in points]
    typical = statistics.median(spreads)
    if typical <= 0:
        typical = max(1.0, statistics.mean(spreads) or 1.0)

    outliers = [
        (name, d) for (name, _), d in zip(points, spreads) if d > typical * OUTLIER_FACTOR
    ]
    if not outliers:
        return []

    outliers.sort(key=lambda o: -o[1])
    return [
        Finding(
            "error",
            f"{len(outliers)} item(s) sit far from everything else",
            f"The typical item is {typical:,.1f} m from the middle of the model; "
            f"these are up to {outliers[0][1]:,.0f} m away. This is the single "
            "commonest reason an imported model renders as one huge flat shape: "
            "the plan is centred on the midpoint of its bounds, so one distant "
            "item pushes the real building off into a corner.",
            [f"{name} at {d:,.0f} m" for name, d in outliers],
        )
    ]


def _access_findings(plan: FloorPlan) -> list[Finding]:
    """Can anybody get in? Only matters once somebody tries to walk through it."""
    out: list[Finding] = []
    doors = [o for o in plan.openings if o.kind == "door"]
    if plan.walls and not doors:
        out.append(
            Finding(
                "warning",
                "no doorways anywhere in the model",
                "Walls are solid in the 3D world, so a building with no doorways "
                "cannot be walked into -- you will be put inside it, but you will "
                "not be able to move between rooms. For IFC, doorways are read "
                "through IfcRelVoidsElement and IfcRelFillsElement; a model with "
                "IfcDoor entities but no void/fill relationships gives exactly "
                "this.",
            )
        )
        return out

    orphaned = [o for o in plan.openings if plan.wall(o.wall_id) is None]
    if orphaned:
        out.append(
            Finding(
                "warning",
                f"{len(orphaned)} opening(s) whose wall was not imported",
                "The opening was read but the wall hosting it was not, so it "
                "cannot be positioned and will not appear as a gap.",
                [o.id for o in orphaned],
            )
        )

    for level in plan.levels:
        walls = plan.walls_on(level.id)
        if not walls:
            continue
        level_doors = [
            o
            for o in doors
            if (w := plan.wall(o.wall_id)) is not None and w.level_id == level.id
        ]
        if not level_doors:
            out.append(
                Finding(
                    "note",
                    f"storey '{level.name or level.id}' has {len(walls)} walls and no doorways",
                    "Nothing can move between its rooms in the 3D world.",
                )
            )
    return out


def _midpoint(axis: list[tuple[float, float]]) -> tuple[float, float]:
    xs = [p[0] for p in axis]
    ys = [p[1] for p in axis]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def report(plan: FloorPlan) -> dict[str, Any]:
    """The whole diagnosis, as data — for the API and the tests."""
    width, depth = plan.size_m()
    findings = diagnose(plan)
    per_level = []
    for level in plan.levels:
        rooms = plan.spaces_on(level.id)
        walls = plan.walls_on(level.id)
        per_level.append(
            {
                "id": level.id,
                "name": level.name,
                "elevation_m": level.elevation_m,
                "rooms": len(rooms),
                "walls": len(walls),
                "floor_area_m2": round(sum(r.area_m2 for r in rooms), 2),
            }
        )
    areas = sorted((s.area_m2 for s in plan.spaces), reverse=True)
    return {
        "plan_id": plan.id,
        "size_m": [round(width, 2), round(depth, 2)],
        "bounds": [round(v, 2) for v in plan.bounds()],
        "floor_area_m2": round(plan.floor_area_m2, 2),
        "levels": per_level,
        "largest_rooms_m2": [round(a, 1) for a in areas[:5]],
        "smallest_rooms_m2": [round(a, 1) for a in areas[-5:]],
        "doors": sum(1 for o in plan.openings if o.kind == "door"),
        "windows": sum(1 for o in plan.openings if o.kind == "window"),
        "findings": [f.to_dict() for f in findings],
        "ok": not any(f.severity == "error" for f in findings),
    }

