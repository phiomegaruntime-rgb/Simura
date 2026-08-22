"""Tests for the "get familiar" layer (simura.explain).

The thing worth testing here is not that sentences come out. It is that the
sentences are **downstream of the physics** — that an attribution reproduces the
model it claims to decompose, that changing the model changes the explanation,
and that the prose layer never contradicts the numbers it is describing. A test
suite that only asserted "the headline is non-empty" would pass forever while
the layer quietly stopped being true, which is the exact failure this component
exists to prevent.

So the tests are grouped as:

* **arithmetic** — the two decompositions add up and multiply out.
* **fidelity** — each attribution reproduces the number the physics library
  itself reports, to the library's own precision.
* **responsiveness** — perturb the model and the ranking moves the way the
  physics says it must.
* **coverage** — every parameter in the code has a card, in both directions.
* **rendering** — depth adds and never contradicts; a lens reorders and never
  drops.
"""

from __future__ import annotations

import math

import pytest

from simura.builder import FaultSpec, ProfileSpec, SystemSpec, build_simulator
from simura.explain import (
    Attribution,
    Term,
    additive,
    brief,
    coverage,
    define,
    explain_frame,
    explain_pack,
    find_param,
    get_card,
    get_domain,
    list_cards,
    list_domains,
    list_terms,
    multiplicative,
    quantity,
    render,
    render_all,
    translate,
)
from simura.explain import battery as bx
from simura.explain import lights as lx
from simura.explain import wires as wx
from simura.explain.cards import ALL_CARDS, COMPONENTS
from simura.explain.levels import LEVELS, at_least, deeper
from simura.lights import LightSpec, evaluate_installation, build_layout
from simura.lights.lamp import Light
from simura.wires import WireSpec, evaluate_run


# ==========================================================================
# Fixtures: real runs of the real models, not hand-made numbers
# ==========================================================================


@pytest.fixture(scope="module")
def healthy():
    spec = SystemSpec(
        series=4, parallel=3, duration_s=600, dt_s=1.0,
        profile=ProfileSpec("constant_current", {"amps": 24.0}),
    )
    sim = build_simulator(spec)
    frames = list(sim.run())
    return sim, spec, frames[-1].to_dict()


@pytest.fixture(scope="module")
def shorted():
    spec = SystemSpec(
        series=4, parallel=3, duration_s=900, dt_s=1.0,
        profile=ProfileSpec("constant_current", {"amps": 24.0}),
        faults=[FaultSpec("internal_short", 2, 1, 300.0, {"r_short_ohm": 1.0})],
    )
    sim = build_simulator(spec)
    frames = list(sim.run())
    return sim, spec, frames[-1].to_dict()


# ==========================================================================
# The attribution core
# ==========================================================================


def _t(key, value, unit="W"):
    return Term(key=key, label=key.title(), value=value, unit=unit, symbol=key, why="")


def test_additive_total_is_computed_from_the_terms_not_asserted():
    a = additive("k", "K", "W", "eq", [_t("a", 3.0), _t("b", -1.0)])
    assert a.total == pytest.approx(2.0)
    # A caller cannot hand in a total that disagrees with the terms, which is
    # what makes "the number and the sentence agree" structural rather than a
    # thing to remember.
    assert not hasattr(a, "set_total")


def test_additive_shares_are_gross_so_a_near_cancellation_stays_legible():
    a = additive("k", "K", "W", "eq", [_t("heat", 10.0), _t("cool", -9.8)])
    assert a.total == pytest.approx(0.2)
    assert a.balanced
    # Net shares would be 50x and -49x here. Gross shares stay in [0, 1].
    assert all(0.0 <= t.share <= 1.0 for t in a.terms)
    assert a.dominant.key == "heat"
    assert [t.key for t in a.opposing] == ["cool"]


def test_additive_ranks_by_magnitude_regardless_of_sign():
    a = additive("k", "K", "W", "eq", [_t("small", 1.0), _t("big", -50.0)])
    assert a.dominant.key == "big"


def test_negligible_terms_are_flagged_but_significant_never_empties():
    a = additive("k", "K", "W", "eq", [_t("big", 100.0), _t("dust", 0.05)])
    assert a.term("dust").negligible
    assert [t.key for t in a.significant] == ["big"]
    # Even an attribution of one tiny term still yields something to say.
    lone = additive("k", "K", "W", "eq", [_t("only", 1e-9)])
    assert len(lone.significant) == 1


def test_multiplicative_total_is_the_product_of_base_and_factors():
    a = multiplicative("k", "K", "Ω", "eq", 2.0,
                       [_t("x", 3.0, "×"), _t("y", 0.5, "×")])
    assert a.total == pytest.approx(3.0)


