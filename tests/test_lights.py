"""Tests for the lights library. Fully offline and deterministic.

Covers the spectral core (Planck, the CIE observer, luminous efficacy of
radiation, correlated colour temperature), the catalog, the three families'
electro-thermal models, fault injection, photometry, the planner, and the layout
solve.

The interesting tests here are the *emergent* ones. Nothing in the code says a
dimmed filament goes orange, or that a cold fluorescent tube is a dim one, or
that warm-white LEDs are less efficacious than cool-white ones. Those all fall
out of the spectrum, and each one is checked below -- if a refactor breaks the
physics, they are what will notice.
"""

from __future__ import annotations

import json
import math

import pytest

from simura.lights import (
    Burnout,
    ConstantDrive,
    DaylightHarvesting,
    Flicker,
    HeatsinkLoss,
    Layout,
    Light,
    LightEnvironmentCoupling,
    LightSimConfig,
    LightSimulator,
    LightSpec,
    LumenDepreciation,
    PhotocellControl,
    Schedule,
    beam_solid_angle_sr,
    blackbody,
    build_fault,
    build_layout,
    build_light,
    build_profile,
    catalog_options,
    clear_sky_ghi_w_m2,
    daylight_illuminance_lux,
    evaluate_installation,
    illuminance_lux,
    lamp_type_for,
    list_lamp_types,
    list_technologies,
    lumen_method,
    luminous_intensity_cd,
    photopic,
    point_illuminance_lux,
    recommend_lamp,
    room_index,
    solar_elevation_deg,
    task_lux,
    technology_for,
    utilisation_factor,
)
from simura.lights.faults import LightFaultEffect, accumulate
from simura.lights.spectrum import (
    K_M,
    SIGMA_SB,
    emission_lines,
    gaussian_band,
    phosphor_led,
    planck_exitance,
    selective_thermal,
    wien_peak_nm,
)
from simura.lights.telemetry import snapshot
from simura.weather import WeatherSample


# -- the CIE observer ------------------------------------------------------
def test_photopic_peaks_at_555nm():
    # V(lambda) is 1.0 at 555 nm by definition -- that is where the candela is fixed.
    assert photopic(555.0) == pytest.approx(1.0, abs=0.01)
    assert photopic(555.0) > photopic(500.0) > photopic(450.0)
    assert photopic(555.0) > photopic(620.0) > photopic(700.0)


def test_photopic_matches_tabulated_values():
    # A handful of the CIE 1931 table, which the analytic fit has to reproduce.
    for nm, expected in [(500.0, 0.323), (600.0, 0.631), (650.0, 0.107)]:
        assert photopic(nm) == pytest.approx(expected, abs=0.02)


# -- Planck's law ----------------------------------------------------------
def test_planck_obeys_wien_displacement():
    # The sun's ~5800 K peaks in the green; a 2800 K filament in the near infrared.
    assert wien_peak_nm(5800.0) == pytest.approx(500.0, abs=10.0)
    assert wien_peak_nm(2800.0) == pytest.approx(1035.0, abs=20.0)


def test_planck_integrates_to_stefan_boltzmann():
    # Integrating the Planck curve over all wavelengths must give sigma*T^4. Only
    # the visible band is on the grid, so this checks the in-band part against a
    # numeric integral of the tail.
    t = 3000.0
    spd = blackbody(t)
    assert spd.radiant_power == pytest.approx(SIGMA_SB * t ** 4, rel=1e-6)
    assert spd.out_of_band_power > spd.in_band_power   # most of it is infrared


def test_blackbody_efficacy_of_radiation_matches_literature():
    # The classic figures: ~15 lm/W for a 2800 K filament, peaking near 95 lm/W
    # around 6600 K. If these drift, the whole photometric chain has moved.
    assert blackbody(2800.0).ler_lm_per_w == pytest.approx(15.0, abs=1.5)
    assert blackbody(6600.0).ler_lm_per_w == pytest.approx(95.0, abs=3.0)
    peak = max(blackbody(t).ler_lm_per_w for t in range(5000, 9000, 200))
    assert 90.0 < peak < 100.0


def test_monochromatic_555nm_approaches_683_lm_per_w():
    # K_M is the luminous efficacy of 555 nm radiation, by definition.
    assert gaussian_band(555.0, 1.0).ler_lm_per_w == pytest.approx(K_M, rel=0.01)


def test_blackbody_cct_reproduces_its_own_temperature():
    for t in (2700.0, 4000.0, 6500.0):
        assert blackbody(t).cct_k() == pytest.approx(t, rel=0.02)


def test_off_locus_source_has_no_colour_temperature():
    # A green laser has a colour, but not the colour of anything hot: its
    # chromaticity is nowhere near the Planckian locus, so a colour *temperature*
    # would be an invention and the model declines to name one.
    assert gaussian_band(532.0, 2.0).cct_k() == 0.0
    # Sodium is the interesting opposite case. It is just as monochromatic, but
    # 589 nm happens to sit close to the locus, which is why the industry really
    # does quote low-pressure sodium at around 1700-1800 K.
    sodium = emission_lines([(589.0, 1.2, 1.0), (589.6, 1.2, 0.9)])
    assert sodium.cct_k() == pytest.approx(1800.0, abs=200.0)


