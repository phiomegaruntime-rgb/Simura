"""The connector data model: raw source signals and how to map them to telemetry.

A :class:`SourceFrame` is what a single protocol read produces -- named scalar
signals and named arrays, in the device's own units. A :class:`DeviceMapping`
describes how to turn that into the twin's :class:`~simura.sim.telemetry.PackTelemetry`
contract: the pack topology, unit scaling, and how to fill the per-cell fields a
real BMS usually does not measure directly (per-cell current and SoC).

Standard signal names the decoder looks for:

    scalars:  pack_current, pack_soc, sim_time
    arrays:   cell_voltage, cell_temp, cell_current (opt), cell_soc (opt)

Protocol connectors emit these names; the MQTT bridge maps a foreign schema onto
them.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SourceFrame:
    scalars: dict[str, float] = field(default_factory=dict)
    arrays: dict[str, list[float]] = field(default_factory=dict)


@dataclass
class DeviceMapping:
    """Topology + derivation rules for turning a SourceFrame into telemetry."""

    series: int
    parallel: int = 1

    # How to fill per-cell fields a BMS often does not report per cell.
    soc_mode: str = "pack"          # pack | from_voltage | array
    current_mode: str = "pack"      # pack | array
    temp_mode: str = "auto"         # auto | per_cell | per_series | broadcast

    # Unit scaling: raw device value * scale -> SI (V, A, C, fraction).
    voltage_scale: float = 1.0      # e.g. 0.001 if the device reports millivolts
    temp_scale: float = 1.0         # e.g. 0.1 if the device reports deci-degrees
    current_scale: float = 1.0      # e.g. 0.1 if the device reports deci-amps
    soc_scale: float = 1.0          # e.g. 0.01 if the device reports percent

    @property
    def n_cells(self) -> int:
        return self.series * self.parallel

    def __post_init__(self) -> None:
        if self.soc_mode not in ("pack", "from_voltage", "array"):
            raise ValueError(f"bad soc_mode: {self.soc_mode}")
        if self.current_mode not in ("pack", "array"):
            raise ValueError(f"bad current_mode: {self.current_mode}")
        if self.temp_mode not in ("auto", "per_cell", "per_series", "broadcast"):
            raise ValueError(f"bad temp_mode: {self.temp_mode}")