def test_multiplicative_shares_are_order_independent_and_log_symmetric():
    doubling = _t("up", 2.0, "×")
    halving = _t("down", 0.5, "×")
    a = multiplicative("k", "K", "Ω", "eq", 1.0, [doubling, halving])
    b = multiplicative("k", "K", "Ω", "eq", 1.0, [halving, doubling])
    # Moving the answer 2x up and 2x down are equally responsible for where it
    # ended up, and writing them in the other order changes nothing.
    assert a.term("up").share == pytest.approx(a.term("down").share)
    assert a.term("up").share == pytest.approx(b.term("up").share)


def test_a_factor_of_one_gets_no_share():
    a = multiplicative("k", "K", "Ω", "eq", 1.0,
                       [_t("moves", 4.0, "×"), _t("inert", 1.0, "×")])
    assert a.term("inert").share == pytest.approx(0.0)
    assert a.term("moves").share == pytest.approx(1.0)


def test_a_zero_factor_takes_the_whole_share_because_it_annihilates_the_outcome():
    a = multiplicative("k", "K", "lm", "eq", 100.0,
                       [_t("dead", 0.0, "×"), _t("other", 0.5, "×")])
    assert a.total == pytest.approx(0.0)
    # The logarithm does not reach zero, but the physics does. Ranking by |ln|
    # here would report a burnt-out lamp's supply voltage as the reason it is
    # dark, which is true of the arithmetic and absurd as an explanation.
    assert a.dominant.key == "dead"
    assert a.term("dead").share == pytest.approx(1.0)
    assert a.term("other").share == pytest.approx(0.0)


def test_several_zero_factors_share_the_blame_equally():
    a = multiplicative("k", "K", "lm", "eq", 100.0,
                       [_t("dead", 0.0, "×"), _t("also_dead", 0.0, "×"), _t("fine", 0.9, "×")])
    # Either one alone would have been enough, so neither outranks the other.
    assert a.term("dead").share == pytest.approx(0.5)
    assert a.term("also_dead").share == pytest.approx(0.5)
    assert a.term("fine").share == pytest.approx(0.0)


# ==========================================================================
# Fidelity: the attribution reproduces the model it decomposes
# ==========================================================================


def test_heat_balance_reproduces_the_packs_own_temperature_derivative(shorted):
    sim, _spec, _frame = shorted
    s, p = 2, 1
    point = bx.operating_point_from_pack(sim.pack, s, p, sim.effect)
    a = bx.heat_balance(point)

    # Recompute dT/dt straight from simura.sim.pack's equation.
    i_tot = point.current_a + point.extra_current_a
    q_gen = i_tot**2 * point.r0_ohm + point.current_a * point.v_rc_v + point.extra_heat_w
    expected = q_gen - point.k_cool_w_per_k * (point.temp_c - point.ambient_c)
    assert a.total == pytest.approx(expected, rel=1e-12)
    assert a.operating_point["rate_c_per_min"] == pytest.approx(
        expected / point.c_th_j_per_k * 60.0
    )


def test_voltage_sag_terms_reconstruct_the_terminal_law(shorted):
    sim, _spec, _frame = shorted
    point = bx.operating_point_from_pack(sim.pack, 2, 1, sim.effect)
    a = bx.voltage_sag(point)
    assert point.ocv_v - a.total == pytest.approx(point.voltage_v, abs=1e-9)


def test_charge_rate_matches_coulomb_counting(shorted):
    sim, _spec, _frame = shorted
    point = bx.operating_point_from_pack(sim.pack, 2, 1, sim.effect)
    a = bx.charge_rate(point)
    i_tot = point.current_a + point.extra_current_a
    expected = -point.coulombic_eff * i_tot / point.capacity_ah * 100.0
    assert a.total == pytest.approx(expected, rel=1e-12)


def test_imbalance_terms_sum_to_the_measured_spread(shorted):
    _sim, spec, frame = shorted
    a = bx.imbalance(frame, spec)
    assert a.total == pytest.approx(frame["voltage_imbalance_v"], abs=1e-3)


def test_wire_resistance_reproduces_the_wire_models_own_number():
    spec = WireSpec(awg=12, length_m=40.0)
    from simura.wires.wire import Wire

    wire = Wire(spec)
    for t_c in (0.0, 20.0, 65.0, 90.0):
        a = wx.resistance(spec, at_temp_c=t_c)
        assert a.total == pytest.approx(wire.resistance_ohm(t_c), rel=1e-12)


def test_wire_voltage_drop_reproduces_evaluate_run():
    spec = WireSpec(awg=12, length_m=40.0, ambient_temp_c=35.0)
    got = evaluate_run(spec, current_a=18.0, system_voltage_v=12.0, round_trip=True)
    a = wx.voltage_drop(spec, 18.0, 12.0, round_trip=True,
                        at_temp_c=got.steady_state_temp_c)
    # RunAssessment rounds its fields, so the temperature fed back in is the
    # rounded one; agreement is exact to the precision the library reports.
    assert a.total == pytest.approx(got.voltage_drop_v, rel=1e-3)
    assert a.operating_point["drop_pct"] == pytest.approx(got.voltage_drop_pct, rel=1e-3)


