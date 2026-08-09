"""Reusable, domain-agnostic wire (conductor) simulation and wiring planning.

This subpackage knows **conductors and electrical physics, not batteries** -- the
same deliberate independence as :mod:`simura.weather`. It models a wire's
resistance, voltage drop, ohmic loss and electro-thermal heating; carries a
catalog of real wire types to pick from; injects wiring faults (corrosion, loose
joints, conductor damage, insulation ageing, ground faults); and answers the
planning questions an engineer asks before pulling cable -- *is this run within
ampacity, is the voltage drop acceptable, what gauge should I use?* -- for a
single run or across a multi-node network.

That battery-free design keeps the conductor physics reusable on its own, with no
dependency on the battery model.

    from simura.wires import WireSpec, evaluate_run, recommend_gauge

    a = evaluate_run(WireSpec(awg=12, length_m=20), current_a=15,
                     system_voltage_v=12, round_trip=True)
    print(a.voltage_drop_pct, a.problems)

    rec = recommend_gauge(current_a=15, length_m=20, system_voltage_v=12, max_drop_pct=3)
    print(rec.wire_type.name, rec.rationale)
"""

from .catalog import (
    INSULATION_TEMP_C,
    MATERIALS,
    WIRE_CATALOG,
    ConductorMaterial,
    WireType,
    awg_area_mm2,
    insulation_temp_c,
    list_wire_types,
    material_for,
    wire_type_for,
)
from .config import WIRE_MATERIALS, build_network, build_wire, catalog_options
from .faults import (
    ConductorDamage,
    ContactResistance,
    Fault,
    FaultEffect,
    GroundFault,
    InsulationDegradation,
    ResistanceGrowth,
    accumulate,
)
from .network import (
    NetworkResult,
    Node,
    Segment,
    SegmentResult,
    WireNetwork,
)
from .planning import Recommendation, RunAssessment, evaluate_run, recommend_gauge
from .profiles import ConstantCurrent, CurrentProfile, DutyCycle, StepCurrent, sinusoidal
from .simulator import WireSimConfig, WireSimulator
from .telemetry import WireTelemetry
from .wire import Wire, WireSpec

__all__ = [
    # catalog
    "ConductorMaterial",
    "WireType",
    "MATERIALS",
    "INSULATION_TEMP_C",
    "WIRE_CATALOG",
    "awg_area_mm2",
    "material_for",
    "insulation_temp_c",
    "wire_type_for",
    "list_wire_types",
    # core model
    "WireSpec",
    "Wire",
    "WireTelemetry",
    "WireSimulator",
    "WireSimConfig",
    # profiles
    "CurrentProfile",
    "ConstantCurrent",
    "StepCurrent",
    "DutyCycle",
    "sinusoidal",
    # faults
    "Fault",
    "FaultEffect",
    "ResistanceGrowth",
    "ContactResistance",
    "ConductorDamage",
    "InsulationDegradation",
    "GroundFault",
    "accumulate",
    # planning
    "evaluate_run",
    "recommend_gauge",
    "RunAssessment",
    "Recommendation",
    # network
    "WireNetwork",
    "Node",
    "Segment",
    "SegmentResult",
    "NetworkResult",
    # declarative
    "build_wire",
    "build_network",
    "catalog_options",
    "WIRE_MATERIALS",
]