def test_sodium_line_has_enormous_efficacy_and_no_colour_rendering():
    lps = emission_lines([(589.0, 1.2, 1.0), (589.6, 1.2, 0.9)])
    assert lps.ler_lm_per_w > 450.0        # nearly at the eye's peak sensitivity
    assert lps.spectral_coverage() < 0.05  # and radiating nowhere else


def test_selective_emissivity_beats_a_greybody():
    # Tungsten radiates relatively more in the visible than the infrared, which is
    # worth roughly 50% more efficacy than the equivalent blackbody.
    t = 2800.0
    assert selective_thermal(t).ler_lm_per_w > 1.3 * blackbody(t).ler_lm_per_w


def test_planck_exitance_is_zero_below_absolute_zero():
    assert planck_exitance(555.0, 0.0) == 0.0


# -- catalog ---------------------------------------------------------------
def test_catalog_spans_every_family():
    families = {t.family for t in list_technologies()}
    assert families == {"incandescent", "solid_state", "discharge_lp", "discharge_hp"}
    assert len(list_lamp_types()) >= 18


def test_technology_and_lamp_lookup_and_unknown():
    assert technology_for("LED").key == "led"
    assert lamp_type_for("led-9-e27").technology == "led"
    with pytest.raises(ValueError):
        technology_for("candle")
    with pytest.raises(ValueError):
        lamp_type_for("nope")


def test_lamp_filter_by_family():
    solid = list_lamp_types(family="solid_state")
    assert solid and all(technology_for(x.technology).family == "solid_state" for x in solid)


def test_catalog_options_enumerates_a_ui():
    opts = catalog_options()
    for key in ("families", "technologies", "lamp_types", "fault_types",
                "profile_types", "control_types", "tasks"):
        assert opts[key]


# -- whole-lamp physics ----------------------------------------------------
def test_every_catalog_lamp_predicts_its_published_efficacy():
    """The end-to-end check: predicted vs published, across all four families.

    The model never consults the published flux, so this is a real prediction
    spanning a fifteen-fold range of lm/W. A few percent of scatter is expected;
    a big shift means the physics moved.
    """
    errors = []
    for lamp in list_lamp_types():
        light = Light(LightSpec(lamp_type=lamp.id))
        light.time_lit_s = 1e9              # warm-up complete
        point = light.operating_point(1.0, 25.0)
        errors.append(
            (point.efficacy_lm_per_w - lamp.published_efficacy_lm_per_w)
            / lamp.published_efficacy_lm_per_w
        )
    rmse = (sum(e * e for e in errors) / len(errors)) ** 0.5
    assert rmse < 0.10, f"whole-catalog efficacy RMSE drifted to {rmse:.1%}"
    assert abs(sum(errors) / len(errors)) < 0.05      # and no systematic bias


def test_dimming_a_filament_costs_far_more_light_than_power():
    """Emergent: the single most characteristic behaviour of an incandescent lamp."""
    light = Light(LightSpec(lamp_type="inc-60-e27"))
    full = light.operating_point(1.0)
    half = light.operating_point(0.5)

    assert half.input_power_w > 0.3 * full.input_power_w    # power falls slowly
    assert half.luminous_flux_lm < 0.15 * full.luminous_flux_lm   # light collapses
    assert half.efficacy_lm_per_w < 0.4 * full.efficacy_lm_per_w
    # And the light reddens, because the filament is cooler.
    assert half.color_temp_k < full.color_temp_k - 300
    assert half.source_temp_c < full.source_temp_c


def test_hotter_filament_is_more_efficacious():
    # A 100 W lamp runs a hotter filament than a 60 W one, and that -- nothing
    # else -- is why it is the more efficacious of the two.
    small = Light(LightSpec(lamp_type="inc-60-e27")).operating_point(1.0)
    large = Light(LightSpec(lamp_type="inc-100-e27")).operating_point(1.0)
    assert large.source_temp_c > small.source_temp_c
    assert large.efficacy_lm_per_w > small.efficacy_lm_per_w


def test_fluorescent_and_led_derate_in_opposite_directions():
    """Emergent: the reason the technology choice depends on where it is going."""
    def flux_at(lamp_id: str, ambient: float) -> float:
        light = Light(LightSpec(lamp_type=lamp_id))
        light.time_lit_s = 1e9
        return light.operating_point(1.0, ambient).luminous_flux_lm

    t8_cold, t8_warm = flux_at("fl-t8-36", 0.0), flux_at("fl-t8-36", 25.0)
    led_cold, led_warm = flux_at("led-15-e27", 0.0), flux_at("led-15-e27", 25.0)

    assert t8_cold < 0.7 * t8_warm     # a cold fluorescent tube is a dim one
    assert led_cold > led_warm         # a cold LED is a bright one