def test_wire_ampacity_margin_agrees_with_the_derating_law():
    spec = WireSpec(awg=12, length_m=10.0, ambient_temp_c=45.0)
    from simura.wires.wire import Wire

    wire = Wire(spec)
    a = wx.ampacity_margin(spec, 18.0, ambient_c=45.0)
    assert a.total == pytest.approx(wire.derated_ampacity_a(45.0) - 18.0, rel=1e-12)


def test_wire_heat_balance_closes_at_the_steady_state_the_model_solves():
    spec = WireSpec(awg=12, length_m=40.0, ambient_temp_c=35.0)
    a = wx.heat_balance(spec, 18.0, ambient_c=35.0)
    # Evaluated at its own equilibrium, generation and cooling must cancel.
    assert a.balanced
    assert abs(a.total) < 1e-5


@pytest.mark.parametrize(
    "lamp_id",
    ["inc-60-e27", "hal-50-gu10", "led-9-e27", "fl-t8-36", "lps-135-bx", "hps-150-e40"],
)
def test_lamp_efficacy_factors_multiply_back_to_the_model_across_all_families(lamp_id):
    light = Light(LightSpec(lamp_type=lamp_id))
    light.time_lit_s = 1e9
    point = light.operating_point()
    a = lx.efficacy(point)
    assert a.total == pytest.approx(point.efficacy_lm_per_w, rel=1e-9)
    # Every factor is a fraction of the physical ceiling, never above it.
    for t in a.terms:
        assert 0.0 < t.value <= 1.0
    assert a.total <= 683.0


def test_illuminance_factors_multiply_back_to_the_lumen_method():
    a = evaluate_installation(
        LightSpec(lamp_type="led-9-e27"), n_luminaires=12,
        length_m=10, width_m=8, mounting_height_m=2.5,
        task="office", maintenance_hours=20000, dirt_frac=0.15,
    )
    att = lx.illuminance(a)
    # RoomLighting rounds the utilisation and loss factors it reports, so the
    # reconstruction agrees to their precision rather than to machine epsilon.
    assert att.total == pytest.approx(a.maintained_lux, rel=1e-3)


def test_field_split_sums_to_the_solved_average():
    lay = build_layout({
        "length_m": 10, "width_m": 8,
        "grid": {"rows": 3, "cols": 4, "height_m": 3.0,
                 "lamp": {"lamp_type": "led-100-flood"}},
    }).solve()
    a = lx.field_split(lay)
    assert a.total == pytest.approx(lay.average_lux, rel=1e-6)


# ==========================================================================
# Responsiveness: change the physics, and the explanation must change with it
# ==========================================================================


def test_a_short_makes_fault_heat_a_term_that_was_not_there_before(healthy, shorted):
    hsim, _hs, _hf = healthy
    ssim, _ss, _sf = shorted
    clean = bx.heat_balance(bx.operating_point_from_pack(hsim.pack, 2, 1, hsim.effect))
    broken = bx.heat_balance(bx.operating_point_from_pack(ssim.pack, 2, 1, ssim.effect))
    assert clean.term("fault_heat") is None
    assert broken.term("fault_heat") is not None
    assert broken.term("fault_heat").value > 0


def test_a_short_splits_the_charge_rate_into_useful_and_wasted(healthy, shorted):
    hsim, _hs, _hf = healthy
    ssim, _ss, _sf = shorted
    clean = bx.charge_rate(bx.operating_point_from_pack(hsim.pack, 2, 1, hsim.effect))
    broken = bx.charge_rate(bx.operating_point_from_pack(ssim.pack, 2, 1, ssim.effect))
    assert clean.term("parasitic") is None
    # The shorted cell is losing charge that never reaches the terminals -- the
    # distinguishing signature of an internal short, and here it is, computed.
    assert broken.term("parasitic").value < 0


def test_resistive_heating_follows_the_square_of_current():
    def ohmic_at(amps):
        point = bx.CellPoint(
            series_index=0, parallel_index=0, current_a=amps, voltage_v=3.6,
            temp_c=25.0, soc=0.5, ocv_v=3.7, v_rc_v=0.0, r0_ohm=0.02,
            capacity_ah=5.0, c_th_j_per_k=70.0, k_cool_w_per_k=0.5,
            ambient_c=25.0,
        )
        return bx.heat_balance(point).term("ohmic").value

    # Nothing in the prose asserts that four times the heat follows twice the
    # current -- the term is I^2*R and the arithmetic does the rest.
    assert ohmic_at(20.0) == pytest.approx(4.0 * ohmic_at(10.0))
    assert ohmic_at(40.0) == pytest.approx(16.0 * ohmic_at(10.0))


