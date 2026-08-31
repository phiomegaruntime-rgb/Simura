"""Reusable, domain-agnostic building layouts -- BIM in, floor plan out.

This subpackage knows nothing about batteries, wires or lamps -- it only produces
:class:`FloorPlan` values through a small :class:`PlanProvider` interface. That
independence is deliberate and it mirrors :mod:`simura.weather` exactly: the plan
package can be lifted, unchanged, into any project where the *building* drives a
system's behaviour. Within Simura, the domain-specific translations live in
:mod:`simura.space.couple` and :mod:`simura.space.routing`, and they too import
nothing from the physics packages.

    from simura.space import GbxmlProvider, lighting_targets

    plan = GbxmlProvider("office.xml").plan()
    print(plan.fidelity.summary())          # what the import could not read
    for target in lighting_targets(plan):
        print(target.name, target.task, target.kwargs())

Providers:

* :class:`RectangleProvider` -- a generated row of rooms, offline, for tests.
* :class:`InlinePlanProvider` -- the plan carried in the spec that names it.
* :class:`JsonPlanProvider`  -- a plan imported once and saved. The fast path.
* :class:`GbxmlProvider`     -- a gbXML energy model.
* :class:`DxfProvider`       -- an ASCII DXF drawing.
* :class:`IfcProvider`       -- an IFC STEP model, read in pure Python.
* :class:`IfcFullProvider`   -- the same, through ``ifcopenshell`` if installed.

The commitment this package is built on lives in :mod:`simura.space.fidelity`:
**an import declares what it could not read.** Every value the importer supplied
rather than read is recorded with its basis, so no number downstream silently
rests on a guess.
"""

from .config import FILE_TYPES, PLAN_PARAMS, PLAN_TYPES, build_provider, detect_format
from .couple import (
    LightingTarget,
    SpaceContext,
    ambient_for,
    lighting_targets,
    orientation_deg,
    space_at,
    summary,
    task_grid,
    weather_spec,
)
from .fidelity import Fidelity, FidelityLog, Inference, Skipped
from .geometry import (
    grid_points,
    oriented_extents,
    point_in_polygon,
    polygon_area,
    polygon_centroid,
)
from .occupancy import OCCUPANCY, classify
from .plan import FloorPlan, Georeference, Level, Opening, Space, Wall
from .provider import PlanError, PlanProvider
from .providers import (
    DxfProvider,
    InlinePlanProvider,
    GbxmlProvider,
    IfcFullProvider,
    IfcProvider,
    JsonPlanProvider,
    RectangleProvider,
    one_room,
)
from .routing import Leg, Route, route

__all__ = [
    # the document
    "FloorPlan",
    "Space",
    "Wall",
    "Opening",
    "Level",
    "Georeference",
    # fidelity -- the commitment
    "Fidelity",
    "FidelityLog",
    "Inference",
    "Skipped",
    # providers
    "PlanProvider",
    "PlanError",
    "RectangleProvider",
    "JsonPlanProvider",
    "GbxmlProvider",
    "DxfProvider",
    "IfcProvider",
    "IfcFullProvider",
    "InlinePlanProvider",
    "one_room",
    "build_provider",
    "detect_format",
    "PLAN_TYPES",
    "PLAN_PARAMS",
    "FILE_TYPES",
    # couplings
    "lighting_targets",
    "LightingTarget",
    "ambient_for",
    "SpaceContext",
    "weather_spec",
    "orientation_deg",
    "space_at",
    "task_grid",
    "summary",
    "route",
    "Route",
    "Leg",
    # geometry, occasionally useful outside
    "polygon_area",
    "polygon_centroid",
    "point_in_polygon",
    "oriented_extents",
    "grid_points",
    "classify",
    "OCCUPANCY",
]
