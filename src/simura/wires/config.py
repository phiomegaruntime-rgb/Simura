"""Declarative builders: turn plain JSON-serializable dicts into wire objects.

This is what makes wiring *declarative* -- a run or a whole network can live in a
JSON spec, an env var, or an API body and be turned into live objects here.
Mirrors :func:`simura.weather.config.build_provider` and
:func:`simura.connect.config` in spirit.
"""

from __future__ import annotations

from typing import Any

from .catalog import MATERIALS, WIRE_CATALOG
from .faults import (
    ConductorDamage,
    ContactResistance,
    Fault,
    GroundFault,
    InsulationDegradation,
    ResistanceGrowth,
)
from .network import WireNetwork
from .wire import WireSpec

# Exposed for UIs / documentation / future API enumerations.
WIRE_MATERIALS = tuple(MATERIALS.keys())

# The injectable wire failure modes, keyed by the id a spec/API body uses.
WIRE_FAULT_TYPES = (
    "resistance_growth",
    "contact_resistance",
    "conductor_damage",
    "insulation_degradation",
    "ground_fault",
)


def build_wire(spec: dict[str, Any]) -> WireSpec:
    """Build a :class:`WireSpec` from a dict (ignoring unknown keys)."""
    return WireSpec.from_dict(spec)


def build_fault(spec: dict[str, Any]) -> Fault:
    """Build one wire :class:`~simura.wires.faults.Fault` from ``{"type", ...params}``.

    Mirrors :func:`simura.builder.build.build_fault` on the battery side, so a
    failure mode can be named in a JSON body (an API call, a saved scenario, a
    site layout) rather than constructed in code.
    """
    p = {k: v for k, v in spec.items() if k != "type"}
    window = {k: float(p[k]) for k in ("start_s", "end_s") if k in p}
    t = str(spec.get("type", ""))
    if t == "resistance_growth":
        return ResistanceGrowth(
            rate_per_s=float(p.get("rate_per_s", 1e-4)),
            max_mult=float(p.get("max_mult", 3.0)),
            **window,
        )
    if t == "contact_resistance":
        return ContactResistance(added_ohm=float(p.get("added_ohm", 0.01)), **window)
    if t == "conductor_damage":
        return ConductorDamage(area_loss_frac=float(p.get("area_loss_frac", 0.3)), **window)
    if t == "insulation_degradation":
        return InsulationDegradation(rating_drop_c=float(p.get("rating_drop_c", 20.0)), **window)
    if t == "ground_fault":
        return GroundFault(leakage_a=float(p.get("leakage_a", 1.0)), **window)
    raise ValueError(f"unknown wire fault type '{t}' (use one of {', '.join(WIRE_FAULT_TYPES)})")


def build_network(spec: dict[str, Any]) -> WireNetwork:
    """Build a :class:`WireNetwork` from a ``{"nodes": [...], "segments": [...]}`` dict.

    ``nodes``: ``{"id", "voltage"?, "load_a"?}``. ``segments``:
    ``{"id", "from", "to", "wire": {...WireSpec fields...}, "faults"?: [{...}]}``.
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
            faults=[build_fault(f) for f in seg.get("faults", [])],
        )
    return net


def catalog_options() -> dict[str, Any]:
    """Enumerations for a UI: materials, insulations, wire catalog, fault types."""
    from .catalog import INSULATION_TEMP_C

    return {
        "materials": list(WIRE_MATERIALS),
        "insulations": list(INSULATION_TEMP_C.keys()),
        "wire_types": [w.to_dict() for w in WIRE_CATALOG],
        "fault_types": list(WIRE_FAULT_TYPES),
    }