def test_a_cold_cell_is_generation_dominated_and_a_warm_one_is_cooling_dominated():
    def dominant_after(duration_s):
        spec = SystemSpec(series=4, parallel=1, duration_s=duration_s, dt_s=1.0,
                          profile=ProfileSpec("constant_current", {"amps": 20.0}))
        sim = build_simulator(spec)
        list(sim.run())
        return bx.heat_balance(bx.operating_point_from_pack(sim.pack, 0, 0, sim.effect))

    # The same load, the same cell. Cooling scales with how far above ambient
    # the cell has climbed, so which term leads changes as the run proceeds --
    # and the sentence changes with it, because it is built from the ranking.
    assert dominant_after(2).dominant.key == "ohmic"
    assert dominant_after(1200).dominant.key == "cooling"


def test_length_beats_gauge_on_a_long_run_and_loses_on_a_short_one():
    long_run = wx.voltage_drop(WireSpec(awg=12, length_m=60.0), 15.0, at_temp_c=20.0)
    short_run = wx.voltage_drop(WireSpec(awg=12, length_m=0.5), 15.0, at_temp_c=20.0)
    assert long_run.dominant.key == "length"
    assert short_run.dominant.key != "length"


def test_a_hot_ambient_costs_more_headroom_than_a_cool_one():
    cool = wx.ampacity_margin(WireSpec(awg=12, length_m=10.0), 15.0, ambient_c=20.0)
    hot = wx.ampacity_margin(WireSpec(awg=12, length_m=10.0), 15.0, ambient_c=60.0)
    assert cool.term("derating").value > 0  # cooler than reference: a bonus
    assert hot.term("derating").value < 0
    assert hot.total < cool.total


def test_a_filaments_problem_is_its_spectrum_and_an_leds_is_not():
    def factors(lamp_id):
        light = Light(LightSpec(lamp_type=lamp_id))
        light.time_lit_s = 1e9
        return {t.key: t.value for t in lx.efficacy(light.operating_point()).terms}

    inc, led = factors("inc-60-e27"), factors("led-9-e27")
    # The emergent finding the decomposition is for: a filament is *better* than
    # an LED at turning power into radiation, and far worse at putting that
    # radiation where the eye can see it.
    assert inc["radiant"] > led["radiant"]
    assert inc["spectrum"] < led["spectrum"] / 10


def test_dirtying_the_luminaires_moves_the_ranking_to_dirt():
    def att(dirt):
        a = evaluate_installation(
            LightSpec(lamp_type="led-9-e27"), n_luminaires=12,
            length_m=10, width_m=8, mounting_height_m=2.5,
            task="office", maintenance_hours=0, dirt_frac=dirt,
        )
        return lx.illuminance(a)

    clean, filthy = att(0.02), att(0.7)
    assert clean.term("light_loss").share < filthy.term("light_loss").share
    assert filthy.dominant.key == "light_loss"


# ==========================================================================
# Inference from telemetry: honest about what it cannot see
# ==========================================================================


def test_frame_inference_recovers_the_terminal_law_exactly(healthy):
    _sim, spec, frame = healthy
    point = bx.operating_point_from_frame(frame, spec, 0, 0)
    # V_rc was solved for, so the law it was solved from must close.
    assert point.ocv_v - point.current_a * point.r0_ohm - point.v_rc_v == pytest.approx(
        point.voltage_v, abs=1e-9
    )
    assert point.exact is False


def test_frame_attributions_carry_their_caveat_and_pack_ones_do_not(healthy):
    sim, spec, frame = healthy
    inferred = bx.explain_frame(frame, spec)
    exact = bx.explain_pack(sim)
    assert all(a.caveat and not a.exact for a in inferred)
    assert all(a.caveat is None and a.exact for a in exact)


def test_the_caveat_is_shown_at_every_depth_including_the_shallowest(healthy):
    _sim, spec, frame = healthy
    a = bx.explain_frame(frame, spec)[0]
    for level in LEVELS:
        # Depth changes how much detail is shown, never how trustworthy the
        # answer is claimed to be.
        assert render(a, "newcomer", level).caveat


def test_explain_pack_prefers_the_simulators_effect_over_a_bare_pack(shorted):
    sim, _spec, _frame = shorted
    with_effect = bx.explain_pack(sim)[0]
    without = bx.explain_pack(sim.pack)[0]
    # A bare pack cannot see fault heat, so it reports the cell shedding heat it
    # is in fact still making. Passing the simulator is what fixes that.
    assert with_effect.term("fault_heat") is not None
    assert without.term("fault_heat") is None
    assert with_effect.total > without.total


