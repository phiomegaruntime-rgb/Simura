"""Build a plan provider from a plain, JSON-serializable spec dict.

This is what makes a building *declarative*, and it is a direct copy of
:mod:`simura.weather.config` -- deliberately, because the two fields end up
sitting next to each other in the same documents::

    {
      "weather": {"type": "open_meteo", "latitude": 51.5, "longitude": -0.13},
      "space":   {"type": "ifc", "path": "models/office.ifc", "space_id": "#412"}
    }

A system spec, an env var, a request body or a library entry can therefore name
the building a system stands in the same way it names the sky over it, and
:func:`build_provider` turns either into something live.

The types
---------

``none``      no building. The default, and what every existing system has.
``rect``      a generated row of rooms -- offline, deterministic, no file.
``inline``    the plan carried in the spec itself. What a browser and a saved
              system use, since neither can rely on a path still existing.
``json``      a plan previously imported and saved. The fast path.
``gbxml``     a gbXML energy model.
``dxf``       an ASCII DXF drawing.
``ifc``       an IFC STEP model, read in pure Python.
``ifc_full``  the same, resolved by ``ifcopenshell`` if it is installed.

:data:`PLAN_PARAMS` gives each type's parameters and defaults, which is what lets
the dashboard build its import form from the server's own answer rather than a
second copy of this list that drifts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .provider import PlanError, PlanProvider
from .providers import (
    DxfProvider,
    InlinePlanProvider,
    GbxmlProvider,
    IfcFullProvider,
    IfcProvider,
    JsonPlanProvider,
    RectangleProvider,
)

# The set of provider types `build_provider` understands. "none" is a sentinel
# meaning "no building" -- callers should treat it as None and skip the coupling,
# exactly as WEATHER_TYPES does.
PLAN_TYPES = ("none", "rect", "inline", "json", "gbxml", "dxf", "ifc", "ifc_full")

# Which types read a file. Used by the API to decide whether a spec needs an
# upload behind it, and by the CLI to decide whether to expect a path.
FILE_TYPES = ("json", "gbxml", "dxf", "ifc", "ifc_full")

# Default params per type, for UIs and documentation.
PLAN_PARAMS: dict[str, dict[str, Any]] = {
    "none": {},
    "inline": {"plan": {}},
    "rect": {
        "name": "Example building",
        "rooms": 4,
        "room_length_m": 6.0,
        "room_width_m": 4.0,
        "corridor_width_m": 1.8,
        "height_m": 2.7,
        "levels": 1,
    },
    "json": {"path": ""},
    "gbxml": {"path": ""},
    "dxf": {
        "path": "",
        "wall_layers": "",
        "room_layers": "",
        "scale": 0.0,
        "wall_height_m": 3.0,
        "wall_thickness_m": 0.2,
        "room_height_m": 2.7,
    },
    "ifc": {"path": ""},
    "ifc_full": {"path": ""},
}

# Filename suffix -> provider type, for `detect_format`.
SUFFIX_TYPES: dict[str, str] = {
    ".ifc": "ifc",
    ".step": "ifc",
    ".stp": "ifc",
    ".xml": "gbxml",
    ".gbxml": "gbxml",
    ".dxf": "dxf",
    ".json": "json",
}


def build_provider(spec: dict[str, Any] | None) -> PlanProvider | None:
    """Turn a ``{"type": ..., ...}`` dict into a provider (``None`` for "none")."""
    if not spec:
        return None
    kind = str(spec.get("type", "none")).lower()
    params = {k: v for k, v in spec.items() if k not in ("type", "space_id")}

    if kind in ("none", ""):
        return None
    if kind == "rect":
        return RectangleProvider(**_filter(params, RectangleProvider))
    if kind == "inline":
        return InlinePlanProvider(plan=params.get("plan"))
    if kind in FILE_TYPES:
        path = params.get("path")
        data = params.get("data")
        if not path and not data:
            raise PlanError(f"the '{kind}' plan provider needs a 'path'")
        if kind == "json":
            return JsonPlanProvider(path, data=data, name=params.get("name", ""))
        if kind == "gbxml":
            return GbxmlProvider(path, data=data, name=params.get("name", ""))
        if kind == "dxf":
            return DxfProvider(path, data=data, **_dxf_params(params))
        if kind == "ifc":
            return IfcProvider(path, data=data, name=params.get("name", ""))
        if kind == "ifc_full":
            if not path:
                raise PlanError(
                    "the 'ifc_full' provider reads through ifcopenshell, which needs "
                    "a file on disk rather than an in-memory upload"
                )
            return IfcFullProvider(path, name=params.get("name", ""))

    raise PlanError(f"unknown plan provider type '{kind}' (use one of {PLAN_TYPES})")


def detect_format(filename: str, data: bytes | None = None) -> str:
    """The provider type for a file, from its name and then from its contents.

    The suffix is tried first because it is right nearly always and costs nothing.
    Contents are the tie-breaker for the case the suffix cannot settle: ``.xml``
    is gbXML or it is somebody else's XML, and a ``.txt`` that begins
    ``ISO-10303-21`` is an IFC file whoever exported it mislabelled.
    """
    suffix = Path(str(filename or "")).suffix.lower()
    guess = SUFFIX_TYPES.get(suffix, "")

    if data:
        head = data[:4096].decode("utf-8", errors="replace")
        if "ISO-10303-21" in head or "IFCPROJECT" in head.upper():
            return "ifc"
        if "<gbXML" in head:
            return "gbxml"
        if "AutoCAD Binary DXF" in head:
            raise PlanError(
                "this is a binary DXF; re-export it as ASCII DXF (R12 or later)"
            )
        if "SECTION" in head and "HEADER" in head and "$ACADVER" in head:
            return "dxf"
        if guess == "gbxml" and "<gbXML" not in head:
            raise PlanError(
                "this XML file is not a gbXML document (no <gbXML> root element)"
            )

    if not guess:
        raise PlanError(
            f"cannot tell what kind of building file '{filename}' is. Supported: "
            f".ifc (IFC STEP), .xml/.gbxml (gbXML), .dxf (ASCII DXF), "
            f".json (a saved Simura plan)."
        )
    return guess


def _dxf_params(params: dict[str, Any]) -> dict[str, Any]:
    """DXF's layer lists arrive from a form as comma-separated text."""
    out = _filter(params, DxfProvider)
    for key in ("wall_layers", "room_layers"):
        value = out.get(key)
        if isinstance(value, str):
            parts = tuple(p.strip() for p in value.split(",") if p.strip())
            out[key] = parts or None
        elif isinstance(value, (list, tuple)):
            out[key] = tuple(value) or None
    # A zero scale from a form means "not set", not "collapse the building".
    if not out.get("scale"):
        out.pop("scale", None)
    out.pop("path", None)
    out.pop("data", None)
    return out


def _filter(params: dict[str, Any], cls: type) -> dict[str, Any]:
    """Keep only params that ``cls.__init__`` accepts (forgiving of extra keys)."""
    import inspect

    allowed = set(inspect.signature(cls.__init__).parameters) - {"self"}
    return {k: v for k, v in params.items() if k in allowed}
