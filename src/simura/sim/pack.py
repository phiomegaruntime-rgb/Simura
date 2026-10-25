"""Vectorized electro-thermal battery pack model.

Physics per cell (1st-order Thevenin equivalent circuit + lumped thermal):

    Terminal:   V = OCV(SoC) - I*R0 - V_rc
    RC branch:  dV_rc/dt = I/C1 - V_rc/(R1*C1)
    Charge:     dSoC/dt  = -eff * I / (Q * 3600)          [I>0 = discharge]
    Thermal:    dT/dt    = (Q_gen - k_cool*(T - T_amb)) / C_th
                Q_gen    = I^2*R0 + I*V_rc                 [irreversible heat]

Sign convention: current I > 0 is *discharge* (energy leaving the pack).

Parallel groups are solved exactly. All cells in a series module share one node
voltage V_mod; given each cell's OCV and RC state, we solve the single linear
equation ``sum_p (OCV - V_rc - V_mod)/R0 = I_module`` for V_mod, then recover
each cell's branch current. This makes cell-to-cell imbalance and single-cell
faults propagate correctly to their neighbours.

State is held as ``(series, parallel)`` NumPy arrays so a rack of hundreds of
cells steps in a single vectorized pass.
"""

from __future__ import annotations

import numpy as np

from .config import PackConfig
from .faults import FaultEffect
from .ocv import make_ocv


class BatteryPack:
    def __init__(self, config: PackConfig) -> None:
        self.config = config
        self.shape = (config.series, config.parallel)
        self.ocv = make_ocv()

        rng = np.random.default_rng(config.seed)
        cell = config.cell

        # Static per-cell parameters with manufacturing spread.
        self.capacity_ah = cell.capacity_ah * (
            1.0 + config.capacity_spread * rng.standard_normal(self.shape)
        )
        self.r0_nom = cell.r0_ohm * (
            1.0 + config.resistance_spread * rng.standard_normal(self.shape)
        )
        self.r1 = np.full(self.shape, cell.r1_ohm)
        self.c1 = np.full(self.shape, cell.c1_farad)
        self.coulombic_eff = cell.coulombic_eff
        self.c_th = np.full(self.shape, cell.thermal_capacity_j_per_k)
        self.k_cool_nom = np.full(self.shape, cell.cooling_conductance_w_per_k)
        self.ambient_c = config.ambient_temp_c

        # Dynamic per-cell state.
        self.soc = np.clip(
            config.initial_soc
            + config.initial_soc_spread * rng.standard_normal(self.shape),
            0.0,
            1.0,
        )
        self.v_rc = np.zeros(self.shape)
        self.temp_c = np.full(self.shape, config.ambient_temp_c)

        # Start at zero external current using the same parallel-node solve as
        # step(). Imbalanced cells may already exchange balancing current; a
        # parallel group has one terminal voltage, not the sum of its cells.
        self.cell_current_a = self._solve_module_voltages(0.0, self.r0_nom)
        self.cell_voltage_v = np.broadcast_to(self.module_voltage_v[:, None], self.shape).copy()
        self.pack_voltage_v = float(self.module_voltage_v.sum())

    # -- solver -----------------------------------------------------------
    def _solve_module_voltages(self, pack_current_a: float, r0: np.ndarray) -> np.ndarray:
        """Return per-cell current for a given pack current and effective R0.

        Pack current flows equally through every series module; within a module
        it divides across the parallel cells according to their impedance.
        """
        ocv = self.ocv(self.soc)                    # (S, P)
        emf = ocv - self.v_rc                        # driving voltage behind R0
        cond = 1.0 / r0                              # per-cell conductance
        # Node voltage for each series module (length S).
        v_mod = (np.sum(emf * cond, axis=1) - pack_current_a) / np.sum(cond, axis=1)
        self.module_voltage_v = v_mod
        # Per-cell branch current: I = (emf - V_mod) / R0.
        i_cell = (emf - v_mod[:, None]) * cond
        return i_cell

    # -- integrator -------------------------------------------------------
    def step(
        self,
        pack_current_a: float,
        dt_s: float,
        effect: FaultEffect | None = None,
        ambient_c: float | None = None,
    ) -> None:
        """Advance the pack by ``dt_s`` seconds under the given pack current.

        ``pack_current_a`` > 0 discharges the pack. ``effect`` bundles any active
        fault contributions for this step (see :mod:`simura.sim.faults`).
        ``ambient_c`` overrides the (otherwise fixed) ambient the pack cools
        toward -- this is the hook a time-varying weather source drives (see
        :mod:`simura.sim.environment`); ``None`` keeps the configured ambient.
        """
        if effect is None:
            effect = FaultEffect.zeros(self.shape)
        if ambient_c is not None:
            self.ambient_c = ambient_c

        r0 = self.r0_nom * effect.resistance_mult
        k_cool = self.k_cool_nom * effect.cooling_mult

        i_cell = self._solve_module_voltages(pack_current_a, r0)
        # Parasitic fault currents drain the cell without contributing to output.
        i_total = i_cell + effect.extra_current_a

        # SoC (coulomb counting). Charge is less efficient than discharge.
        eff = np.where(i_total >= 0.0, 1.0, self.coulombic_eff)
        self.soc = np.clip(
            self.soc - eff * i_total * dt_s / (self.capacity_ah * 3600.0), 0.0, 1.0
        )

        # RC polarization branch (uses the delivered current, not parasitic).
        dv_rc = (i_cell / self.c1 - self.v_rc / (self.r1 * self.c1)) * dt_s
        self.v_rc = self.v_rc + dv_rc

        # Thermal: irreversible ohmic + polarization heat, plus fault heat.
        q_gen = i_total**2 * r0 + i_cell * self.v_rc + effect.extra_heat_w
        dtemp = (q_gen - k_cool * (self.temp_c - self.ambient_c)) / self.c_th * dt_s
        self.temp_c = self.temp_c + dtemp

        # Diagnostics for telemetry (physical, pre-sensor-bias).
        self.cell_current_a = i_cell
        self.cell_voltage_v = self.ocv(self.soc) - i_cell * r0 - self.v_rc
        self.pack_voltage_v = float(self.module_voltage_v.sum())
        # Stash biases so telemetry can apply sensor faults without re-deriving.
        self._voltage_bias = effect.voltage_bias_v
        self._temp_bias = effect.temp_bias_c

    # -- aggregates -------------------------------------------------------
    @property
    def pack_soc(self) -> float:
        """Capacity-weighted mean SoC across the pack."""
        return float(np.average(self.soc, weights=self.capacity_ah))

    @property
    def max_temp_c(self) -> float:
        return float(self.temp_c.max())