def test_cell_of_interest_picks_the_hottest_cell(shorted):
    _sim, _spec, frame = shorted
    s, p = bx.cell_of_interest(frame)
    hottest = max(frame["cells"], key=lambda c: c["temp_c"])
    assert (s, p) == (hottest["series_index"], hottest["parallel_index"])


def test_asking_about_a_cell_that_is_not_there_fails_loudly(healthy):
    _sim, spec, frame = healthy
    with pytest.raises(IndexError):
        bx.operating_point_from_frame(frame, spec, 99, 99)


# ==========================================================================
# Cards and glossary
# ==========================================================================


def test_every_parameter_in_the_code_has_a_card_and_no_card_is_orphaned():
    c = coverage()
    assert c["missing"] == [], f"parameters with no model card: {c['missing']}"
    assert c["orphaned"] == [], f"cards describing dead parameters: {c['orphaned']}"
    assert c["complete"]
    assert c["documented"] == c["parameters_in_code"] > 0


def test_every_card_declares_what_it_cannot_do():
    # A model card that only says what a model does is marketing.
    missing = [c.id for c in ALL_CARDS if not c.limits]
    assert missing == [], f"cards with no stated limits: {missing}"


def test_every_card_belongs_to_a_real_component_and_has_a_unique_id():
    ids = [c.id for c in ALL_CARDS]
    assert len(ids) == len(set(ids))
    assert all(c.component in COMPONENTS for c in ALL_CARDS)


def test_see_also_never_points_at_a_card_that_does_not_exist():
    known = {c.id for c in ALL_CARDS}
    for card in ALL_CARDS:
        for ref in card.see_also:
            assert ref in known, f"{card.id} points at missing card {ref}"


def test_every_attribution_names_a_card_that_exists(shorted):
    sim, spec, frame = shorted
    atts = list(bx.explain_frame(frame, spec))
    atts += wx.explain_run(WireSpec(awg=12, length_m=20.0), 15.0, 12.0)
    for a in atts:
        assert a.card is not None
        get_card(a.card)  # raises if unknown


def test_find_param_joins_a_form_field_to_its_explanation():
    hit = find_param("cooling_conductance_w_per_k")
    assert hit is not None
    card, param = hit
    assert card.component == "batteries"
    assert param.why and param.what
    assert find_param("not_a_real_field") is None


def test_glossary_entries_resolve_by_alias_and_are_case_insensitive():
    assert define("SoC") is define("state of charge")
    assert define("ocv").card == "battery.ocv"
    assert define("  Ampacity ").term == "ampacity"
    assert define("wharrgarbl") is None


def test_glossary_cards_all_exist():
    known = {c.id for c in ALL_CARDS}
    for entry in list_terms():
        if entry.card is not None:
            assert entry.card in known, f"{entry.term} points at missing card {entry.card}"


def test_component_filter_partitions_the_cards():
    counts = sum(len(list_cards(c)) for c in COMPONENTS)
    assert counts == len(list_cards())
    with pytest.raises(KeyError):
        list_cards("submarines")


# ==========================================================================
# Domains and levels
# ==========================================================================


def test_a_lens_reorders_and_never_drops(shorted):
    sim, spec, frame = shorted
    atts = bx.explain_frame(frame, spec)
    keys = {a.key for a in atts}
    for domain in list_domains():
        rendered = render_all(atts, domain.key, "working")
        assert {e.key for e in rendered} == keys


def test_different_lenses_lead_with_different_things(shorted):
    sim, spec, frame = shorted
    atts = bx.explain_frame(frame, spec)
    first = {d.key: render_all(atts, d.key, "overview")[0].key for d in list_domains()}
    # Same computation, different reader, different opening sentence.
    assert first["battery"] == "cell.voltage_sag"
    assert first["safety"] == "cell.heat_balance"
    assert len(set(first.values())) > 1


def test_translation_replaces_the_longest_phrase_first():
    ops = get_domain("operations")
    # "voltage imbalance" must win over the "cell" inside a longer phrase, and
    # a phrase must not be shredded by the single words it contains.
    assert translate("Voltage imbalance is rising", ops).startswith("Pack balance")
    assert "module slot" in translate("the cell is warm", ops)


def test_translation_preserves_sentence_case():
    ops = get_domain("operations")
    assert translate("Cell temperature", ops)[0].isupper()


def test_a_domain_with_no_vocabulary_leaves_prose_untouched():
    text = "Voltage imbalance is rising"
    assert translate(text, get_domain("battery")) == text


def test_unknown_domain_and_level_are_rejected_by_name():
    with pytest.raises(KeyError):
        get_domain("astrology")
    from simura.explain.levels import get_level

    with pytest.raises(KeyError):
        get_level("everything")


