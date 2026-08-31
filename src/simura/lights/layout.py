"""Multi-luminaire layouts: where the light actually falls.

The lighting counterpart of :mod:`simura.wires.network`. The lumen method in
:mod:`simura.lights.photometry` answers *how much* light a room gets on average;
this answers *where* it goes -- which is the question that decides whether a
layout is any good.

Average illuminance hides the two failures that matter. A room lit to a perfect
500 lux average can have 900 lux under each fitting and 150 lux between them, and
a corridor lit by too few, too-bright luminaires reads as a row of pools rather
than a lit space. The measure for this is **uniformity**::

    U0 = E_min / E_average

with 0.6 the usual requirement for a working interior and 0.4 for a circulation
space. Getting there is a question of spacing relative to mounting height, and
the model shows it directly: push the fittings apart and watch U0 collapse while
the average barely moves.

The solve itself is a direct sum -- illuminance is linear, so every luminaire's
contribution at every grid point simply adds. No iteration, unlike the wire
network's resistance/temperature fixed point.

Direct and indirect
-------------------

Point-by-point geometry only accounts for light that travels straight from a
lamp to the surface. In a real room a large share arrives after bouncing off the
ceiling and walls, and leaving it out makes every layout look far darker than it
is -- a 500 lux office would come out at 200.

So the solve uses the standard **split-flux** treatment: the geometry gives the
direct component and its *shape*, and the interreflected light is added as a
uniform term sized so the room total matches the lumen method's utilisation
factor. Bounced light really is close to uniform, which is why a room with light
walls is not just brighter but more even. Set ``include_interreflection=False``
for the direct component alone -- the honest answer outdoors, where there is
nothing to bounce off.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from .environment import LightEnvironmentCoupling
from .faults import Fault, accumulate
from .lamp import Light, LightSpec
from .photometry import (
    illuminance_lux,
    luminous_intensity_cd,
    room_index,
    utilisation_factor,
)


@dataclass
class Luminaire:
    """One fitting at a position, with its own lamp, aim and faults."""

    id: str
    x_m: float
    y_m: float
    height_m: float
    spec: LightSpec
    drive: float = 1.0
    faults: list[Fault] = field(default_factory=list)


@dataclass
class LuminaireResult:
    """What one fitting is doing in the solved layout."""

    id: str
    x_m: float
    y_m: float
    height_m: float
    lit: bool
    input_power_w: float
    luminous_flux_lm: float
    efficacy_lm_per_w: float
    color_temp_k: float
    source_temp_c: float
    lumen_maintenance: float
    peak_lux_below: float          # illuminance directly underneath

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LayoutResult:
    """The solved illuminance field over the area."""

    average_lux: float
    min_lux: float
    max_lux: float
    uniformity: float              # U0 = min / average
    diversity: float               # min / max, the stricter measure
    total_power_w: float
    power_density_w_per_m2: float
    area_m2: float
    # Illuminance at each grid point, row-major. `None` where the grid point
    # falls outside the room's outline -- see `Layout(outline=...)`. A masked
    # point is not darkness and must not be rendered as though it were.
    grid: list[list[float | None]]
    grid_x_m: list[float]
    grid_y_m: list[float]
    luminaires: list[LuminaireResult]
    direct_average_lux: float = 0.0     # before interreflection
    indirect_lux: float = 0.0           # the uniform bounced component
    daylight_lux: float = 0.0
    target_lux: float = 0.0
    # The room outline the field was solved over, when it was not a rectangle.
    outline: list[list[float]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["luminaires"] = [lum.to_dict() for lum in self.luminaires]
        return d


class Layout:
    """A room (or an area) with luminaires in it, solved on a grid.

    Build it by adding luminaires, then :meth:`solve` for the illuminance field.
    Mirrors :class:`simura.wires.network.WireNetwork`: add elements, solve, read
    the per-element results and the whole-system verdict together.
    """

    def __init__(
        self,
        length_m: float,
        width_m: float,
        workplane_height_m: float = 0.75,
        grid_n: int = 9,
        outline: list[tuple[float, float]] | None = None,
    ) -> None:
        """A rectangular room, or -- with ``outline`` -- the room a building has.

        ``outline`` is a closed polygon of ``(x, y)`` metres **in the same frame
        as the luminaire positions**. Give one and the grid spans its bounding
        box and is masked to its interior, and the area is the polygon's rather
        than ``length x width``.

        That distinction is the whole reason the argument exists. An L-shaped
        room lit as its bounding rectangle reports an average that includes
        points in the notch -- floor that does not exist, receiving light from
        fittings that are not above it -- and a uniformity the re-entrant corner
        never sees. ``length_m`` and ``width_m`` are still required because the
        room index the lumen method needs is a rectangle's; with an outline they
        should be its best-fit rectangle, and the caller should say so (see
        :meth:`simura.space.plan.Space.rectangular`).
        """
        if length_m <= 0 or width_m <= 0:
            raise ValueError("a layout needs a positive length and width")
        self.length_m = float(length_m)
        self.width_m = float(width_m)
        self.workplane_height_m = float(workplane_height_m)
        self.grid_n = max(3, min(int(grid_n), 41))
        self.outline: list[tuple[float, float]] = (
            [(float(x), float(y)) for x, y in outline] if outline else []
        )
        self.luminaires: list[Luminaire] = []

    def area_m2(self) -> float:
        """Floor area: the outline's, when there is one, else the rectangle's."""
        if len(self.outline) >= 3:
            return _polygon_area(self.outline)
        return self.length_m * self.width_m

    def _mean_mount_height(self) -> float:
        """Average luminaire height above the working plane, for the room index."""
        if not self.luminaires:
            return 1.0
        heights = [max(lum.height_m - self.workplane_height_m, 0.05) for lum in self.luminaires]
        return sum(heights) / len(heights)

    def add(
        self,
        id: str,
        x_m: float,
        y_m: float,
        height_m: float,
        spec: LightSpec,
        drive: float = 1.0,
        faults: list[Fault] | None = None,
    ) -> "Layout":
        """Place one luminaire. Returns self, so placements chain."""
        self.luminaires.append(
            Luminaire(id=id, x_m=x_m, y_m=y_m, height_m=height_m, spec=spec,
                      drive=drive, faults=faults or [])
        )
        return self

    def grid_regular(
        self,
        rows: int,
        cols: int,
        height_m: float,
        spec: LightSpec,
        drive: float = 1.0,
        prefix: str = "L",
    ) -> "Layout":
        """Place ``rows x cols`` luminaires on the standard even grid.

        Each fitting sits at the centre of its own equal share of the ceiling --
        half a spacing in from the walls -- which is the layout every regular
        installation starts from.
        """
        for r in range(rows):
            for c in range(cols):
                x = self.length_m * (c + 0.5) / cols
                y = self.width_m * (r + 0.5) / rows
                self.add(f"{prefix}{r * cols + c + 1}", x, y, height_m, spec, drive)
        return self

    # -- the solve ---------------------------------------------------------
    def solve(
        self,
        elapsed_s: float = 0.0,
        target_lux: float = 0.0,
        min_uniformity: float = 0.0,
        weather=None,
        coupling: LightEnvironmentCoupling | None = None,
        include_interreflection: bool = True,
        ceiling_reflectance: float = 0.7,
        wall_reflectance: float = 0.5,
        floor_reflectance: float = 0.2,
    ) -> LayoutResult:
        """Sum every luminaire's contribution over the grid.

        ``elapsed_s`` is how long any injected faults have been active, which
        matters for the ones that develop over time (lumen depreciation, fouling).
        A ``weather`` sample makes every lamp answer that day's ambient, and its
        daylight is added to the whole field -- so a daylit room can pass at noon
        and fail at dusk on the same layout.
        """
        ambient_c = None
        daylight = 0.0
        if weather is not None:
            env = (coupling or LightEnvironmentCoupling()).apply(weather)
            ambient_c = env.ambient_c
            daylight = env.daylight_lux

        # Solve each lamp once: the field is linear in flux, so a fitting's
        # contribution is its own operating point times pure geometry.
        results: list[LuminaireResult] = []
        # (fitting, intensity cd, mounting height above the workplane, beam angle)
        emitters: list[tuple[Luminaire, float, float, float]] = []
        total_power = 0.0

        for lum in self.luminaires:
            light = Light(lum.spec)
            light.time_lit_s = 1e9       # a solved layout is a warmed-up one
            amb = ambient_c
            if amb is not None:
                env = (coupling or LightEnvironmentCoupling()).apply(weather)
                amb = env.ambient_c + env.solar_heat_w * light.r_th
            effect = accumulate(lum.faults, light, elapsed_s)
            point = light.operating_point(lum.drive, amb, effect)

            mount = max(lum.height_m - self.workplane_height_m, 0.05)
            intensity = luminous_intensity_cd(point.luminous_flux_lm, light.beam_angle_deg)
            emitters.append((lum, intensity, mount, light.beam_angle_deg))
            total_power += point.input_power_w

            results.append(
                LuminaireResult(
                    id=lum.id,
                    x_m=round(lum.x_m, 3),
                    y_m=round(lum.y_m, 3),
                    height_m=round(lum.height_m, 3),
                    lit=point.lit,
                    input_power_w=round(point.input_power_w, 3),
                    luminous_flux_lm=round(point.luminous_flux_lm, 1),
                    efficacy_lm_per_w=round(point.efficacy_lm_per_w, 2),
                    color_temp_k=round(point.color_temp_k, 0),
                    source_temp_c=round(point.source_temp_c, 1),
                    lumen_maintenance=round(point.lumen_maintenance, 4),
                    peak_lux_below=round(
                        illuminance_lux(intensity, mount) if point.lit else 0.0, 1
                    ),
                )
            )

        # The grid: interior points, half a cell in from each wall, so the edges
        # are not double-counted the way a corner-anchored grid would. With an
        # outline the grid spans its bounding box instead, and every point
        # outside the room is masked out rather than solved -- a point in the
        # notch of an L-shaped room is not dark floor, it is not floor.
        if len(self.outline) >= 3:
            min_x, min_y, max_x, max_y = _bounds(self.outline)
        else:
            min_x, min_y, max_x, max_y = 0.0, 0.0, self.length_m, self.width_m
        span_x, span_y = max_x - min_x, max_y - min_y
        xs = [min_x + span_x * (i + 0.5) / self.grid_n for i in range(self.grid_n)]
        ys = [min_y + span_y * (j + 0.5) / self.grid_n for j in range(self.grid_n)]

        masked = len(self.outline) >= 3
        grid: list[list[float | None]] = []
        for y in ys:
            row: list[float | None] = []
            for x in xs:
                if masked and not _point_inside((x, y), self.outline):
                    row.append(None)
                    continue
                total = daylight
                for lum, intensity, mount, beam in emitters:
                    if intensity <= 0:
                        continue
                    offset = math.hypot(x - lum.x_m, y - lum.y_m)
                    angle = math.degrees(math.atan2(offset, mount))
                    if beam < 360.0 and angle > beam / 2.0:
                        continue
                    total += illuminance_lux(intensity, math.hypot(mount, offset), angle)
                row.append(round(total, 2))
            grid.append(row)

        area = self.area_m2()
        flat = [v for row in grid for v in row if v is not None]
        direct_average = sum(flat) / len(flat) if flat else 0.0

        # Split flux: the bounced light is added uniformly, sized so the room
        # total lands on the lumen method's utilisation factor. Only what the
        # geometry has not already delivered is added, so this can never subtract.
        indirect = 0.0
        if include_interreflection and area > 0:
            total_flux = sum(r.luminous_flux_lm for r in results)
            uf = utilisation_factor(
                room_index(self.length_m, self.width_m, self._mean_mount_height()),
                ceiling_reflectance, wall_reflectance, floor_reflectance,
            )
            target_average = total_flux * uf / area
            indirect = max(0.0, target_average - (direct_average - daylight))
            grid = [
                [None if v is None else round(v + indirect, 2) for v in row]
                for row in grid
            ]
            flat = [v for row in grid for v in row if v is not None]

        average = sum(flat) / len(flat) if flat else 0.0
        lo = min(flat) if flat else 0.0
        hi = max(flat) if flat else 0.0

        problems: list[str] = []
        uniformity = lo / average if average > 0 else 0.0
        if target_lux > 0 and average < target_lux:
            problems.append(
                f"under-lit: {average:.0f} lux average against a {target_lux:.0f} lux target"
            )
        if target_lux > 0 and lo < 0.5 * target_lux:
            problems.append(
                f"dark spots: the worst point sees {lo:.0f} lux, under half the "
                f"{target_lux:.0f} lux target"
            )
        if min_uniformity > 0 and uniformity < min_uniformity:
            problems.append(
                f"uneven: uniformity U0 = {uniformity:.2f}, below the "
                f"{min_uniformity:.2f} required — the fittings are too far apart "
                f"for their mounting height"
            )
        dark = [r.id for r in results if not r.lit]
        if dark:
            problems.append(f"not lit: {', '.join(dark)}")

        return LayoutResult(
            average_lux=round(average, 2),
            min_lux=round(lo, 2),
            max_lux=round(hi, 2),
            uniformity=round(uniformity, 4),
            diversity=round(lo / hi, 4) if hi > 0 else 0.0,
            total_power_w=round(total_power, 2),
            power_density_w_per_m2=round(total_power / area, 3) if area > 0 else 0.0,
            area_m2=round(area, 2),
            grid=grid,
            grid_x_m=[round(x, 3) for x in xs],
            grid_y_m=[round(y, 3) for y in ys],
            luminaires=results,
            direct_average_lux=round(direct_average, 2),
            indirect_lux=round(indirect, 2),
            daylight_lux=round(daylight, 2),
            target_lux=round(target_lux, 1),
            outline=[[round(x, 4), round(y, 4)] for x, y in self.outline],
            problems=problems,
        )


# Three small geometry helpers, deliberately local rather than imported from
# `simura.space`. The dependency arrow runs the other way -- a floor plan knows
# how to describe a room to this module, and this module knows nothing about
# floor plans -- exactly as `simura.lights.environment` takes a weather sample
# without importing `simura.weather`. Duplicating twenty lines of ray casting is
# the cheaper of the two costs.

def _polygon_area(poly: list[tuple[float, float]]) -> float:
    if len(poly) < 3:
        return 0.0
    total = 0.0
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _bounds(poly: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (min(xs), min(ys), max(xs), max(ys))


def _point_inside(pt: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    """Ray casting. A point on the boundary may fall either way; the grid never
    places one exactly there, because its samples sit half a cell inside."""
    x, y = pt
    n = len(poly)
    inside = False
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            t = (y - y1) / (y2 - y1)
            if x < x1 + t * (x2 - x1):
                inside = not inside
    return inside


def build_layout(spec: dict[str, Any]) -> Layout:
    """Build a :class:`Layout` from a plain dict.

    ``{"length_m", "width_m", "workplane_height_m"?, "grid_n"?,
    "luminaires": [{"id", "x_m", "y_m", "height_m", "lamp": {...LightSpec},
    "drive"?, "faults"?: [{...}]}]}``.

    A regular grid can be asked for instead, with
    ``{"grid": {"rows", "cols", "height_m", "lamp": {...}}}``.
    """
    from .config import build_fault, build_light

    layout = Layout(
        length_m=float(spec["length_m"]),
        width_m=float(spec["width_m"]),
        workplane_height_m=float(spec.get("workplane_height_m", 0.75)),
        grid_n=int(spec.get("grid_n", 9)),
    )

    regular = spec.get("grid")
    if regular:
        layout.grid_regular(
            rows=int(regular.get("rows", 2)),
            cols=int(regular.get("cols", 2)),
            height_m=float(regular.get("height_m", 3.0)),
            spec=build_light(regular.get("lamp", {})),
            drive=float(regular.get("drive", 1.0)),
        )

    for i, lum in enumerate(spec.get("luminaires", [])):
        layout.add(
            id=str(lum.get("id", f"L{i + 1}")),
            x_m=float(lum["x_m"]),
            y_m=float(lum["y_m"]),
            height_m=float(lum.get("height_m", 3.0)),
            spec=build_light(lum.get("lamp", {})),
            drive=float(lum.get("drive", 1.0)),
            faults=[build_fault(f) for f in lum.get("faults", [])],
        )
    return layout
