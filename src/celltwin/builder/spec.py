"""The user-defined system specification -- a plain, JSON-serializable description
of a battery system to simulate.

A :class:`SystemSpec` is everything needed to stand up a twin: chemistry, cell
parameters, pack topology, the load profile it runs, any faults to inject, and
the simulation settings. It contains no runtime state -- it's a *recipe*. The
builder turns it into a live :class:`~celltwin.sim.simulator.Simulator`
(:mod:`celltwin.builder.build`), previews it offline
(:mod:`celltwin.builder.preview`), or the publisher streams it into the twin.

Everything is a dataclass of primitives (plus two small nested dataclasses) so it
round-trips cleanly through JSON -- the dashboard form, the API body, and the
``python -m celltwin.publisher --spec file.json`` command all speak the same shape.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any


@dataclass
class ProfileSpec:
    """How the pack is charged/discharged. ``type`` selects which params apply."""

    type: str = "cycle"  # constant_current | constant_power | cycle | sinusoidal
    params: dict[str, float] = field(default_factory=dict)


@dataclass
class FaultSpec:
    """A fault to inject at one cell, on a schedule. ``type`` selects the params."""

    type: str = "internal_short"
    series: int = 0
    parallel: int = 0
    start_s: float = 600.0
    params: dict[str, float] = field(default_factory=dict)


@dataclass
class SystemSpec:
    """A complete, serializable description of a battery system to simulate."""

    system_id: str = "my-bess-01"
    name: str = "My BESS"
    chemistry: str = "NMC"  # NMC | LFP | LCO | NCA -> selects the OCV curve

    # Cell electro-thermal parameters (override CellParams defaults).
    capacity_ah: float = 5.0
    r0_ohm: float = 0.020
    r1_ohm: float = 0.010
    c1_farad: float = 2000.0
    coulombic_eff: float = 0.99
    thermal_capacity_j_per_k: float = 70.0
    cooling_conductance_w_per_k: float = 0.5
    v_min: float = 2.5
    v_max: float = 4.2
    temp_max_c: float = 60.0

    # Pack topology + manufacturing spread.
    series: int = 12
    parallel: int = 2
    capacity_spread: float = 0.02
    resistance_spread: float = 0.05
    initial_soc: float = 0.80
    initial_soc_spread: float = 0.01
    ambient_temp_c: float = 25.0
    seed: int = 42

    # Simulation loop.
    dt_s: float = 1.0
    duration_s: float = 3600.0

    profile: ProfileSpec = field(default_factory=ProfileSpec)
    faults: list[FaultSpec] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SystemSpec":
        """Build a spec from a (possibly partial) dict, ignoring unknown keys.

        Missing keys fall back to the field defaults, so the dashboard can send
        just what the user changed and older/newer clients stay compatible.
        """
        known = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {k: v for k, v in d.items() if k in known and k not in ("profile", "faults")}

        prof = d.get("profile")
        if isinstance(prof, dict):
            kwargs["profile"] = ProfileSpec(
                type=str(prof.get("type", "cycle")),
                params=dict(prof.get("params", {})),
            )

        faults = d.get("faults")
        if isinstance(faults, list):
            kwargs["faults"] = [
                FaultSpec(
                    type=str(f.get("type", "internal_short")),
                    series=int(f.get("series", 0)),
                    parallel=int(f.get("parallel", 0)),
                    start_s=float(f.get("start_s", 0.0)),
                    params=dict(f.get("params", {})),
                )
                for f in faults
                if isinstance(f, dict)
            ]

        return cls(**kwargs)

    def n_steps(self) -> int:
        """Number of integration steps this spec would run (``duration/dt``)."""
        if self.dt_s <= 0:
            return 0
        return int(self.duration_s / self.dt_s)