def test_levels_are_ordered_and_the_deepest_has_no_deeper():
    assert at_least("physics", "overview")
    assert not at_least("overview", "working")
    assert deeper("overview") == "working"
    assert deeper("physics") is None


# ==========================================================================
# Rendering: depth adds, never contradicts
# ==========================================================================


def test_depth_adds_detail_without_changing_the_headline(shorted):
    sim, _spec, _frame = shorted
    a = bx.explain_pack(sim)[0]
    rendered = {lv: render(a, "newcomer", lv) for lv in LEVELS}
    headlines = {r.headline for r in rendered.values()}
    assert len(headlines) == 1, "a deeper level must not restate the claim"
    assert not rendered["overview"].causes
    assert rendered["working"].causes
    assert not rendered["overview"].equation
    assert rendered["physics"].equation
    assert rendered["physics"].limits


def test_the_physics_level_hides_nothing_the_ranking_called_negligible(shorted):
    sim, _spec, _frame = shorted
    a = bx.explain_pack(sim)[0]
    assert len(render(a, "newcomer", "physics").terms) == len(a.terms)
    assert len(render(a, "newcomer", "working").terms) == len(a.significant)


def test_the_quoted_value_is_the_same_at_every_depth(shorted):
    sim, _spec, _frame = shorted
    for a in bx.explain_pack(sim):
        values = {render(a, "operations", lv).value for lv in LEVELS}
        assert len(values) == 1


def test_a_headline_survives_being_read_on_its_own(shorted):
    sim, spec, frame = shorted
    for a in bx.explain_frame(frame, spec):
        h = render(a, "newcomer", "overview").headline
        assert h[0].isupper() and h.endswith(".")
        assert " None" not in h and "nan" not in h


def test_a_directional_verb_is_not_contradicted_by_a_negative_number():
    # "discharging at -176 %/h" reads as a double negative; the magnitude is
    # what belongs beside a verb that already carries the direction.
    a = additive("cell.charge_rate", "Rate", "%/h", "eq",
                 [_t("load", -176.0, "%/h")])
    h = render(a, "newcomer", "overview").headline
    assert "discharging" in h
    assert "-176" not in h and "−176" not in h


def test_a_single_cause_is_not_described_as_mostly_anything():
    a = additive("cell.charge_rate", "Rate", "%/h", "eq", [_t("load", -50.0, "%/h")])
    assert "mostly" not in render(a, "newcomer", "overview").headline


def test_an_equilibrium_says_where_it_settled_not_just_that_it_netted_zero():
    a = wx.heat_balance(WireSpec(awg=12, length_m=40.0, ambient_temp_c=35.0),
                        18.0, ambient_c=35.0)
    h = render(a, "electrical", "overview").headline
    assert "balance" in h
    assert "°C" in h, "a net of zero is useless without the temperature it settled at"


def test_follow_ups_point_only_at_cards_that_exist(shorted):
    sim, _spec, _frame = shorted
    known = {c.id for c in ALL_CARDS}
    for a in bx.explain_pack(sim):
        for f in render(a, "newcomer", "working").follow_ups:
            assert f["card"] in known
            assert f["question"].endswith("?")


def test_brief_is_one_headline_per_attribution(shorted):
    sim, _spec, _frame = shorted
    atts = bx.explain_pack(sim)
    text = brief(atts, "newcomer")
    assert text.count(".") >= len(atts)


def test_an_explanation_round_trips_to_plain_json(shorted):
    import json

    sim, _spec, _frame = shorted
    for a in bx.explain_pack(sim):
        json.dumps(a.to_dict())
        json.dumps(render(a, "operations", "physics").to_dict())


# ==========================================================================
# Number formatting
# ==========================================================================


@pytest.mark.parametrize(
    "value,unit,expected",
    [
        (0.0, "W", "0 W"),
        (1e-9, "W", "~0 W"),
        (0.0174, "W", "17.4 mW"),
        (1259.58, "lux", "1,260 lux"),   # lighting is quoted in plain lux
        (2.5, "×", "×2.5"),
        (float("nan"), "W", "—"),
        (float("inf"), "A", "—"),
    ],
)
def test_quantity_formats_the_way_a_person_would_write_it(value, unit, expected):
    assert quantity(value, unit) == expected


def test_an_operations_reader_gets_kilowatts_only_when_it_is_kilowatts():
    assert quantity(15.0, "W", "kW") == "15.0 W"
    assert quantity(42000.0, "W", "kW") == "42.0 kW"