def test_warm_white_is_less_efficacious_than_cool_white():
    """Emergent: more phosphor, more Stokes loss, more light where the eye is weak."""
    warm = Light(LightSpec(lamp_type="led-9-e27")).operating_point(1.0, 25.0)
    cool = Light(LightSpec(lamp_type="led-15-e27")).operating_point(1.0, 25.0)
    assert warm.color_temp_k < cool.color_temp_k
    assert warm.efficacy_lm_per_w < cool.efficacy_lm_per_w


def test_led_colour_temperature_tracks_its_published_value():
    for lamp_id, expected in [("led-9-e27", 2700), ("led-15-e27", 4000),
                              ("led-100-flood", 5000)]:
        light = Light(LightSpec(lamp_type=lamp_id))
        assert light.operating_point(1.0).color_temp_k == pytest.approx(expected, rel=0.05)


def test_led_junction_runs_hotter_and_dimmer_with_ambient():
    light = Light(LightSpec(lamp_type="led-15-e27"))
    cool = light.operating_point(1.0, 20.0)
    hot = light.operating_point(1.0, 45.0)
    assert hot.source_temp_c > cool.source_temp_c + 20
    assert hot.luminous_flux_lm < cool.luminous_flux_lm


def test_forward_voltage_falls_as_the_junction_heats():
    light = Light(LightSpec(lamp_type="led-15-e27"))
    assert light.forward_voltage_v(0.35, 85.0) < light.forward_voltage_v(0.35, 25.0)


def test_discharge_lamp_warms_up_slowly():
    light = Light(LightSpec(lamp_type="mh-250-e40"))
    assert light.warmup_factor() == 0.0
    light.time_lit_s = 120.0
    partial = light.warmup_factor()
    light.time_lit_s = 1e9
    assert 0.0 < partial < 0.7 < light.warmup_factor() <= 1.0


def test_hot_hid_lamp_will_not_restrike():
    light = Light(LightSpec(lamp_type="mh-250-e40"))
    light.lit = False
    light.time_dark_s = 10.0
    assert not light.can_strike()               # still hot
    assert light.operating_point(1.0).luminous_flux_lm == 0.0
    light.time_dark_s = 1e9
    assert light.can_strike()


def test_led_restrikes_instantly():
    light = Light(LightSpec(lamp_type="led-9-e27"))
    light.time_dark_s = 0.0
    assert light.can_strike()


def test_non_dimmable_lamp_refuses_partial_drive():
    light = Light(LightSpec(lamp_type="lps-135-bx"))
    light.time_lit_s = 1e9
    assert not light.tech.dimmable
    half = light.operating_point(0.5)
    full = light.operating_point(1.0)
    # It either runs or it does not; there is no half output.
    assert half.luminous_flux_lm in (0.0, pytest.approx(full.luminous_flux_lm))


def test_lumen_depreciation_follows_the_l70_rating():
    tech = technology_for("led")
    aged = Light(LightSpec(lamp_type="led-9-e27", operating_hours_h=tech.l70_h))
    assert aged.lumen_maintenance() == pytest.approx(0.7, abs=0.01)


def test_switch_cycles_wear_out_a_fluorescent_lamp_but_not_an_led():
    cfl = Light(LightSpec(lamp_type="cfl-15-e27", switch_cycles=2000))
    led = Light(LightSpec(lamp_type="led-9-e27", switch_cycles=2000))
    assert cfl.lumen_maintenance() < 0.85
    assert led.lumen_maintenance() == pytest.approx(1.0, abs=1e-9)


def test_a_light_needs_positive_power():
    with pytest.raises(ValueError):
        Light(LightSpec(technology="led", power_w=0.0))


# -- faults ----------------------------------------------------------------
def test_no_faults_is_the_identity():
    effect = accumulate([], None, 0.0)
    assert effect == LightFaultEffect.zeros()


def test_burnout_puts_the_lamp_out():
    light = Light(LightSpec(lamp_type="led-9-e27"))
    effect = accumulate([Burnout(start_s=10.0)], light, 20.0)
    assert effect.failed
    assert light.operating_point(1.0, 25.0, effect).luminous_flux_lm == 0.0


def test_faults_are_inactive_outside_their_window():
    light = Light(LightSpec(lamp_type="led-9-e27"))
    assert not accumulate([Burnout(start_s=10.0, end_s=20.0)], light, 5.0).failed
    assert not accumulate([Burnout(start_s=10.0, end_s=20.0)], light, 25.0).failed


def test_heatsink_loss_cooks_the_junction_and_dims_the_lamp():
    light = Light(LightSpec(lamp_type="led-100-flood"))
    healthy = light.operating_point(1.0, 25.0)
    effect = accumulate([HeatsinkLoss(r_th_mult=3.0)], light, 0.0)
    broken = light.operating_point(1.0, 25.0, effect)
    assert broken.source_temp_c > healthy.source_temp_c + 40
    assert broken.luminous_flux_lm < healthy.luminous_flux_lm


