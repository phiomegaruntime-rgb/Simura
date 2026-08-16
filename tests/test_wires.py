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
    build_fault,
    build_network,
    build_wire,
    catalog_options,
    evaluate_run,
    list_wire_types,
    material_for,
    recommend_gauge,
    wire_type_for,
)
from simura.weather import WeatherSample
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


def test_network_rejects_paralleled_sources_of_different_voltage():
    """Two packs on one bus is a circuit with no answer -- say which two, and why.

    Ideal sources have no internal impedance here, so only the copper limits the
    current between them. Left to the solver this becomes a runaway that cooks a
    conductor until its resistance overflows and the matrix goes singular, and the
    reported error then blames a disconnected node that was never disconnected.
    """
    net = WireNetwork()
    net.add_node("lfp+", voltage=51.2)
    net.add_node("nmc+", voltage=44.4)
    net.add_node("bus")
    net.add_node("lamp", load_a=2.0)
    net.add_segment("t1", "lfp+", "bus", WireSpec(awg=2, length_m=4.0))
    net.add_segment("t2", "nmc+", "bus", WireSpec(awg=4, length_m=4.0))
    net.add_segment("b1", "bus", "lamp", WireSpec(awg=10, length_m=5.0))

    with pytest.raises(ValueError) as excinfo:
        net.solve()
    message = str(excinfo.value)
    # It must name both offenders and their voltages -- that is the whole point.
    assert "lfp+" in message and "nmc+" in message
    assert "51.20" in message and "44.40" in message
    assert "singular" not in message


def test_network_allows_paralleled_sources_that_agree():
    """The same topology is fine -- and genuinely useful -- when the sources match."""
    net = WireNetwork()
    net.add_node("a+", voltage=51.2)
    net.add_node("b+", voltage=51.2)
    net.add_node("bus")
    net.add_node("lamp", load_a=2.0)
    net.add_segment("t1", "a+", "bus", WireSpec(awg=2, length_m=4.0))
    net.add_segment("t2", "b+", "bus", WireSpec(awg=2, length_m=4.0))
    net.add_segment("b1", "bus", "lamp", WireSpec(awg=10, length_m=5.0))

    res = net.solve()
    by_id = {s.id: s for s in res.segments}
    # The load is shared between two equal sources over equal cable, so neither
    # trunk carries it alone and nothing circulates between them.
    assert by_id["b1"].current_a == pytest.approx(2.0, abs=1e-6)
    assert by_id["t1"].current_a == pytest.approx(1.0, abs=1e-3)
    assert by_id["t2"].current_a == pytest.approx(1.0, abs=1e-3)


def test_network_names_the_nodes_that_have_no_path_to_a_source():
    """A genuinely stranded corner should be named, not merely called singular."""
    net = WireNetwork()
    net.add_node("src", voltage=48.0)
    net.add_node("load", load_a=3.0)
    net.add_node("orphan_a")
    net.add_node("orphan_b", load_a=1.0)
    net.add_segment("wired", "src", "load", WireSpec(awg=10, length_m=2.0))
    net.add_segment("stranded", "orphan_a", "orphan_b", WireSpec(awg=10, length_m=2.0))

    with pytest.raises(ValueError) as excinfo:
        net.solve()
    message = str(excinfo.value)
    assert "orphan_a" in message and "orphan_b" in message
    assert "no conductive path" in message


def test_paralleled_source_conflicts_ignores_separate_groups():
    """Two sources at different voltages are fine while nothing joins them."""
    net = WireNetwork()
    net.add_node("left+", voltage=51.2)
    net.add_node("left_load", load_a=1.0)
    net.add_node("right+", voltage=24.0)
    net.add_node("right_load", load_a=1.0)
    net.add_segment("l", "left+", "left_load", WireSpec(awg=10, length_m=2.0))
    net.add_segment("r", "right+", "right_load", WireSpec(awg=10, length_m=2.0))

    assert net.paralleled_source_conflicts() == []
    assert net.solve().ok


def test_network_flags_overloaded_segment():
    net = WireNetwork()
    net.add_node("src", voltage=48.0)
    net.add_node("load", load_a=40.0)
    net.add_segment("run", "src", "load", WireSpec(awg=14, insulation="THHN-90", length_m=1.0))
    res = net.solve()
    assert not res.ok
    assert res.segments[0].over_ampacity