# ==========================================================================
# Vocabulary substitution: the failure mode that recurs
# ==========================================================================
#
# A domain's vocabulary is applied to prose that was written with the canonical
# words in it, so a replacement phrase has to survive being dropped into the
# middle of a label as well as standing alone in a sentence. Mapping
# "ampacity" -> "the safe current for this cable" reads fine on its own and
# turns the label "Rated ampacity" into "Rated the safe current for this
# cable". That is not a typo anyone will notice in review, so it is checked
# mechanically over every lens and every quantity the project can explain.


def _all_attributions(sim, spec, frame):
    atts = list(bx.explain_pack(sim))
    atts += bx.explain_frame(frame, spec)
    atts += wx.explain_run(WireSpec(awg=12, length_m=40.0, ambient_temp_c=35.0),
                           18.0, 12.0, round_trip=True, ambient_c=35.0)
    installation = evaluate_installation(
        LightSpec(lamp_type="led-9-e27"), n_luminaires=12,
        length_m=10, width_m=8, mounting_height_m=2.5,
        task="office", maintenance_hours=20000, dirt_frac=0.15,
    )
    light = Light(LightSpec(lamp_type="led-9-e27"))
    light.time_lit_s = 1e9
    atts += lx.explain_installation(installation, point=light.operating_point())
    return atts


_ARTICLES = ("the ", "a ", "an ")


def test_every_vocabulary_entry_is_a_synonym_not_a_definition():
    """The lint that would have caught the real bug.

    Checking rendered output for stutters is not enough: the defect that
    actually happened -- "Rated ampacity" becoming "Rated the safe current for
    this cable" -- produces prose that is grammatical, just wrong. It is only
    detectable at the source, in the shape of the replacement itself.
    """
    problems: list[str] = []
    for domain in list_domains():
        for canonical, replacement in domain.vocabulary.items():
            where = f"{domain.key}: {canonical!r} -> {replacement!r}"
            # An article is fine only when the term being replaced has one too;
            # otherwise the surrounding sentence already supplied it.
            starts = replacement.lower().startswith(_ARTICLES)
            if starts and not canonical.lower().startswith(_ARTICLES):
                problems.append(f"{where} (leading article)")
            if len(replacement.split()) > len(canonical.split()) + 2:
                problems.append(f"{where} (a definition, not a synonym)")
            # Substitution runs longest-phrase-first in a single pass, so a
            # replacement is only unsafe if it contains a *shorter* canonical
            # that has not been processed yet -- that one would then be
            # substituted inside text this rule just produced.
            for other in domain.vocabulary:
                if len(other) < len(canonical) and other.lower() in replacement.lower():
                    problems.append(f"{where} (would then be re-matched by {other!r})")
    assert not problems, " | ".join(problems)


def test_no_lens_produces_a_stutter_or_a_broken_phrase(shorted):
    sim, spec, frame = shorted
    atts = _all_attributions(sim, spec, frame)
    bad: list[str] = []
    for domain in list_domains():
        for lv in LEVELS:
            for e in render_all(atts, domain.key, lv):
                for text in (e.headline, e.summary, *e.causes):
                    if not text:
                        continue
                    words = text.lower().replace(",", " ").replace(".", " ").split()
                    for a, b in zip(words, words[1:]):
                        # "slow slow", "the the" -- a phrase substituted into a
                        # label that already contained one of its own words.
                        if a == b and a.isalpha():
                            bad.append(f"[{domain.key}/{lv}] '{a} {b}' in: {text[:90]}")
    assert not bad, "\n".join(sorted(set(bad))[:10])


def test_every_headline_reads_as_a_sentence_under_every_lens(shorted):
    sim, spec, frame = shorted
    atts = _all_attributions(sim, spec, frame)
    for domain in list_domains():
        for e in render_all(atts, domain.key, "overview"):
            h = e.headline
            assert h[0].isupper(), f"[{domain.key}] {h}"
            assert h.endswith("."), f"[{domain.key}] {h}"
            # An article immediately followed by another article is what a
            # noun-phrase substitution looks like when it goes wrong.
            for artifact in (" the the ", " a the ", " is is ", " the a "):
                assert artifact not in f" {h.lower()} ", f"[{domain.key}] {h}"


# ==========================================================================
# One luminaire, against its rating
# ==========================================================================
#
# The decomposition a fitting in a real installation actually needs: it is rated
# for so many lumens and is producing fewer, so which of dimming, supply
# voltage, ambient, wear and faults did it? Every factor is a re-run of the lamp
# model with exactly one condition changed, chained so the product telescopes to
# the true ratio. That makes the arithmetic checkable against the model itself,
# which is what these tests do.


def _flux_at(spec, volts, ambient=None, faults=(), elapsed_s=0.0):
    """Run the real lamp model, the way the API does."""
    from simura.lights.faults import accumulate

    light = Light(LightSpec.from_dict(spec.to_dict()))
    light.time_lit_s = 1e9
    effect = accumulate(list(faults), light, elapsed_s) if faults else None
    return light.at_supply(volts, ambient_c=ambient, effect=effect).point.luminous_flux_lm


