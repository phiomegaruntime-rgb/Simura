"""Tests for the wire library. Fully offline and deterministic.

Covers the physics (resistance vs the textbook 12 AWG value, temperature
dependence, thermal steady state), the catalog, fault injection, the planning
checks (ampacity / voltage drop / gauge sizing), and the multi-node network solve
(current conservation, monotonic voltage drop).
"""

from __future__ import annotations

import math

import pytest

from simura.wires import (
    ConductorDamage,
    ConstantCurrent,
    ContactResistance,
    GroundFault,
    InsulationDegradation,
    ResistanceGrowth,
    Wire,
    WireNetwork,
    WireSimConfig,
    WireSimulator,
    WireSpec,
    WireTelemetry,
    awg_area_mm2,
    build_network,
    build_wire,
    catalog_options,
    evaluate_run,
    list_wire_types,
    material_for,
    recommend_gauge,
    wire_type_for,
)
from simura.wires.faults import FaultEffect, accumulate
from simura.wires.telemetry import snapshot


# -- catalog & geometry ----------------------------------------------------
def test_awg_area_matches_standard_values():
    # 12 AWG ~ 3.31 mm^2; 1/0 (awg=0) ~ 53.5 mm^2. Standard table values.
    assert awg_area_mm2(12) == pytest.approx(3.31, abs=0.02)
    assert awg_area_mm2(0) == pytest.approx(53.5, abs=0.5)
    # A larger number is a thinner wire.
    assert awg_area_mm2(14) < awg_area_mm2(12) < awg_area_mm2(10)


def test_material_lookup_and_unknown():
    assert material_for("COPPER").key == "copper"
    with pytest.raises(ValueError):
        material_for("unobtanium")


def test_catalog_is_populated_and_indexed():
    assert len(list_wire_types()) >= 10
    wt = wire_type_for("cu-12-thhn90")
    assert wt.material == "copper" and wt.awg == 12
    with pytest.raises(ValueError):
        wire_type_for("nope")


# -- resistance physics ----------------------------------------------------
def test_resistance_matches_textbook_12awg():
    # 12 AWG copper is ~5.1 ohm/km at 20 C.
    wire = Wire(WireSpec(material="copper", awg=12, length_m=1000.0, ambient_temp_c=20.0))
    assert wire.resistance_20c_ohm == pytest.approx(5.1, abs=0.2)


def test_resistance_rises_with_temperature():
    wire = Wire(WireSpec(awg=10, length_m=10.0))
    cold = wire.resistance_ohm(0.0)
    hot = wire.resistance_ohm(80.0)
    assert hot > cold
    # rho is referenced to 20 C: ratio = (1 + a*60) / (1 + a*(-20)) for copper.
    a = 0.00393
    assert hot / cold == pytest.approx((1 + a * 60) / (1 + a * -20), rel=0.01)


def test_resistance_scales_with_length_and_inverse_area():
    short = Wire(WireSpec(awg=12, length_m=1.0))
    long = Wire(WireSpec(awg=12, length_m=3.0))
    assert long.resistance_ohm(25.0) == pytest.approx(3 * short.resistance_ohm(25.0), rel=1e-6)
    thin = Wire(WireSpec(awg=14, length_m=1.0))
    assert thin.resistance_ohm(25.0) > short.resistance_ohm(25.0)


def test_voltage_drop_and_power_loss():
    wire = Wire(WireSpec(awg=12, length_m=10.0, ambient_temp_c=25.0))
    r = wire.resistance_ohm(25.0)
    assert wire.voltage_drop_v(10.0, at_temp_c=25.0) == pytest.approx(10.0 * r)
    assert wire.power_loss_w(10.0, at_temp_c=25.0) == pytest.approx(100.0 * r)


# -- thermal model ---------------------------------------------------------
def test_steady_state_temp_balances_heat_and_cooling():
    wire = Wire(WireSpec(awg=14, length_m=2.0, ambient_temp_c=25.0))
    i = 20.0
    t_ss = wire.steady_state_temp_c(i)
    # At equilibrium, I^2 R(T) == k_cool (T - T_amb).
    lhs = i * i * wire.resistance_ohm(t_ss)
    rhs = wire.k_cool * (t_ss - wire.ambient_c)
    assert lhs == pytest.approx(rhs, rel=1e-3)
    assert t_ss > wire.ambient_c


def test_simulator_converges_to_steady_state():
    spec = WireSpec(awg=12, length_m=2.0, ambient_temp_c=25.0)
    sim = WireSimulator(spec=spec, sim_config=WireSimConfig(dt_s=1.0, duration_s=3000.0),
                        profile=ConstantCurrent(20.0))
    frames = sim.run_to_list()
    expected = Wire(spec).steady_state_temp_c(20.0)
    assert frames[-1].temp_c == pytest.approx(expected, abs=0.5)
    # Monotonic heating from ambient (no oscillation / blow-up).
    temps = [f.temp_c for f in frames]
    assert temps[0] > 25.0 and all(b >= a - 1e-6 for a, b in zip(temps, temps[1:]))


