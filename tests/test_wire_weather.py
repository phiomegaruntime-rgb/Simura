"""Tests for weather coupling in the wire simulator (simura.wires.environment).

Mirrors the battery weather tests: the three environmental levers (ambient air
temperature, wind cooling, solar heating) each move the conductor temperature in
the physically correct direction, and a weather-driven run records the conditions
on its telemetry.
"""

from __future__ import annotations

import pytest

from simura.wires import (
    ConstantCurrent,
    Wire,
    WireEnvironmentCoupling,
    WireSimConfig,
    WireSimulator,
    WireSpec,
    apply_weather_to_effect,
    evaluate_run,
    recommend_gauge,
)
from simura.wires.faults import FaultEffect
from simura.weather import StaticProvider, SyntheticProvider


def _sample(air_temp_c, wind_speed_ms=0.0, solar_w_m2=0.0):
    return StaticProvider(air_temp_c=air_temp_c, wind_speed_ms=wind_speed_ms, solar_w_m2=solar_w_m2).at(0)

# A fixed epoch so any weather query is deterministic.
EPOCH = 1_704_110_400.0  # 2024-01-01 12:00 UTC


def _settle_temp(current_a=25.0, ambient_c=25.0, weather=None, duration_s=2000.0):
    """Run a 14 AWG conductor to (near) steady state and return its final temp."""
    sim = WireSimulator(
        spec=WireSpec(awg=14, length_m=5.0, insulation="THHN-90", ambient_temp_c=ambient_c),
        sim_config=WireSimConfig(dt_s=1.0, duration_s=duration_s),
        profile=ConstantCurrent(current_a),
        weather=weather,
        weather_epoch0=EPOCH,
    )
    return sim.run_to_list()[-1].temp_c


def test_coupling_maps_the_three_levers():
    env = WireEnvironmentCoupling().apply(
        StaticProvider(air_temp_c=30.0, wind_speed_ms=5.0, solar_w_m2=800.0).at(EPOCH),
        projected_area_m2=0.01,
    )
    assert env.ambient_c == pytest.approx(30.0)
    assert env.cooling_mult > 1.0          # wind boosts convective cooling
    assert env.solar_heat_w > 0.0          # sun adds heat


def test_no_wind_no_solar_is_identity():
    env = WireEnvironmentCoupling().apply(
        StaticProvider(air_temp_c=20.0, wind_speed_ms=0.0, solar_w_m2=0.0).at(EPOCH),
        projected_area_m2=0.01,
    )
    assert env.cooling_mult == pytest.approx(1.0)
    assert env.solar_heat_w == pytest.approx(0.0)


def test_apply_to_effect_rides_existing_channels():
    effect = FaultEffect.zeros()
    env = WireEnvironmentCoupling().apply(
        StaticProvider(air_temp_c=25.0, wind_speed_ms=10.0, solar_w_m2=1000.0).at(EPOCH),
        projected_area_m2=0.02,
    )
    apply_weather_to_effect(effect, env)
    assert effect.cooling_mult > 1.0
    assert effect.extra_heat_w > 0.0


def test_hotter_ambient_runs_hotter():
    cool_day = _settle_temp(weather=StaticProvider(air_temp_c=10.0, wind_speed_ms=0.0, solar_w_m2=0.0))
    hot_day = _settle_temp(weather=StaticProvider(air_temp_c=40.0, wind_speed_ms=0.0, solar_w_m2=0.0))
    assert hot_day > cool_day
    # A 30 °C ambient shift is a *floor* on the conductor's temperature rise:
    # resistance climbs with temperature, so the hotter run dissipates more and
    # the gap is amplified beyond the raw ambient difference.
    assert hot_day - cool_day >= 30.0


def test_wind_cools_the_conductor():
    still = _settle_temp(weather=StaticProvider(air_temp_c=25.0, wind_speed_ms=0.0, solar_w_m2=0.0))
    windy = _settle_temp(weather=StaticProvider(air_temp_c=25.0, wind_speed_ms=8.0, solar_w_m2=0.0))
    assert windy < still


def test_sun_heats_the_conductor_at_zero_current():
    # No current, so any rise above ambient is purely absorbed sunlight.
    shade = _settle_temp(current_a=0.0, weather=StaticProvider(air_temp_c=25.0, wind_speed_ms=0.0, solar_w_m2=0.0))
    sun = _settle_temp(current_a=0.0, weather=StaticProvider(air_temp_c=25.0, wind_speed_ms=0.0, solar_w_m2=1000.0))
    assert shade == pytest.approx(25.0, abs=0.5)
    assert sun > shade


