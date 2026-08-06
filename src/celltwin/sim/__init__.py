"""Physics simulator for the CellTwin battery digital twin."""

from .config import CellParams, PackConfig, SimConfig
from .environment import EnvironmentCoupling, EnvironmentEffect
from .faults import (
    CoolingFault,
    Fault,
    InternalShort,
    ResistanceGrowth,
    SensorDrift,
    ThermalRunaway,
)
from .ocv import (
    LCO_OCV_TABLE,
    LFP_OCV_TABLE,
    NCA_OCV_TABLE,
    NMC_OCV_TABLE,
    OCV_TABLES,
    chemistry_key_for,
    make_ocv,
    make_soc_from_ocv,
    ocv_table_for,
)
from .pack import BatteryPack
from .profiles import (
    ChargeDischargeCycle,
    ConstantCurrent,
    ConstantPower,
    LoadProfile,
    sinusoidal,
)
from .simulator import Simulator
from .telemetry import CellTelemetry, PackTelemetry

__all__ = [
    "CellParams",
    "PackConfig",
    "SimConfig",
    "BatteryPack",
    "Simulator",
    "EnvironmentCoupling",
    "EnvironmentEffect",
    "Fault",
    "ResistanceGrowth",
    "InternalShort",
    "CoolingFault",
    "ThermalRunaway",
    "SensorDrift",
    "ConstantCurrent",
    "ConstantPower",
    "ChargeDischargeCycle",
    "LoadProfile",
    "sinusoidal",
    "CellTelemetry",
    "PackTelemetry",
    "make_ocv",
    "make_soc_from_ocv",
    "ocv_table_for",
    "chemistry_key_for",
    "OCV_TABLES",
    "NMC_OCV_TABLE",
    "LFP_OCV_TABLE",
    "LCO_OCV_TABLE",
    "NCA_OCV_TABLE",
]