def test_lumen_depreciation_fault_compounds_over_time():
    light = Light(LightSpec(lamp_type="fl-t8-36"))
    fault = LumenDepreciation(rate_per_h=1e-3)
    early = accumulate([fault], light, 3600.0).flux_mult
    late = accumulate([fault], light, 360000.0).flux_mult
    assert late < early < 1.0


def test_flicker_modulates_output_without_changing_power():
    light = Light(LightSpec(lamp_type="fl-t8-36"))
    light.time_lit_s = 1e9
    fault = Flicker(depth=0.6, freq_hz=10.0)
    fluxes = [
        light.operating_point(1.0, 25.0, accumulate([fault], light, t / 100.0)).luminous_flux_lm
        for t in range(40)
    ]
    assert max(fluxes) > min(fluxes) * 1.5      # it visibly swings


def test_faults_compose():
    light = Light(LightSpec(lamp_type="led-9-e27"))
    effect = accumulate([HeatsinkLoss(r_th_mult=2.0), LumenDepreciation(rate_per_h=1e-3)],
                        light, 36000.0)
    assert effect.thermal_resistance_mult == pytest.approx(2.0)
    assert effect.flux_mult < 1.0


def test_build_fault_covers_every_declared_type():
    for fault_type in catalog_options()["fault_types"]:
        assert build_fault({"type": fault_type, "start_s": 1.0}) is not None
    with pytest.raises(ValueError):
        build_fault({"type": "gremlins"})


# -- photometry ------------------------------------------------------------
def test_solid_angle_of_a_full_sphere():
    assert beam_solid_angle_sr(360.0) == pytest.approx(4.0 * math.pi)
    assert beam_solid_angle_sr(180.0) == pytest.approx(2.0 * math.pi)


def test_narrow_beam_concentrates_intensity():
    spot = luminous_intensity_cd(1000.0, 30.0)
    flood = luminous_intensity_cd(1000.0, 360.0)
    assert spot > 10 * flood        # the entire reason optics exist


def test_illuminance_obeys_the_inverse_square_law():
    near = illuminance_lux(1000.0, 2.0)
    far = illuminance_lux(1000.0, 4.0)
    assert far == pytest.approx(near / 4.0)


def test_illuminance_falls_off_the_beam_axis():
    on_axis = point_illuminance_lux(1000.0, 360.0, 3.0, 0.0)
    off_axis = point_illuminance_lux(1000.0, 360.0, 3.0, 3.0)
    assert 0 < off_axis < on_axis
    # Outside a narrow beam there is nothing at all.
    assert point_illuminance_lux(1000.0, 20.0, 3.0, 3.0) == 0.0


def test_room_index_and_utilisation_factor_behave():
    wide = room_index(20.0, 20.0, 2.0)
    narrow = room_index(4.0, 4.0, 3.0)
    assert wide > narrow
    assert utilisation_factor(wide) > utilisation_factor(narrow)
    # Lighter surfaces return more of the light that misses first time.
    assert utilisation_factor(2.0, 0.8, 0.7) > utilisation_factor(2.0, 0.3, 0.2)


def test_lumen_method_scales_with_flux_and_area():
    one = lumen_method(2000.0, 4, 8.0, 6.0, 2.5, 20.0)
    two = lumen_method(2000.0, 8, 8.0, 6.0, 2.5, 20.0)
    # Reported values are rounded for transport, so compare at that precision.
    assert two.average_lux == pytest.approx(2 * one.average_lux, rel=1e-3)
    assert two.power_density_w_per_m2 == pytest.approx(2 * one.power_density_w_per_m2, rel=1e-3)


def test_task_lux_lookup():
    assert task_lux("office") == 500.0
    assert task_lux("corridor") < task_lux("office") < task_lux("surgery")
    with pytest.raises(ValueError):
        task_lux("nightclub")


# -- planning --------------------------------------------------------------
def test_evaluate_installation_flags_an_under_lit_room():
    a = evaluate_installation(
        LightSpec(lamp_type="led-9-e27"), n_luminaires=2,
        length_m=10.0, width_m=8.0, task="office",
    )
    assert not a.ok
    assert any("under-lit" in p for p in a.problems)


def test_evaluate_installation_passes_a_good_design():
    rec = recommend_lamp(length_m=12.0, width_m=10.0, mounting_height_m=2.5, task="office")
    assert rec.ok and rec.lamp_type is not None
    assert rec.assessment is not None and rec.assessment.ok


def test_ageing_a_design_lowers_its_maintained_illuminance():
    spec = LightSpec(lamp_type="fl-t8-36")
    new = evaluate_installation(spec, 12, 10.0, 8.0, task="office", maintenance_hours=0.0)
    old = evaluate_installation(spec, 12, 10.0, 8.0, task="office", maintenance_hours=15000.0)
    assert old.maintained_lux < new.maintained_lux
    assert old.initial_lux == pytest.approx(new.initial_lux, rel=1e-6)


