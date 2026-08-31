"""Plane geometry, in metres, with nothing imported.

Everything a floor plan needs to be *measured* rather than merely drawn: how big
a room is, where its middle is, whether a point is inside it, and what rectangle
best stands in for it. Pure standard library -- no numpy, no shapely -- for the
same reason :mod:`simura.weather` is: this subpackage should lift out of Simura
unchanged, and a geometry dependency is the one thing that would stop it.

Coordinates are **metres in the plan's own frame**, right-handed, ``+x`` east and
``+y`` north once the plan has been rotated onto true north. Polygons are lists
of ``(x, y)`` vertices, implicitly closed -- the last vertex is *not* repeated,
because a repeated vertex is a thing every importer gets wrong differently and
normalising it once here is cheaper than defending against it everywhere.

The one function here that makes a *claim* rather than a measurement is
:func:`oriented_extents`, and it is worth saying why. The lumen method
(:func:`simura.lights.photometry.lumen_method`) is written for a rectangular
room, because the room index it computes is a rectangle's. Real rooms are
L-shaped, chamfered and full of columns. Rather than refuse to light them or
quietly use a bounding box aligned to whatever arbitrary axis the CAD file was
drawn on, this returns the **minimum-area enclosing rectangle** -- the rectangle
a person would draw round the room -- and the caller records that the length and
width were *inferred* from a polygon rather than read as a rectangle. A number
derived this way is fine; a number derived this way and presented as measured is
not.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

Point = tuple[float, float]
Polygon = list[Point]

# Below this, two vertices are the same vertex and an area is zero. A tenth of a
# millimetre is finer than any building model is meaningful to, and coarse enough
# that floating-point noise from a transform chain never reads as real geometry.
EPS_M = 1e-4


def normalize_polygon(points: Iterable[Sequence[float]]) -> Polygon:
    """Drop repeated vertices and any closing duplicate; return a clean ring.

    Importers disagree about whether a ring repeats its first point at the end,
    and some emit the same vertex twice where two walls meet. Normalising on the
    way in means every consumer downstream can assume a simple, unrepeated ring.
    """
    ring: Polygon = []
    for p in points:
        pt = (float(p[0]), float(p[1]))
        if ring and _close(ring[-1], pt):
            continue
        ring.append(pt)
    while len(ring) >= 2 and _close(ring[0], ring[-1]):
        ring.pop()
    return ring


def _close(a: Point, b: Point) -> bool:
    return abs(a[0] - b[0]) <= EPS_M and abs(a[1] - b[1]) <= EPS_M


def polygon_area(poly: Sequence[Point]) -> float:
    """Enclosed area in m^2, by the shoelace formula. Sign-free."""
    if len(poly) < 3:
        return 0.0
    total = 0.0
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def signed_area(poly: Sequence[Point]) -> float:
    """Shoelace area *with* its sign: positive counter-clockwise."""
    if len(poly) < 3:
        return 0.0
    total = 0.0
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def ensure_ccw(poly: Sequence[Point]) -> Polygon:
    """The same ring, wound counter-clockwise.

    Winding carries no meaning in a floor plan, but *consistent* winding means a
    plan hashes the same twice and two importers of the same building produce
    comparable output. So it is normalised rather than preserved.
    """
    ring = list(poly)
    return ring if signed_area(ring) >= 0 else ring[::-1]


def polygon_perimeter(poly: Sequence[Point]) -> float:
    """Total edge length in metres."""
    if len(poly) < 2:
        return 0.0
    return sum(distance(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def polygon_centroid(poly: Sequence[Point]) -> Point:
    """Area centroid -- the point a room balances on.

    Falls back to the mean of the vertices for a degenerate (zero-area) ring,
    which is what a two-point "room" from a broken import collapses to. A
    centroid that raises is a centroid that takes the whole import down with it.
    """
    if not poly:
        return (0.0, 0.0)
    a = signed_area(poly)
    if abs(a) < EPS_M * EPS_M:
        return (
            sum(p[0] for p in poly) / len(poly),
            sum(p[1] for p in poly) / len(poly),
        )
    cx = cy = 0.0
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        cross = x1 * y2 - x2 * y1
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    return (cx / (6.0 * a), cy / (6.0 * a))


def polygon_bounds(poly: Sequence[Point]) -> tuple[float, float, float, float]:
    """``(min_x, min_y, max_x, max_y)`` -- the axis-aligned extent."""
    if not poly:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (min(xs), min(ys), max(xs), max(ys))


def point_in_polygon(pt: Point, poly: Sequence[Point]) -> bool:
    """Ray casting, with points *on* an edge counted as inside.

    Counting the boundary as inside matters for the illuminance grid: a room
    exactly 6 m wide sampled every 0.5 m has grid points landing precisely on the
    wall line, and excluding them would silently trim a column off every room
    whose dimensions are round numbers -- which, in a building model, is most of
    them.
    """
    if len(poly) < 3:
        return False
    x, y = pt
    n = len(poly)
    for i in range(n):
        if _on_segment(pt, poly[i], poly[(i + 1) % n]):
            return True
    inside = False
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            t = (y - y1) / (y2 - y1)
            if x < x1 + t * (x2 - x1):
                inside = not inside
    return inside


def _on_segment(pt: Point, a: Point, b: Point) -> bool:
    cross = (b[0] - a[0]) * (pt[1] - a[1]) - (b[1] - a[1]) * (pt[0] - a[0])
    if abs(cross) > EPS_M:
        return False
    dot = (pt[0] - a[0]) * (b[0] - a[0]) + (pt[1] - a[1]) * (b[1] - a[1])
    if dot < -EPS_M:
        return False
    return dot <= distance(a, b) ** 2 + EPS_M


def distance(a: Sequence[float], b: Sequence[float]) -> float:
    """Euclidean distance between two points, in metres."""
    return math.hypot(b[0] - a[0], b[1] - a[1])


def polyline_length(points: Sequence[Point]) -> float:
    """Length of an open polyline -- a wall axis, a cable route."""
    return sum(distance(points[i], points[i + 1]) for i in range(len(points) - 1))


def grid_points(poly: Sequence[Point], spacing_m: float, inset_m: float = 0.0) -> list[Point]:
    """Sample points on a regular grid, keeping only those inside the polygon.

    This is what lets an illuminance field be solved over a room's real shape
    rather than its bounding box. ``inset_m`` pulls the sampled region in from
    the walls, which is what lighting standards mean by the "task area": the
    half-metre against a wall is not somewhere anybody works, and including it
    drags every uniformity figure down for no reason a designer would accept.
    """
    if spacing_m <= 0:
        raise ValueError("spacing_m must be positive")
    min_x, min_y, max_x, max_y = polygon_bounds(poly)
    min_x, min_y = min_x + inset_m, min_y + inset_m
    max_x, max_y = max_x - inset_m, max_y - inset_m
    if max_x < min_x or max_y < min_y:
        return []
    out: list[Point] = []
    n_x = max(1, int(round((max_x - min_x) / spacing_m)))
    n_y = max(1, int(round((max_y - min_y) / spacing_m)))
    for iy in range(n_y + 1):
        for ix in range(n_x + 1):
            x = min_x + (max_x - min_x) * (ix / n_x)
            y = min_y + (max_y - min_y) * (iy / n_y)
            if point_in_polygon((x, y), poly):
                out.append((x, y))
    return out


def convex_hull(points: Sequence[Point]) -> Polygon:
    """Andrew monotone-chain hull, counter-clockwise."""
    pts = sorted({(round(p[0], 6), round(p[1], 6)) for p in points})
    if len(pts) < 3:
        return list(pts)

    def half(seq: Sequence[Point]) -> list[Point]:
        out: list[Point] = []
        for p in seq:
            while len(out) >= 2 and _cross(out[-2], out[-1], p) <= 0:
                out.pop()
            out.append(p)
        return out

    lower = half(pts)
    upper = half(pts[::-1])
    return lower[:-1] + upper[:-1]


def _cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def oriented_extents(poly: Sequence[Point]) -> tuple[float, float, float]:
    """The minimum-area enclosing rectangle: ``(length_m, width_m, angle_deg)``.

    ``length_m >= width_m``, and ``angle_deg`` is the rectangle's long axis
    measured counter-clockwise from ``+x``. By the rotating-calipers theorem the
    minimum-area rectangle shares an edge with the convex hull, so trying every
    hull edge as a candidate axis is exact rather than a search.

    See the module docstring for why this exists and what a caller owes the
    reader when it uses the result.
    """
    hull = convex_hull(list(poly))
    if len(hull) < 3:
        min_x, min_y, max_x, max_y = polygon_bounds(poly)
        w, h = max_x - min_x, max_y - min_y
        return (max(w, h), min(w, h), 0.0 if w >= h else 90.0)

    best = (float("inf"), 0.0, 0.0, 0.0)  # area, length, width, angle
    for i in range(len(hull)):
        ax, ay = hull[i]
        bx, by = hull[(i + 1) % len(hull)]
        theta = math.atan2(by - ay, bx - ax)
        cos_t, sin_t = math.cos(-theta), math.sin(-theta)
        xs = [p[0] * cos_t - p[1] * sin_t for p in hull]
        ys = [p[0] * sin_t + p[1] * cos_t for p in hull]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        area = w * h
        if area < best[0] - EPS_M:
            length, width = (w, h) if w >= h else (h, w)
            angle = math.degrees(theta) if w >= h else math.degrees(theta) + 90.0
            best = (area, length, width, angle % 180.0)
    return (best[1], best[2], best[3])


def rectangle(length_m: float, width_m: float, origin: Point = (0.0, 0.0)) -> Polygon:
    """An axis-aligned rectangle as a ring -- the simplest possible room."""
    x, y = origin
    return [(x, y), (x + length_m, y), (x + length_m, y + width_m), (x, y + width_m)]


def transform(
    poly: Sequence[Point], *, rotate_deg: float = 0.0, offset: Point = (0.0, 0.0)
) -> Polygon:
    """Rotate about the origin, then translate -- the whole transform a plan needs.

    A building model carries a local origin and a true-north angle; applying both
    once, on import, is what lets everything downstream work in one frame instead
    of each consumer re-deriving the same rotation.
    """
    rad = math.radians(rotate_deg)
    cos_t, sin_t = math.cos(rad), math.sin(rad)
    dx, dy = offset
    return [(p[0] * cos_t - p[1] * sin_t + dx, p[0] * sin_t + p[1] * cos_t + dy) for p in poly]


def bounds_union(
    boxes: Iterable[tuple[float, float, float, float]]
) -> tuple[float, float, float, float]:
    """Smallest box containing them all; zeros for an empty iterable."""
    items = list(boxes)
    if not items:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(b[0] for b in items),
        min(b[1] for b in items),
        max(b[2] for b in items),
        max(b[3] for b in items),
    )
