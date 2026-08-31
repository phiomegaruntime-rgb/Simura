"""The user-defined system specification -- a plain, JSON-serializable description
of a battery system to simulate.

A :class:`SystemSpec` is everything needed to stand up a twin: chemistry, cell
parameters, pack topology, the load profile it runs, any faults to inject, and
the simulation settings. It contains no runtime state -- it's a *recipe*. The
builder turns it into a live :class:`~simura.sim.simulator.Simulator`
(:mod:`simura.builder.build`), previews it offline
(:mod:`simura.builder.preview`), or the publisher streams it into the twin.

Everything is a dataclass of primitives (plus two small nested dataclasses) so it
round-trips cleanly through JSON -- the dashboard form, the API body, and the
``python -m simura.publisher --spec file.json`` command all speak the same shape.
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
class WeatherSpec:
    """Optional environmental weather source driving the pack's ambient/cooling.

    ``type`` is one of ``none | static | synthetic | csv | open_meteo`` (see
    :mod:`simura.weather.config`). ``params`` carries the provider's settings
    (e.g. ``latitude``/``longitude`` for ``open_meteo``). ``type="none"`` (the
    default) means the pack uses its fixed ``ambient_temp_c`` as before.
    """

    type: str = "none"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class SpaceSpec:
    """Optional building the system stands in -- which room, in which floor plan.

    ``type`` is one of ``none | rect | json | gbxml | dxf | ifc | ifc_full`` (see
    :mod:`simura.space.config`), ``params`` carries the provider's settings (a
    ``path``, usually), and ``space_id`` names the room within that plan.

    It is deliberately the same two-field shape as :class:`WeatherSpec`, because
    it answers the neighbouring question. Weather says *what the sky is doing*;
    this says *whether the sky reaches the equipment at all*. A rack in a
    conditioned plant room sits at a setpoint with no solar gain; the same rack
    in a yard takes the weather in full -- and until a spec could say which, that
    difference had to be typed in as an ambient somebody guessed.

    ``type="none"`` (the default) means no building, and the pack behaves exactly
    as it did before this field existed.
    """

    type: str = "none"
    params: dict[str, Any] = field(default_factory=dict)
    space_id: str = ""


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
    weather: WeatherSpec = field(default_factory=WeatherSpec)
    space: SpaceSpec = field(default_factory=SpaceSpec)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SystemSpec":
        """Build a spec from a (possibly partial) dict, ignoring unknown keys.

        Missing keys fall back to the field defaults, so the dashboard can send
        just what the user changed and older/newer clients stay compatible.
        """
        known = {f.name for f in fields(cls)}
        nested = ("profile", "faults", "weather", "space")
        kwargs: dict[str, Any] = {k: v for k, v in d.items() if k in known and k not in nested}

        weather = d.get("weather")
        if isinstance(weather, dict):
            kwargs["weather"] = WeatherSpec(
                type=str(weather.get("type", "none")),
                params=dict(weather.get("params", {})),
            )

        space = d.get("space")
        if isinstance(space, dict):
            kwargs["space"] = SpaceSpec(
                type=str(space.get("type", "none")),
                params=dict(space.get("params", {})),
                space_id=str(space.get("space_id", "")),
            )

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
