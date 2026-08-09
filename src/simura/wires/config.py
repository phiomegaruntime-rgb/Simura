"""Declarative builders: turn plain JSON-serializable dicts into wire objects.

This is what makes wiring *declarative* -- a run or a whole network can live in a
JSON spec, an env var, or an API body and be turned into live objects here.
Mirrors :func:`simura.weather.config.build_provider` and
:func:`simura.connect.config` in spirit.
"""

from __future__ import annotations

from typing import Any

from .catalog import MATERIALS, WIRE_CATALOG
from .network import WireNetwork
from .wire import WireSpec

# Exposed for UIs / documentation / future API enumerations.
WIRE_MATERIALS = tuple(MATERIALS.keys())


def build_wire(spec: dict[str, Any]) -> WireSpec:
    """Build a :class:`WireSpec` from a dict (ignoring unknown keys)."""
    return WireSpec.from_dict(spec)


def build_network(spec: dict[str, Any]) -> WireNetwork:
    """Build a :class:`WireNetwork` from a ``{"nodes": [...], "segments": [...]}`` dict.

    ``nodes``: ``{"id", "voltage"?, "load_a"?}``. ``segments``:
    ``{"id", "from", "to", "wire": {...WireSpec fields...}}``.
    """
    net = WireNetwork()
    for node in spec.get("nodes", []):
        net.add_node(
            id=str(node["id"]),
            voltage=node.get("voltage"),
            load_a=float(node.get("load_a", 0.0)),
        )
    for seg in spec.get("segments", []):
        net.add_segment(
            id=str(seg["id"]),
            from_node=str(seg["from"]),
            to_node=str(seg["to"]),
            spec=build_wire(seg.get("wire", {})),
        )
    return net


def catalog_options() -> dict[str, Any]:
    """Enumerations for a UI: materials, insulations, and the wire catalog."""
    from .catalog import INSULATION_TEMP_C

    return {
        "materials": list(WIRE_MATERIALS),
        "insulations": list(INSULATION_TEMP_C.keys()),
        "wire_types": [w.to_dict() for w in WIRE_CATALOG],
    }
