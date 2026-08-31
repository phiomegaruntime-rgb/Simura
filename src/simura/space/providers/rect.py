"""A building with no file behind it.

The counterpart of :class:`simura.weather.providers.synthetic.SyntheticProvider`,
and it exists for the same three reasons: the tests need a building that is the
same every run, the dashboard needs something to show before anybody has uploaded
a model, and a reader needs to see the whole pipeline work without first finding
an IFC file.

It generates the most boring real building there is -- a row of rooms off a
corridor -- because that is enough to exercise everything the component claims:
several spaces with different occupancies, walls with thickness, doors positioned
along them, more than one storey, and a plan whose numbers a person can check by
hand. The rooms are rectangles, so ``Space.rectangular()`` is true throughout and
the lighting coupling reports its extents as *measured* -- which makes this the
control case against which an imported, genuinely L-shaped room can be compared.

Nothing here is inferred, so the fidelity record comes out ``complete``. That is
the point: a synthetic building is the one case where the importer knows
everything, and seeing ``nothing was assumed`` here is what gives the warning any
meaning when it shows up on a real model.
"""

from __future__ import annotations

from ..fidelity import FidelityLog
from ..geometry import rectangle
from ..plan import FloorPlan, Georeference, Level, Opening, Space, Wall


class RectangleProvider:
    """A row of rectangular rooms off a corridor, repeated over ``levels``.

    ``occupancies`` is cycled over the rooms, so the default gives offices with a
    store at the end -- enough for the lighting rollup to have something to say.
    """

    format = "rect"

    def __init__(
        self,
        name: str = "Example building",
        rooms: int = 4,
        room_length_m: float = 6.0,
        room_width_m: float = 4.0,
        corridor_width_m: float = 1.8,
        height_m: float = 2.7,
        wall_thickness_m: float = 0.2,
        levels: int = 1,
        level_height_m: float = 3.4,
        occupancies: tuple[str, ...] = ("office", "office", "office", "storage"),
        latitude: float | None = None,
        longitude: float | None = None,
        north_deg: float = 0.0,
    ) -> None:
        if rooms < 1:
            raise ValueError("a building needs at least one room")
        self.name = name
        self.rooms = int(rooms)
        self.room_length_m = float(room_length_m)
        self.room_width_m = float(room_width_m)
        self.corridor_width_m = float(corridor_width_m)
        self.height_m = float(height_m)
        self.wall_thickness_m = float(wall_thickness_m)
        self.levels = max(1, int(levels))
        self.level_height_m = float(level_height_m)
        self.occupancies = tuple(occupancies) or ("office",)
        self.latitude = latitude
        self.longitude = longitude
        self.north_deg = float(north_deg)
        self._plan: FloorPlan | None = None

    def plan(self) -> FloorPlan:
        if self._plan is None:
            self._plan = self._build()
        return self._plan

    def _build(self) -> FloorPlan:
        log = FidelityLog(self.format, self.name)

        def emit(n: int = 1) -> None:
            # Nothing here comes from a file, so everything this provider looks
            # at is also everything it uses -- which is what makes its coverage
            # 100% and its fidelity record `complete`.
            log.seen(n)
            log.used(n)

        spaces: list[Space] = []
        walls: list[Wall] = []
        openings: list[Opening] = []
        plan_levels: list[Level] = []

        span = self.rooms * self.room_length_m
        for li in range(self.levels):
            level_id = f"level-{li}"
            plan_levels.append(
                Level(
                    id=level_id,
                    name=f"Level {li}",
                    elevation_m=li * self.level_height_m,
                    height_m=self.level_height_m,
                )
            )

            # The rooms, in a row along +x, their south wall on y = corridor_width.
            for ri in range(self.rooms):
                occupancy = self.occupancies[ri % len(self.occupancies)]
                x0 = ri * self.room_length_m
                y0 = self.corridor_width_m
                sid = f"{level_id}-room-{ri}"
                spaces.append(
                    Space(
                        id=sid,
                        name=f"{occupancy.replace('_', ' ').title()} {li}.{ri:02d}",
                        level_id=level_id,
                        polygon=rectangle(self.room_length_m, self.room_width_m, (x0, y0)),
                        height_m=self.height_m,
                        occupancy=occupancy,
                        conditioned=True,
                    )
                )
                emit()

                # The partition between this room and the next.
                if ri:
                    walls.append(
                        Wall(
                            id=f"{sid}-partition",
                            level_id=level_id,
                            axis=[(x0, y0), (x0, y0 + self.room_width_m)],
                            thickness_m=self.wall_thickness_m,
                            height_m=self.height_m,
                        )
                    )
                    emit()

                # The corridor wall, with this room's door in the middle of it.
                wall_id = f"{sid}-front"
                walls.append(
                    Wall(
                        id=wall_id,
                        level_id=level_id,
                        axis=[(x0, y0), (x0 + self.room_length_m, y0)],
                        thickness_m=self.wall_thickness_m,
                        height_m=self.height_m,
                    )
                )
                openings.append(
                    Opening(
                        id=f"{sid}-door",
                        wall_id=wall_id,
                        kind="door",
                        along_m=self.room_length_m / 2.0,
                        width_m=0.9,
                        height_m=2.1,
                    )
                )
                emit(2)

                # An exterior wall with a window, at the back of every room.
                back_id = f"{sid}-rear"
                walls.append(
                    Wall(
                        id=back_id,
                        level_id=level_id,
                        axis=[
                            (x0, y0 + self.room_width_m),
                            (x0 + self.room_length_m, y0 + self.room_width_m),
                        ],
                        thickness_m=self.wall_thickness_m,
                        height_m=self.height_m,
                        exterior=True,
                    )
                )
                openings.append(
                    Opening(
                        id=f"{sid}-window",
                        wall_id=back_id,
                        kind="window",
                        along_m=self.room_length_m / 2.0,
                        width_m=min(2.0, self.room_length_m * 0.5),
                        height_m=1.4,
                        sill_m=0.9,
                    )
                )
                emit(2)

            # The corridor itself: one space running the length of the row.
            corridor_id = f"{level_id}-corridor"
            spaces.append(
                Space(
                    id=corridor_id,
                    name=f"Corridor {li}",
                    level_id=level_id,
                    polygon=rectangle(span, self.corridor_width_m, (0.0, 0.0)),
                    height_m=self.height_m,
                    occupancy="corridor",
                    conditioned=True,
                )
            )
            walls.append(
                Wall(
                    id=f"{corridor_id}-outer",
                    level_id=level_id,
                    axis=[(0.0, 0.0), (span, 0.0)],
                    thickness_m=self.wall_thickness_m,
                    height_m=self.height_m,
                    exterior=True,
                )
            )
            # The two ends, so the storey is a closed shell the world can extrude.
            walls.append(
                Wall(
                    id=f"{level_id}-end-w",
                    level_id=level_id,
                    axis=[(0.0, 0.0), (0.0, self.corridor_width_m + self.room_width_m)],
                    thickness_m=self.wall_thickness_m,
                    height_m=self.height_m,
                    exterior=True,
                )
            )
            walls.append(
                Wall(
                    id=f"{level_id}-end-e",
                    level_id=level_id,
                    axis=[(span, 0.0), (span, self.corridor_width_m + self.room_width_m)],
                    thickness_m=self.wall_thickness_m,
                    height_m=self.height_m,
                    exterior=True,
                )
            )
            emit(4)

        return FloorPlan(
            name=self.name,
            georeference=Georeference(
                latitude=self.latitude, longitude=self.longitude, north_deg=self.north_deg
            ),
            levels=plan_levels,
            spaces=spaces,
            walls=walls,
            openings=openings,
            fidelity=log.freeze(),
            source_units="m",
        )