def test_low_cri_lamp_is_rejected_for_a_task_that_needs_colour():
    a = evaluate_installation(
        LightSpec(lamp_type="hps-150-e40"), n_luminaires=2,
        length_m=8.0, width_m=6.0, task="office",
    )
    assert any("colour rendering" in p for p in a.problems)


def test_recommend_restricted_to_a_family():
    rec = recommend_lamp(
        length_m=40.0, width_m=12.0, mounting_height_m=8.0,
        task="street_main", family="discharge_hp",
    )
    assert rec.lamp_type is not None
    assert technology_for(rec.lamp_type.technology).family == "discharge_hp"


def test_recommendation_alternatives_are_ranked_by_power():
    rec = recommend_lamp(length_m=12.0, width_m=10.0, mounting_height_m=2.5, task="office")
    powers = [alt["power_w"] for alt in rec.alternatives]
    assert powers == sorted(powers)


def test_weather_moves_a_fluorescent_design_the_wrong_way():
    spec = LightSpec(lamp_type="fl-t8-36")
    cold = WeatherSample(timestamp=0.0, air_temp_c=-5.0, source="test")
    warm = evaluate_installation(spec, 16, 10.0, 8.0, task="office")
    chilly = evaluate_installation(spec, 16, 10.0, 8.0, task="office", weather=cold)
    assert chilly.maintained_lux < warm.maintained_lux
    assert chilly.ambient_temp_c == pytest.approx(-5.0, abs=1.0)


# -- layout ----------------------------------------------------------------
def test_layout_grid_is_even_and_meets_its_target():
    # Twelve 1500 lm lamps over 80 m^2 is domestic-grade light, not office-grade:
    # ~150 lux. Checked against a target it can actually meet.
    layout = Layout(length_m=10.0, width_m=8.0, grid_n=7)
    layout.grid_regular(3, 4, 3.0, LightSpec(lamp_type="led-15-e27"))
    result = layout.solve(target_lux=120.0, min_uniformity=0.5)
    assert result.average_lux > 120.0
    assert result.uniformity > 0.5
    assert len(result.luminaires) == 12
    assert len(result.grid) == 7 and len(result.grid[0]) == 7


def test_spreading_luminaires_further_apart_hurts_uniformity():
    def uniformity(cols: int) -> float:
        layout = Layout(length_m=20.0, width_m=4.0, grid_n=11)
        layout.grid_regular(1, cols, 3.0, LightSpec(lamp_type="led-100-flood"))
        return layout.solve(include_interreflection=False).uniformity

    assert uniformity(2) < uniformity(6)


def test_a_failed_luminaire_shows_up_in_the_layout():
    layout = Layout(length_m=8.0, width_m=6.0, grid_n=5)
    layout.grid_regular(2, 2, 3.0, LightSpec(lamp_type="led-15-e27"))
    layout.add("dead", 6.0, 4.5, 3.0, LightSpec(lamp_type="led-15-e27"),
               faults=[Burnout()])
    result = layout.solve()
    assert any("not lit" in p for p in result.problems)
    assert not next(lum for lum in result.luminaires if lum.id == "dead").lit


def test_interreflection_raises_the_average_but_not_the_shape():
    layout = Layout(length_m=10.0, width_m=8.0, grid_n=7)
    layout.grid_regular(3, 4, 3.0, LightSpec(lamp_type="led-15-e27"))
    direct = layout.solve(include_interreflection=False)
    total = layout.solve(include_interreflection=True)
    assert total.average_lux > direct.average_lux
    assert total.uniformity > direct.uniformity      # bounced light is uniform
    assert total.indirect_lux > 0


def test_build_layout_from_a_dict():
    layout = build_layout({
        "length_m": 8.0,
        "width_m": 6.0,
        "grid": {"rows": 2, "cols": 2, "height_m": 3.0, "lamp": {"lamp_type": "led-15-e27"}},
        "luminaires": [
            {"id": "extra", "x_m": 4.0, "y_m": 3.0, "height_m": 3.0,
             "lamp": {"lamp_type": "led-9-e27"}, "faults": [{"type": "burnout"}]},
        ],
    })
    result = layout.solve()
    assert len(result.luminaires) == 5
    assert any("not lit" in p for p in result.problems)


def test_layout_needs_a_positive_area():
    with pytest.raises(ValueError):
        Layout(length_m=0.0, width_m=5.0)


# -- profiles, telemetry and the simulator ---------------------------------
def test_schedule_switches_on_and_off():
    profile = Schedule(start_s=0.0, on_s=3600.0, period_s=7200.0)
    assert profile.drive(0.0) == 1.0
    assert profile.drive(1800.0) == 1.0
    assert profile.drive(5400.0) == 0.0
    assert profile.drive(7200.0) == 1.0      # and again next period