# -- faulted networks -------------------------------------------------------
def test_network_contact_resistance_starves_the_load():
    """A loose joint on one segment re-settles the *whole* network."""
    def net(faults):
        n = WireNetwork()
        n.add_node("src", voltage=48.0)
        n.add_node("load", load_a=20.0)
        n.add_segment("run", "src", "load", WireSpec(awg=10, length_m=3.0), faults=faults)
        return n.solve()

    clean = net([])
    bad = net([ContactResistance(added_ohm=0.05)])
    seg_c, seg_b = clean.segments[0], bad.segments[0]
    # The joint adds series resistance: more drop, more loss, a hotter run, and a
    # load node that sits measurably lower than it did on the clean network.
    assert seg_b.resistance_ohm > seg_c.resistance_ohm
    assert seg_b.voltage_drop_v > seg_c.voltage_drop_v
    assert seg_b.power_loss_w > seg_c.power_loss_w
    assert seg_b.temp_c > seg_c.temp_c
    assert bad.node_voltages["load"] < clean.node_voltages["load"]
    assert seg_b.faulted and not seg_c.faulted


def test_network_conductor_damage_derates_ampacity_into_an_overload():
    """Losing cross-section can push an otherwise fine run over its rating."""
    def net(faults):
        n = WireNetwork()
        n.add_node("src", voltage=48.0)
        n.add_node("load", load_a=25.0)
        n.add_segment("run", "src", "load", WireSpec(awg=10, insulation="THHN-90"), faults=faults)
        return n.solve()

    clean, bad = net([]), net([ConductorDamage(area_loss_frac=0.5)])
    assert not clean.segments[0].over_ampacity
    assert bad.segments[0].ampacity_a < clean.segments[0].ampacity_a
    assert bad.segments[0].over_ampacity and not bad.ok


def test_network_insulation_degradation_lowers_only_the_rating():
    """Aged insulation changes what counts as too hot, not the physics."""
    def net(faults):
        n = WireNetwork()
        n.add_node("src", voltage=12.0)
        n.add_node("load", load_a=16.0)
        n.add_segment(
            "run", "src", "load",
            WireSpec(awg=12, insulation="THHN-90", length_m=6.0), faults=faults,
        )
        return n.solve()

    # The clean run settles around 47 C -- comfortably inside a 90 C rating, but
    # over the 40 C an aged insulation can still tolerate.
    clean = net([]).segments[0]
    aged = net([InsulationDegradation(rating_drop_c=50.0)]).segments[0]
    assert aged.temp_c == pytest.approx(clean.temp_c, abs=1e-6)   # same operating point
    assert aged.temp_rating_c == pytest.approx(clean.temp_rating_c - 50.0)
    assert aged.over_temp and not clean.over_temp


def test_network_ground_fault_leaks_current_past_the_load():
    """A leak is carried by the faulted segment but never reaches the load."""
    net = WireNetwork()
    net.add_node("src", voltage=48.0)
    net.add_node("load", load_a=10.0)
    net.add_segment(
        "run", "src", "load", WireSpec(awg=10, length_m=2.0), faults=[GroundFault(leakage_a=4.0)]
    )
    res = net.solve()
    seg = res.segments[0]
    assert seg.current_a == pytest.approx(14.0, abs=1e-6)  # 10 A load + 4 A to ground
    assert seg.leakage_a == pytest.approx(4.0)


def test_network_resistance_growth_develops_with_elapsed_time():
    """Corrosion is progressive: the same network is worse an hour later."""
    def solve_at(elapsed_s):
        n = WireNetwork()
        n.add_node("src", voltage=48.0)
        n.add_node("load", load_a=15.0)
        n.add_segment(
            "run", "src", "load", WireSpec(awg=10, length_m=3.0),
            faults=[ResistanceGrowth(rate_per_s=1e-4, max_mult=3.0)],
        )
        return n.solve(elapsed_s=elapsed_s).segments[0]

    fresh, hour = solve_at(0.0), solve_at(3600.0)
    assert hour.resistance_ohm > fresh.resistance_ohm
    assert hour.power_loss_w > fresh.power_loss_w


def test_unfaulted_network_is_unchanged_by_the_fault_machinery():
    """The clean path must give exactly what it gave before faults existed."""
    net = WireNetwork()
    net.add_node("src", voltage=24.0)
    net.add_node("load", load_a=12.0)
    net.add_segment("run", "src", "load", WireSpec(awg=10, length_m=4.0))
    seg = net.solve().segments[0]
    wire = Wire(WireSpec(awg=10, length_m=4.0))
    # Reported fields are independently rounded, hence the loose tolerance.
    assert seg.resistance_ohm == pytest.approx(wire.resistance_ohm(seg.temp_c), rel=1e-4)
    assert seg.ampacity_a == pytest.approx(wire.ampacity_a, rel=1e-6)
    assert seg.leakage_a == 0.0 and not seg.faulted


