"""Configuration dataclasses for the battery simulator.

These are plain, serializable descriptions of *what* to simulate. They contain
no state -- the runtime state lives in :class:`celltwin.sim.pack.BatteryPack`.
Keeping config separate from state means a twin's configuration can be stored,
versioned, and shipped over the wire independently of its live measurements.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CellParams:
    """Electro-thermal parameters for a single cell (nominal / "as new").

    Defaults approximate a 21700-format NMC Li-ion cell. All resistances are in
    ohms, capacities in amp-hours, temperatures in Celsius, thermal capacity in
    J/K, and thermal conductance to ambient in W/K.
    """

    capacity_ah: float = 5.0          # nominal usable capacity
    r0_ohm: float = 0.020             # instantaneous (ohmic) internal resistance
    r1_ohm: float = 0.010             # polarization resistance (RC branch)
    c1_farad: float = 2000.0          # polarization capacitance (tau = r1*c1 = 20 s)
    coulombic_eff: float = 0.99       # charge efficiency (<1); discharge is 1.0

    # Thermal (lumped single-node) model.
    thermal_capacity_j_per_k: float = 70.0   # m * cp for one cell
    cooling_conductance_w_per_k: float = 0.5  # h * A to ambient

    # Safe operating envelope (used for telemetry flags, not enforced physics).
    v_min: float = 2.5
    v_max: float = 4.2
    temp_max_c: float = 60.0


@dataclass
class PackConfig:
    """Topology and manufacturing spread of a pack.

    A pack is ``series`` modules in series; each module is ``parallel`` cells in
    parallel. Real cells are never identical -- the ``*_spread`` fields inject
    small Gaussian variation (as a fraction of nominal) so that imbalance and
    single-cell faults become physically meaningful. ``seed`` makes it
    reproducible.
    """

    series: int = 12                  # modules in series (sets pack voltage)
    parallel: int = 1                 # cells in parallel per module (sets current)
    cell: CellParams = field(default_factory=CellParams)

    capacity_spread: float = 0.02     # +/-2% cell-to-cell capacity variation
    resistance_spread: float = 0.05   # +/-5% resistance variation
    initial_soc: float = 0.80
    initial_soc_spread: float = 0.01  # small SoC imbalance at start
    ambient_temp_c: float = 25.0
    seed: int = 42


@dataclass
class SimConfig:
    """Simulation loop settings."""

    dt_s: float = 1.0                 # integration timestep (seconds)
    duration_s: float = 3600.0        # total simulated time
