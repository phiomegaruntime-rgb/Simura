"""Initial diagnostics obey the pack topology before a profile reads voltage.

Synthetic circuit checks only, not a validation of battery or fault fidelity.
Assisted-by: Codex:unknown
"""

from __future__ import annotations

import numpy as np
import pytest

from simura.sim import ConstantPower, PackConfig, SimConfig, Simulator
from simura.sim.pack import BatteryPack
from simura.sim.telemetry import snapshot


@pytest.mark.parametrize("parallel", [1, 4])
def test_uniform_initial_voltage_depends_on_series_not_parallel_count(parallel):
    pack = BatteryPack(PackConfig(
        series=12, parallel=parallel, initial_soc=0.8,
        initial_soc_spread=0.0, resistance_spread=0.0, capacity_spread=0.0,
    ))
    cell_ocv = float(pack.ocv(np.array([0.8]))[0])
    np.testing.assert_allclose(pack.module_voltage_v, cell_ocv, rtol=0, atol=1e-12)
    np.testing.assert_allclose(pack.cell_voltage_v, cell_ocv, rtol=0, atol=1e-12)
    np.testing.assert_allclose(pack.cell_current_a, 0.0, rtol=0, atol=1e-12)
    assert pack.pack_voltage_v == pytest.approx(12 * cell_ocv)
    np.testing.assert_array_equal(pack.soc, 0.8)
    np.testing.assert_array_equal(pack.v_rc, 0.0)
    np.testing.assert_array_equal(pack.temp_c, pack.config.ambient_temp_c)


def test_imbalanced_initial_diagnostics_satisfy_zero_external_current_nodes():
    pack = BatteryPack(PackConfig(
        series=3, parallel=4, initial_soc_spread=0.12, resistance_spread=0.2, seed=7,
    ))
    emf = pack.ocv(pack.soc)
    conductance = 1.0 / pack.r0_nom
    expected_nodes = np.sum(emf * conductance, axis=1) / np.sum(conductance, axis=1)
    expected_currents = (emf - expected_nodes[:, None]) * conductance
    assert np.max(np.abs(expected_currents)) > 0.1
    np.testing.assert_allclose(pack.module_voltage_v, expected_nodes, rtol=0, atol=1e-12)
    np.testing.assert_allclose(pack.cell_current_a, expected_currents, rtol=0, atol=1e-12)
    np.testing.assert_allclose(pack.cell_current_a.sum(axis=1), 0.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(pack.cell_voltage_v, emf - pack.cell_current_a * pack.r0_nom, rtol=0, atol=1e-12)
    assert pack.pack_voltage_v == pytest.approx(float(expected_nodes.sum()))


def test_snapshot_before_first_step_reports_the_solved_parallel_nodes():
    pack = BatteryPack(PackConfig(series=2, parallel=3, seed=11))
    telemetry = snapshot(pack, 0.0, 0.0)
    emf = pack.ocv(pack.soc)
    nodes = (emf / pack.r0_nom).sum(axis=1) / (1.0 / pack.r0_nom).sum(axis=1)
    assert telemetry.time_s == 0.0
    assert telemetry.pack_voltage_v == round(float(nodes.sum()), 4)
    for cell in telemetry.cells:
        assert cell.voltage_v == round(float(nodes[cell.series_index]), 4)


def test_constant_power_profile_reads_correct_voltage_on_its_first_call():
    class RecordingPower(ConstantPower):
        def __init__(self):
            super().__init__(1000.0)
            self.calls = []

        def current(self, t, pack_voltage_v):
            current = super().current(t, pack_voltage_v)
            self.calls.append((t, pack_voltage_v, current))
            return current

    config = PackConfig(series=12, parallel=4, initial_soc=0.8,
                        initial_soc_spread=0.0, resistance_spread=0.0, capacity_spread=0.0)
    profile = RecordingPower()
    simulator = Simulator(config, SimConfig(dt_s=1.0, duration_s=1.0), profile)
    expected_voltage = 12 * float(simulator.pack.ocv(np.array([0.8]))[0])
    simulator.run_to_list()
    assert len(profile.calls) == 1
    time, voltage, current = profile.calls[0]
    assert time == 0.0
    assert voltage == pytest.approx(expected_voltage)
    assert current == pytest.approx(1000.0 / expected_voltage)