def test_build_profile_covers_every_declared_type():
    for profile_type in catalog_options()["profile_types"]:
        assert build_profile({"type": profile_type}) is not None
    with pytest.raises(ValueError):
        build_profile({"type": "morse"})


def test_simulator_yields_one_frame_per_step():
    sim = LightSimulator(
        spec=LightSpec(lamp_type="led-9-e27"),
        sim_config=LightSimConfig(dt_s=1.0, duration_s=30.0, mounting_height_m=2.5),
        profile=ConstantDrive(1.0),
    )
    frames = sim.run_to_list()
    assert len(frames) == 30
    assert frames[-1].time_s == pytest.approx(30.0)
    assert frames[-1].lit and frames[-1].illuminance_lux > 0
    assert frames[-1].operating_hours_h > 0


def test_simulator_needs_a_profile_or_a_control():
    with pytest.raises(ValueError):
        LightSimulator(spec=LightSpec(lamp_type="led-9-e27")).run_to_list()


def test_discharge_lamp_gets_brighter_through_the_run():
    sim = LightSimulator(
        spec=LightSpec(lamp_type="hps-150-e40"),
        sim_config=LightSimConfig(dt_s=30.0, duration_s=900.0),
        profile=ConstantDrive(1.0),
    )
    frames = sim.run_to_list()
    assert frames[0].luminous_flux_lm < frames[-1].luminous_flux_lm
    assert frames[-1].warmup_frac > 0.9


def test_telemetry_round_trips_through_a_dict():
    light = Light(LightSpec(lamp_type="led-9-e27"))
    point = light.operating_point(1.0, 25.0)
    frame = snapshot(light, 1.0, 1.0, point, illuminance_lux=120.0, target_lux=300.0)
    assert frame.below_target
    from simura.lights.telemetry import LightTelemetry

    assert LightTelemetry.from_dict(frame.to_dict()) == frame


# -- weather, daylight and controls ----------------------------------------
def test_solar_elevation_is_higher_at_noon_than_at_midnight():
    # 2024-06-21, London. Epoch seconds for 12:00 and 00:00 UTC.
    noon = 1718971200.0
    assert solar_elevation_deg(51.5, -0.13, noon) > 55.0
    assert solar_elevation_deg(51.5, -0.13, noon - 12 * 3600) < 0.0


def test_solar_elevation_is_opposite_across_the_equator():
    # Midsummer in the north is midwinter in the south.
    noon = 1718971200.0
    north = solar_elevation_deg(51.5, 0.0, noon)
    south = solar_elevation_deg(-51.5, 0.0, noon)
    assert north > south


def test_clear_sky_irradiance_peaks_overhead_and_is_zero_at_night():
    assert clear_sky_ghi_w_m2(-5.0) == 0.0
    assert clear_sky_ghi_w_m2(90.0) > clear_sky_ghi_w_m2(30.0) > clear_sky_ghi_w_m2(10.0)
    assert 900.0 < clear_sky_ghi_w_m2(90.0) < 1100.0     # a plausible clear noon


def test_daylight_illuminance_conversion():
    # Full sun, ~1000 W/m^2, is on the order of 100 klx.
    assert daylight_illuminance_lux(1000.0) == pytest.approx(110000.0, rel=0.01)
    assert daylight_illuminance_lux(1000.0, transmission=0.5) == pytest.approx(55000.0, rel=0.01)


def test_environment_coupling_indoors_ignores_wind_and_sun():
    sample = WeatherSample(timestamp=0.0, air_temp_c=30.0, wind_speed_ms=8.0,
                           solar_w_m2=800.0, source="test")
    outdoor = LightEnvironmentCoupling(outdoor=True).apply(sample)
    indoor = LightEnvironmentCoupling(outdoor=False, window_transmission=0.4).apply(sample)
    assert outdoor.cooling_mult > 1.0 and outdoor.solar_heat_w > 0
    assert indoor.cooling_mult == 1.0 and indoor.solar_heat_w == 0.0
    assert indoor.daylight_lux < outdoor.daylight_lux    # through the glazing


def test_photocell_switches_on_at_dusk_with_hysteresis():
    cell = PhotocellControl(switch_on_lux=50.0, hysteresis_frac=2.0)
    assert cell.drive_for(20000.0) == 0.0     # broad daylight
    assert cell.drive_for(30.0) == 1.0        # dusk
    assert cell.drive_for(70.0) == 1.0        # stays on inside the band
    assert cell.drive_for(200.0) == 0.0       # morning


def test_daylight_harvesting_dims_against_the_sky():
    control = DaylightHarvesting(target_lux=500.0, full_output_lux=500.0)
    assert control.drive_for(0.0) == pytest.approx(1.0)
    assert control.drive_for(250.0) == pytest.approx(0.5)
    assert control.drive_for(900.0) == 0.0