def test_higher_current_runs_hotter():
    spec = WireSpec(awg=12, length_m=2.0)
    assert Wire(spec).steady_state_temp_c(30.0) > Wire(spec).steady_state_temp_c(10.0)


# -- spec resolution -------------------------------------------------------
def test_spec_from_wire_type_fills_defaults():
    wire = Wire(WireSpec(wire_type="cu-10-thhn90", length_m=5.0))
    assert wire.area_mm2 == pytest.approx(awg_area_mm2(10), abs=0.01)
    assert wire.ampacity_a == 35.0
    assert wire.temp_rating_c == 90.0


def test_spec_needs_a_size():
    with pytest.raises(ValueError):
        Wire(WireSpec(material="copper", length_m=1.0))


def test_awg_ampacity_falls_back_to_catalog():
    # awg + insulation matching a catalog row should adopt its ampacity.
    wire = Wire(WireSpec(awg=12, insulation="THHN-90", length_m=1.0))
    assert wire.ampacity_a == 25.0


# -- planning: evaluate ----------------------------------------------------
def test_evaluate_flags_over_ampacity():
    a = evaluate_run(WireSpec(awg=14, insulation="THHN-90", length_m=1.0), current_a=30.0)
    assert a.ampacity_utilization > 1.0
    assert any("ampacity" in p for p in a.problems)
    assert not a.ok


def test_evaluate_flags_voltage_drop():
    a = evaluate_run(WireSpec(awg=14, length_m=20.0), current_a=10.0,
                     system_voltage_v=12.0, max_drop_pct=3.0, round_trip=True)
    assert a.voltage_drop_pct is not None and a.voltage_drop_pct > 3.0
    assert any("voltage drop" in p for p in a.problems)


def test_evaluate_ok_for_a_good_run():
    a = evaluate_run(WireSpec(awg=8, insulation="THHN-90", length_m=2.0), current_a=15.0,
                     system_voltage_v=48.0, max_drop_pct=3.0, round_trip=True)
    assert a.ok and not a.problems


def test_round_trip_doubles_the_drop():
    spec = WireSpec(awg=12, length_m=10.0)
    one = evaluate_run(spec, 10.0, system_voltage_v=48.0, round_trip=False)
    two = evaluate_run(spec, 10.0, system_voltage_v=48.0, round_trip=True)
    assert two.voltage_drop_v == pytest.approx(2 * one.voltage_drop_v, rel=1e-6)


# -- planning: recommend ---------------------------------------------------
def test_recommend_picks_smallest_adequate():
    rec = recommend_gauge(current_a=15.0, length_m=2.0, system_voltage_v=48.0,
                          max_drop_pct=3.0, round_trip=True)
    assert rec.ok and rec.wire_type is not None
    assert rec.assessment.ok
    # Anything strictly smaller in the catalog should fail the constraints.
    smaller = [w for w in list_wire_types()
               if w.material == "copper" and w.area_mm2 < rec.wire_type.area_mm2]
    for w in smaller:
        a = evaluate_run(WireSpec(wire_type=w.id, length_m=2.0), 15.0,
                         system_voltage_v=48.0, max_drop_pct=3.0, round_trip=True)
        assert not a.ok


def test_recommend_upsizes_for_long_low_voltage_run():
    # A long 12 V run is drop-limited, forcing a much larger gauge than ampacity.
    rec = recommend_gauge(current_a=15.0, length_m=20.0, system_voltage_v=12.0,
                          max_drop_pct=3.0, round_trip=True)
    assert rec.ok
    assert rec.wire_type.area_mm2 > awg_area_mm2(10)


def test_recommend_reports_failure_when_nothing_fits():
    rec = recommend_gauge(current_a=5000.0, length_m=5.0, system_voltage_v=12.0,
                          max_drop_pct=1.0)
    assert not rec.ok
    assert rec.assessment is not None and rec.assessment.problems


# -- faults ----------------------------------------------------------------
def test_resistance_growth_raises_resistance_over_time():
    f = ResistanceGrowth(rate_per_s=1e-3)
    early = accumulate([f], None, 10.0)
    late = accumulate([f], None, 500.0)
    assert late.resistance_mult > early.resistance_mult > 1.0


def test_contact_resistance_adds_series_ohms_and_heat():
    wire = Wire(WireSpec(awg=12, length_m=1.0, ambient_temp_c=25.0))
    base_r = wire.resistance_ohm(25.0)
    eff = accumulate([ContactResistance(added_ohm=0.05)], wire, 0.0)
    wire.step(20.0, 1.0, effect=eff)
    assert wire._last_resistance_ohm > base_r + 0.04


def test_conductor_damage_derates_ampacity_and_raises_resistance():
    wire = Wire(WireSpec(wire_type="cu-12-thhn90", length_m=1.0))
    eff = accumulate([ConductorDamage(area_loss_frac=0.5)], wire, 0.0)
    assert eff.ampacity_mult == pytest.approx(0.5)
    assert eff.resistance_mult == pytest.approx(2.0)
    assert wire.effective_ampacity_a(eff) == pytest.approx(0.5 * wire.ampacity_a)