@pytest.mark.parametrize("lamp_id", ["inc-60-e27", "led-9-e27", "fl-t8-36", "hps-150-e40"])
def test_output_factors_telescope_to_the_models_own_flux(lamp_id):
    spec = LightSpec(lamp_type=lamp_id, operating_hours_h=6000, dirt_depreciation_frac=0.12)
    a = lx.output(spec, supply_voltage_v=207.0, ambient_c=40.0)
    assert a.total == pytest.approx(_flux_at(spec, 207.0, 40.0), rel=1e-9)
    # The base is the same lamp at its rating: nominal supply, 25 C, new, clean.
    rated = LightSpec(lamp_type=lamp_id)
    assert a.operating_point["rated_flux_lm"] == pytest.approx(
        _flux_at(rated, a.operating_point["nominal_voltage_v"], 25.0), rel=1e-9
    )


def test_a_sagging_supply_costs_a_filament_dearly_and_a_driven_lamp_nothing():
    volts = 207.0  # 10% low
    fil = lx.output(LightSpec(lamp_type="inc-60-e27"), supply_voltage_v=volts).term("supply")
    led = lx.output(LightSpec(lamp_type="led-9-e27"), supply_voltage_v=volts).term("supply")
    # Nothing in the explainer knows what a driver is. The filament solves an
    # energy balance and runs cooler; the LED's driver regulates. The factors
    # come out an order of magnitude apart because the lamp model differs.
    assert fil.value < 0.8
    assert led.value == pytest.approx(1.0, abs=1e-6)


def test_led_and_fluorescent_move_in_opposite_directions_on_ambient():
    led = lx.output(LightSpec(lamp_type="led-9-e27"), ambient_c=45.0).term("ambient")
    flu = lx.output(LightSpec(lamp_type="fl-t8-36"), ambient_c=10.0).term("ambient")
    assert led.value < 1.0   # a hot junction is a dimmer one
    assert flu.value < 1.0   # a cold tube has not reached its vapour-pressure optimum


def test_a_fault_appears_as_a_factor_only_when_there_is_one():
    from simura.lights.config import build_fault

    clean = lx.output(LightSpec(lamp_type="led-9-e27"), supply_voltage_v=230.0)
    broken = lx.output(
        LightSpec(lamp_type="led-9-e27"),
        supply_voltage_v=230.0,
        faults=[build_fault({"type": "heatsink_loss", "severity": 0.8})],
        elapsed_s=3600.0,
    )
    assert clean.term("faults") is None
    assert broken.term("faults").value < 1.0
    assert broken.total < clean.total


def test_a_lamp_past_its_life_is_explained_by_its_age_not_its_supply():
    # The regression this rule exists for: |ln 0| does not exist, so ranking by
    # logarithm alone reported a burnt-out lamp's *supply voltage* as the reason
    # it was dark. A zero factor annihilates the outcome, so it owns the answer.
    dead = lx.output(
        LightSpec(lamp_type="inc-60-e27", operating_hours_h=50000),
        supply_voltage_v=207.0,
    )
    assert dead.total == pytest.approx(0.0)
    assert dead.dominant.key == "maintenance"
    assert "age and dirt" in render(dead, "lighting", "overview").headline.lower()


def test_output_is_reported_as_a_fraction_of_the_rating():
    spec = LightSpec(lamp_type="led-9-e27", operating_hours_h=20000)
    a = lx.output(spec, supply_voltage_v=230.0)
    op = a.operating_point
    assert op["fraction_of_rated"] == pytest.approx(op["actual_flux_lm"] / op["rated_flux_lm"])
    assert 0.0 < op["fraction_of_rated"] < 1.0


# ==========================================================================
# Pinning a wire attribution to an already-solved temperature
# ==========================================================================


def test_a_pinned_temperature_is_used_instead_of_a_re_derived_one():
    spec = WireSpec(awg=12, length_m=40.0, ambient_temp_c=35.0)
    free = wx.explain_run(spec, 18.0, 12.0, ambient_c=35.0)
    pinned = wx.explain_run(spec, 18.0, 12.0, ambient_c=35.0, at_temp_c=45.0)

    def temp_of(atts):
        return next(a for a in atts if a.key == "wire.resistance").operating_point["temp_c"]

    assert temp_of(pinned) == pytest.approx(45.0)
    assert temp_of(free) != pytest.approx(45.0)
    # A network solve owns the temperature; the explanation must not quietly
    # disagree with the number displayed beside it.
    drop_pinned = next(a for a in pinned if a.key == "wire.voltage_drop")
    drop_free = next(a for a in free if a.key == "wire.voltage_drop")
    assert drop_pinned.total < drop_free.total