def test_weather_run_records_conditions_on_telemetry():
    sim = WireSimulator(
        spec=WireSpec(awg=10, length_m=3.0),
        sim_config=WireSimConfig(dt_s=10.0, duration_s=120.0),
        profile=ConstantCurrent(20.0),
        weather=SyntheticProvider(mean_temp_c=22.0, solar_peak_w_m2=800.0),
        weather_epoch0=EPOCH,
    )
    frames = sim.run_to_list()
    assert frames[0].weather is not None
    assert "air_temp_c" in frames[0].weather
    assert "wind_speed_ms" in frames[0].weather


def test_no_weather_leaves_telemetry_weather_none():
    sim = WireSimulator(
        spec=WireSpec(awg=10, length_m=3.0),
        sim_config=WireSimConfig(dt_s=10.0, duration_s=30.0),
        profile=ConstantCurrent(20.0),
    )
    assert sim.run_to_list()[0].weather is None


def test_cooling_mult_channel_lowers_steady_state_temp():
    # Directly: doubling the cooling conductance nearly halves the temp rise.
    wire = Wire(WireSpec(awg=14, length_m=5.0, ambient_temp_c=25.0))
    base = FaultEffect.zeros()
    windy = FaultEffect(cooling_mult=2.0)
    for _ in range(4000):
        wire.step(30.0, 1.0, effect=base)
    hot = wire.temp_c
    wire2 = Wire(WireSpec(awg=14, length_m=5.0, ambient_temp_c=25.0))
    for _ in range(4000):
        wire2.step(30.0, 1.0, effect=windy)
    cool = wire2.temp_c
    assert (cool - 25.0) < (hot - 25.0)


# --- weather in the planner (evaluate_run / recommend_gauge) ---------------


def test_planner_hot_ambient_derates_ampacity():
    spec = WireSpec(wire_type="cu-12-thhn90", length_m=20)
    cool = evaluate_run(spec, current_a=20, system_voltage_v=48, weather=_sample(20))
    hot = evaluate_run(spec, current_a=20, system_voltage_v=48, weather=_sample(50))
    assert hot.ampacity_a < cool.ampacity_a          # less headroom to the rating
    assert hot.ampacity_utilization > cool.ampacity_utilization
    assert hot.ambient_temp_c == 50.0


def test_planner_cold_day_uprates_ampacity():
    spec = WireSpec(wire_type="cu-12-thhn90", length_m=20)
    nominal = evaluate_run(spec, current_a=20, system_voltage_v=48)          # no weather
    cold = evaluate_run(spec, current_a=20, system_voltage_v=48, weather=_sample(0))
    # Below the 30 C reference ambient there is more headroom, so ampacity rises.
    assert cold.ampacity_a > nominal.ampacity_a
    assert nominal.ambient_temp_c is None


def test_planner_wind_cools_temp_but_not_the_derated_ampacity():
    spec = WireSpec(wire_type="cu-12-thhn90", length_m=20)
    still = evaluate_run(spec, current_a=22, system_voltage_v=48, weather=_sample(45, wind_speed_ms=0))
    windy = evaluate_run(spec, current_a=22, system_voltage_v=48, weather=_sample(45, wind_speed_ms=8))
    assert windy.steady_state_temp_c < still.steady_state_temp_c   # wind cools the conductor
    # Ampacity derating is ambient-only (conservative), so it does not change.
    assert windy.ampacity_a == pytest.approx(still.ampacity_a)


def test_planner_solar_raises_conductor_temp():
    spec = WireSpec(wire_type="cu-10-thhn90", length_m=10)
    shade = evaluate_run(spec, current_a=25, weather=_sample(30, solar_w_m2=0))
    sun = evaluate_run(spec, current_a=25, weather=_sample(30, solar_w_m2=1000))
    assert sun.steady_state_temp_c > shade.steady_state_temp_c


def test_planner_ambient_at_rating_leaves_no_capacity():
    spec = WireSpec(wire_type="cu-12-thhn90", length_m=20)  # THHN-90 -> 90 C rating
    a = evaluate_run(spec, current_a=5, weather=_sample(90))
    assert a.ampacity_a == 0.0
    assert any("no usable ampacity" in p for p in a.problems)


def test_recommend_sizes_up_on_a_hot_day():
    cool = recommend_gauge(current_a=50, length_m=2, system_voltage_v=48,
                           max_drop_pct=10, round_trip=True, weather=_sample(10))
    hot = recommend_gauge(current_a=50, length_m=2, system_voltage_v=48,
                          max_drop_pct=10, round_trip=True, weather=_sample(45))
    assert cool.ok and hot.ok
    # The hot day derates ampacity, forcing a heavier (larger-area) conductor.
    assert hot.wire_type.area_mm2 > cool.wire_type.area_mm2