def test_insulation_degradation_lowers_rating():
    wire = Wire(WireSpec(wire_type="cu-12-thhn90", length_m=1.0))
    eff = accumulate([InsulationDegradation(rating_drop_c=25.0)], wire, 0.0)
    assert wire.effective_temp_rating_c(eff) == pytest.approx(wire.temp_rating_c - 25.0)


def test_ground_fault_injects_current():
    eff = accumulate([GroundFault(leakage_a=2.0)], None, 0.0)
    assert eff.extra_current_a == pytest.approx(2.0)


def test_faults_are_windowed():
    f = ContactResistance(added_ohm=0.01, start_s=100.0, end_s=200.0)
    assert accumulate([f], None, 50.0).extra_resistance_ohm == 0.0
    assert accumulate([f], None, 150.0).extra_resistance_ohm == pytest.approx(0.01)
    assert accumulate([f], None, 250.0).extra_resistance_ohm == 0.0


# -- telemetry -------------------------------------------------------------
def test_telemetry_roundtrips():
    wire = Wire(WireSpec(wire_type="cu-12-thhn90", length_m=2.0))
    wire.step(20.0, 1.0)
    t = snapshot(wire, 1.0, 20.0)
    assert isinstance(t, WireTelemetry)
    assert WireTelemetry.from_dict(t.to_dict()) == t


def test_telemetry_over_flags():
    wire = Wire(WireSpec(awg=14, insulation="THHN-90", length_m=1.0))
    wire.step(40.0, 1.0)
    t = snapshot(wire, 1.0, 40.0)
    assert t.over_ampacity  # 40 A on a 20 A wire


# -- network ---------------------------------------------------------------
def test_network_requires_a_source():
    net = WireNetwork()
    net.add_node("a")
    net.add_node("b", load_a=5.0)
    net.add_segment("s", "a", "b", WireSpec(awg=12, length_m=1.0))
    with pytest.raises(ValueError):
        net.solve()


def test_network_two_node_run_is_self_consistent():
    net = WireNetwork()
    net.add_node("src", voltage=48.0)
    net.add_node("load", load_a=10.0)
    net.add_segment("run", "src", "load", WireSpec(awg=10, length_m=3.0))
    res = net.solve()
    seg = res.segments[0]
    # Current equals the load; drop is consistent; load node sits below source.
    assert seg.current_a == pytest.approx(10.0, abs=1e-6)
    # Reported fields are independently rounded, so allow a small tolerance.
    assert seg.voltage_drop_v == pytest.approx(seg.current_a * seg.resistance_ohm, abs=1e-4)
    assert res.node_voltages["load"] == pytest.approx(48.0 - seg.voltage_drop_v, abs=1e-4)


def test_network_branch_conserves_current_and_drops_monotonically():
    net = WireNetwork()
    net.add_node("source", voltage=12.0)
    net.add_node("junction", load_a=8.0)
    net.add_node("end", load_a=6.0)
    net.add_segment("trunk", "source", "junction", WireSpec(awg=10, length_m=5.0))
    net.add_segment("branch", "junction", "end", WireSpec(awg=12, length_m=8.0))
    res = net.solve()
    by_id = {s.id: s for s in res.segments}
    # KCL: trunk feeds both loads (14 A), branch feeds the end load (6 A).
    assert by_id["trunk"].current_a == pytest.approx(14.0, abs=1e-6)
    assert by_id["branch"].current_a == pytest.approx(6.0, abs=1e-6)
    v = res.node_voltages
    assert v["source"] > v["junction"] > v["end"]
    assert res.total_loss_w > 0.0


def test_network_flags_overloaded_segment():
    net = WireNetwork()
    net.add_node("src", voltage=48.0)
    net.add_node("load", load_a=40.0)
    net.add_segment("run", "src", "load", WireSpec(awg=14, insulation="THHN-90", length_m=1.0))
    res = net.solve()
    assert not res.ok
    assert res.segments[0].over_ampacity


# -- declarative builders --------------------------------------------------
def test_build_wire_from_dict():
    spec = build_wire({"material": "copper", "awg": 10, "length_m": 4.0, "bogus": 1})
    wire = Wire(spec)
    assert wire.area_mm2 == pytest.approx(awg_area_mm2(10), abs=0.01)


def test_build_network_from_dict():
    net = build_network({
        "nodes": [{"id": "s", "voltage": 24.0}, {"id": "l", "load_a": 5.0}],
        "segments": [{"id": "run", "from": "s", "to": "l", "wire": {"awg": 12, "length_m": 2.0}}],
    })
    res = net.solve()
    assert res.segments[0].current_a == pytest.approx(5.0, abs=1e-6)


def test_catalog_options_shape():
    opts = catalog_options()
    assert "copper" in opts["materials"]
    assert "THHN-90" in opts["insulations"]
    assert len(opts["wire_types"]) == len(list_wire_types())


def test_fault_effect_zeros_is_identity():
    z = FaultEffect.zeros()
    assert z.resistance_mult == 1.0 and z.ampacity_mult == 1.0
    assert z.extra_resistance_ohm == 0.0 and z.extra_current_a == 0.0