def test_build_fault_from_dict_and_unknown_type():
    f = build_fault({"type": "contact_resistance", "added_ohm": 0.02})
    assert isinstance(f, ContactResistance) and f.added_ohm == pytest.approx(0.02)
    assert isinstance(build_fault({"type": "ground_fault"}), GroundFault)
    with pytest.raises(ValueError, match="unknown wire fault type"):
        build_fault({"type": "nope"})


def test_build_network_parses_segment_faults():
    net = build_network({
        "nodes": [{"id": "s", "voltage": 48.0}, {"id": "l", "load_a": 10.0}],
        "segments": [{
            "id": "run", "from": "s", "to": "l",
            "wire": {"awg": 10, "length_m": 3.0},
            "faults": [{"type": "contact_resistance", "added_ohm": 0.05}],
        }],
    })
    seg = net.solve().segments[0]
    assert seg.faulted
    assert seg.resistance_ohm > 0.05  # the joint dominates a 3 m run of AWG 10


# -- weather-driven networks ------------------------------------------------
def _weather(air_temp_c, wind_speed_ms=0.0, solar_w_m2=0.0):
    return WeatherSample(
        timestamp=0.0,
        air_temp_c=air_temp_c,
        wind_speed_ms=wind_speed_ms,
        solar_w_m2=solar_w_m2,
        source="test",
    )


def _run(weather=None, load_a=30.0):
    net = WireNetwork()
    net.add_node("src", voltage=48.0)
    net.add_node("load", load_a=load_a)
    net.add_segment("run", "src", "load", WireSpec(awg=10, insulation="THHN-90", length_m=8.0))
    return net.solve(weather=weather).segments[0]


def test_network_hot_day_costs_voltage_and_headroom():
    """A hot still day is worse at both ends: hotter copper, less rating."""
    cold = _run(_weather(0.0))
    hot = _run(_weather(40.0))
    # Resistance rises with temperature, so the far end really does sit lower.
    assert hot.temp_c > cold.temp_c
    assert hot.resistance_ohm > cold.resistance_ohm
    assert hot.voltage_drop_v > cold.voltage_drop_v
    assert hot.power_loss_w > cold.power_loss_w
    # And the rating falls: less headroom to the insulation limit.
    assert hot.ampacity_a < cold.ampacity_a


def test_network_wind_cools_the_run_without_crediting_its_rating():
    """Wind shows up in the temperature only -- the conservative convention."""
    still = _run(_weather(30.0))
    windy = _run(_weather(30.0, wind_speed_ms=8.0))
    assert windy.temp_c < still.temp_c
    assert windy.ampacity_a == pytest.approx(still.ampacity_a)


def test_network_sun_heats_an_idle_run():
    """Absorbed sunlight warms a conductor carrying almost nothing."""
    shade = _run(_weather(25.0), load_a=0.5)
    sun = _run(_weather(25.0, solar_w_m2=1000.0), load_a=0.5)
    assert sun.temp_c > shade.temp_c


def test_network_without_weather_is_unchanged():
    """The no-weather path must give exactly what it gave before."""
    plain = _run(None)
    # The spec's own ambient (25 C default) and the catalog rating, untouched.
    assert plain.ampacity_a == pytest.approx(Wire(WireSpec(awg=10, insulation="THHN-90")).ampacity_a)
    assert plain.temp_c > 25.0  # self-heating only


def test_network_weather_and_faults_compose():
    """A hot day on top of a nicked conductor is worse than either alone."""
    def seg(weather, faults):
        net = WireNetwork()
        net.add_node("src", voltage=48.0)
        net.add_node("load", load_a=25.0)
        net.add_segment(
            "run", "src", "load",
            WireSpec(awg=10, insulation="THHN-90", length_m=8.0), faults=faults,
        )
        return net.solve(weather=weather).segments[0]

    clean_cool = seg(_weather(10.0), [])
    damaged_hot = seg(_weather(40.0), [ConductorDamage(area_loss_frac=0.4)])
    assert damaged_hot.temp_c > clean_cool.temp_c
    assert damaged_hot.ampacity_a < clean_cool.ampacity_a
    assert damaged_hot.over_ampacity and not clean_cool.over_ampacity


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
