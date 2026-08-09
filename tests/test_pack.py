"""Physics sanity checks for the pack model.

These assert the invariants that must hold for the twin to be trustworthy:
charge conservation, energy-consistent heating, correct parallel current
sharing, and that faults actually change behaviour.
"""

from __future__ import annotations

import numpy as np

from simura.sim import (
    CoolingFault,
    InternalShort,
    PackConfig,
    SimConfig,
    Simulator,
    ConstantCurrent,
)
from simura.sim.faults import FaultEffect, accumulate
from simura.sim.pack import BatteryPack


def _run(profile, faults=None, duration=600.0, **pack_kw):
    pack = PackConfig(**pack_kw)
    sim = SimConfig(dt_s=1.0, duration_s=duration)
    return Simulator(pack, sim, profile, faults or []).run_to_list()


def test_discharge_reduces_soc():
    tel = _run(ConstantCurrent(10.0), series=10, parallel=1, initial_soc=0.8)
    assert tel[-1].pack_soc < 0.8
    # Voltage should stay within a physically plausible band.
    assert all(2.0 < c.voltage_v < 4.3 for c in tel[-1].cells)


def test_coulomb_counting_matches_capacity():
    # Discharge a single-cell pack at 1 A for 360 s => 0.1 Ah removed.
    pack = PackConfig(series=1, parallel=1, initial_soc=0.8, capacity_spread=0.0)
    cap = pack.cell.capacity_ah
    tel = _run(ConstantCurrent(1.0), series=1, parallel=1, initial_soc=0.8,
               capacity_spread=0.0, initial_soc_spread=0.0, duration=360.0)
    expected_drop = (1.0 * 360.0 / 3600.0) / cap
    actual_drop = 0.8 - tel[-1].pack_soc
    assert abs(actual_drop - expected_drop) < 1e-3


def test_charging_increases_soc():
    tel = _run(ConstantCurrent(-10.0), series=8, parallel=1, initial_soc=0.5)
    assert tel[-1].pack_soc > 0.5


def test_parallel_currents_sum_to_pack_current():
    pack = BatteryPack(PackConfig(series=3, parallel=4, seed=1))
    effect = FaultEffect.zeros(pack.shape)
    pack.step(20.0, 1.0, effect)
    # Each series module's parallel branch currents must sum to the pack current.
    per_module = pack.cell_current_a.sum(axis=1)
    assert np.allclose(per_module, 20.0, atol=1e-6)


def test_discharge_heats_pack():
    tel = _run(ConstantCurrent(30.0), series=6, parallel=2, initial_soc=0.9)
    # I^2 R heating must raise temperature above ambient (25 C default).
    assert tel[-1].max_temp_c > 25.5


def test_internal_short_drains_and_heats_target_cell():
    healthy = _run(ConstantCurrent(0.0), series=5, parallel=1, initial_soc=0.8, duration=600.0)
    faulted = _run(
        ConstantCurrent(0.0),
        faults=[InternalShort(cell=(2, 0), r_short_ohm=2.0)],
        series=5, parallel=1, initial_soc=0.8, duration=600.0,
    )
    # The shorted cell should self-discharge below its healthy counterpart...
    assert faulted[-1].cells[2].soc < healthy[-1].cells[2].soc - 1e-3
    # ...and run hotter than the rest of the pack.
    temps = [c.temp_c for c in faulted[-1].cells]
    assert temps[2] == max(temps)


def test_cooling_fault_raises_temperature():
    base = _run(ConstantCurrent(25.0), series=6, parallel=1, initial_soc=0.9)
    hot = _run(
        ConstantCurrent(25.0),
        faults=[CoolingFault(effectiveness=0.2)],
        series=6, parallel=1, initial_soc=0.9,
    )
    assert hot[-1].max_temp_c > base[-1].max_temp_c