def test_weather_driven_run_records_conditions_and_daylight():
    from simura.weather import SyntheticProvider

    sim = LightSimulator(
        spec=LightSpec(lamp_type="led-100-flood"),
        sim_config=LightSimConfig(dt_s=600.0, duration_s=86400.0, mounting_height_m=8.0),
        profile=ConstantDrive(1.0),
        weather=SyntheticProvider(mean_temp_c=15.0, solar_peak_w_m2=800.0),
        weather_epoch0=1704110400.0,
    )
    frames = sim.run_to_list()
    assert all(f.weather is not None for f in frames)
    assert max(f.daylight_lux or 0.0 for f in frames) > 10000.0    # midday
    assert min(f.daylight_lux or 0.0 for f in frames) == 0.0       # night


def test_photocell_control_burns_less_energy_than_running_all_day():
    from simura.weather import SyntheticProvider

    def energy(control) -> float:
        sim = LightSimulator(
            spec=LightSpec(lamp_type="hps-150-e40"),
            sim_config=LightSimConfig(dt_s=600.0, duration_s=86400.0),
            profile=ConstantDrive(1.0),
            weather=SyntheticProvider(mean_temp_c=15.0, solar_peak_w_m2=800.0),
            weather_epoch0=1704110400.0,
            control=control,
        )
        return sum(f.input_power_w for f in sim.run_to_list())

    assert energy(PhotocellControl()) < 0.75 * energy(None)


# -- declarative builders --------------------------------------------------
def test_build_light_ignores_unknown_keys():
    spec = build_light({"lamp_type": "led-9-e27", "colour": "warm", "power_w": 12.0})
    assert spec.lamp_type == "led-9-e27" and spec.power_w == 12.0


def test_light_spec_round_trips():
    spec = LightSpec(lamp_type="mh-250-e40", operating_hours_h=1200.0)
    assert LightSpec.from_dict(spec.to_dict()) == spec


# -- running off a supply that is not at its rated voltage -----------------
#
# The seam a whole-site client runs through: a lamp at the far end of a
# cable does not get its rated voltage, and what happens next is the sharpest
# difference between the technologies in this package.

def test_filament_follows_the_supply_and_reddens():
    """A filament is wired straight across the supply, so the voltage *is* the drive."""
    light = Light(LightSpec(lamp_type="hal-50-gu10", supply_voltage_v=48.0))
    light.time_lit_s = 1e9
    full = light.at_supply(48.0)
    sagged = light.at_supply(40.8)          # 85% of rated

    assert not full.regulated and not sagged.regulated
    # Light collapses far faster than power: roughly V^3.4.
    assert sagged.point.luminous_flux_lm < 0.6 * full.point.luminous_flux_lm
    assert sagged.supply_current_a > 0.85 * full.supply_current_a
    # And it goes orange, because the filament is genuinely cooler.
    assert sagged.point.color_temp_k < full.point.color_temp_k - 80


def test_a_regulated_lamp_draws_more_current_as_the_bus_sags():
    """Constant power off a falling voltage means rising current — the load fights back.

    This is the coupling that makes a DC lighting circuit interesting: an
    undersized run sags the bus, which makes every driver on it pull harder,
    which sags it further.
    """
    light = Light(LightSpec(lamp_type="led-15-e27", supply_voltage_v=48.0))
    light.time_lit_s = 1e9
    full = light.at_supply(48.0)
    sagged = light.at_supply(42.0)

    assert full.regulated and not sagged.dropped_out
    # Output does not move...
    assert sagged.point.luminous_flux_lm == pytest.approx(full.point.luminous_flux_lm, rel=1e-6)
    # ...but the current does, and upward.
    assert sagged.supply_current_a > full.supply_current_a
    assert sagged.supply_current_a * sagged.supply_voltage_v == pytest.approx(
        full.supply_current_a * full.supply_voltage_v, rel=1e-6
    )


def test_gear_drops_out_with_no_warning():
    """Below its dropout the lamp is simply out — it does not dim on the way down."""
    light = Light(LightSpec(lamp_type="led-15-e27", supply_voltage_v=48.0))
    light.time_lit_s = 1e9
    just_above = light.at_supply(48.0 * 0.82)
    just_below = light.at_supply(48.0 * 0.78)

    assert just_above.point.lit and not just_above.dropped_out
    assert just_above.point.luminous_flux_lm > 0
    assert just_below.dropped_out
    assert just_below.point.luminous_flux_lm == 0.0
    assert just_below.supply_current_a == 0.0


def test_over_voltage_burns_a_filament_brighter():
    light = Light(LightSpec(lamp_type="inc-60-e27", supply_voltage_v=48.0))
    rated = light.at_supply(48.0)
    over = light.at_supply(57.6)            # 120% of rated

    assert over.over_voltage
    assert over.point.luminous_flux_lm > 1.8 * rated.point.luminous_flux_lm
    assert over.point.source_temp_c > rated.point.source_temp_c
    assert over.point.color_temp_k > rated.point.color_temp_k


def test_a_lamp_calibrates_to_whatever_bus_it_is_wound_for():
    """The same catalog lamp on a 48 V DC site and on 230 V mains is the same lamp.

    Only the winding differs: the model back-solves the filament (or sizes the
    driver) from the rated power and *this* supply, so both deliver the same
    light for the same watts.
    """
    mains = Light(LightSpec(lamp_type="inc-60-e27"))
    dc = Light(LightSpec(lamp_type="inc-60-e27", supply_voltage_v=48.0))
    a = mains.operating_point(1.0, 25.0)
    b = dc.operating_point(1.0, 25.0)
    assert b.luminous_flux_lm == pytest.approx(a.luminous_flux_lm, rel=0.01)
    assert b.input_power_w == pytest.approx(a.input_power_w, rel=0.01)
    # But the low-voltage one draws far more current for it.
    assert b.current_a > 4 * a.current_a


def test_supply_faults_compose_with_a_sagging_bus():
    """An injected brown-out and a real cable drop must multiply, not overwrite."""
    from simura.lights import SupplyVoltageFault

    light = Light(LightSpec(lamp_type="hal-50-gu10", supply_voltage_v=48.0))
    light.time_lit_s = 1e9
    effect = accumulate([SupplyVoltageFault(supply_mult=0.9)], light, 0.0)
    plain = light.at_supply(43.2)
    both = light.at_supply(43.2, effect=effect)
    assert both.point.luminous_flux_lm < plain.point.luminous_flux_lm


def test_a_dark_lamp_still_reports_its_maintenance():
    """Dropping out is an electrical event, not an ageing one."""
    light = Light(
        LightSpec(lamp_type="led-15-e27", supply_voltage_v=48.0, operating_hours_h=25000)
    )
    out = light.at_supply(10.0)
    assert out.dropped_out
    assert 0.0 < out.point.lumen_maintenance < 1.0


def test_supply_point_serializes():
    light = Light(LightSpec(lamp_type="fl-t8-36", supply_voltage_v=48.0))
    d = light.at_supply(46.0).to_dict()
    assert d["regulated"] is True
    assert "luminous_flux_lm" in d["point"]


# ---------------------------------------------------------------------------
# Rooms that are not rectangles
# ---------------------------------------------------------------------------

L_SHAPED_ROOM = [(0.0, 0.0), (8.0, 0.0), (8.0, 4.0), (4.0, 4.0), (4.0, 7.0), (0.0, 7.0)]


def _l_shaped_layout(outline):
    """The same three fittings, solved over a rectangle and over the real room."""
    layout = Layout(8.0, 7.0, grid_n=9, outline=outline)
    for x, y in ((2.0, 2.0), (6.0, 2.0), (2.0, 5.5)):
        layout.add(f"L{x}-{y}", x, y, 2.7, LightSpec(lamp_type="led-15-e27"))
    return layout


def test_a_room_outline_is_measured_instead_of_its_bounding_box():
    solved = _l_shaped_layout(L_SHAPED_ROOM).solve()
    assert solved.area_m2 == pytest.approx(44.0)          # the room
    assert _l_shaped_layout(None).solve().area_m2 == pytest.approx(56.0)  # the box


def test_grid_points_outside_the_room_are_masked_not_darkened():
    # A point in the notch is not floor receiving no light; it is not floor. It
    # comes back as null so a heatmap can leave it blank rather than paint it
    # black, and so it never drags the statistics down.
    solved = _l_shaped_layout(L_SHAPED_ROOM).solve()
    masked = [v for row in solved.grid for v in row if v is None]
    assert masked, "an L-shaped room must mask some of its bounding box"
    assert all(v > 0 for row in solved.grid for v in row if v is not None)


def test_the_notch_is_what_was_dragging_the_uniformity_down():
    # The finding this feature exists to produce: the same three fittings in the
    # same places are a better design than the rectangle said they were, because
    # a fifth of the "room" the rectangle measured was never floor.
    box = _l_shaped_layout(None).solve()
    room = _l_shaped_layout(L_SHAPED_ROOM).solve()
    assert room.average_lux > box.average_lux
    assert room.uniformity > box.uniformity
    assert room.min_lux > box.min_lux


def test_a_solved_outline_travels_with_the_result():
    solved = _l_shaped_layout(L_SHAPED_ROOM).solve()
    assert len(solved.outline) == len(L_SHAPED_ROOM)
    # And the whole result is still serializable, masked points included.
    assert json.loads(json.dumps(solved.to_dict()))["outline"]


def test_a_layout_with_no_outline_is_exactly_what_it_always_was():
    # The feature is additive: every existing caller passes no outline and gets
    # the rectangular grid, unmasked, over the same points as before.
    solved = Layout(6.0, 4.0, grid_n=5).add(
        "L1", 3.0, 2.0, 2.5, LightSpec(lamp_type="led-15-e27")
    ).solve()
    assert solved.outline == []
    assert all(v is not None for row in solved.grid for v in row)
    assert solved.area_m2 == pytest.approx(24.0)
