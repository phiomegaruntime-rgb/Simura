"""Tests for the wire-model validation (simura.wires.validation).

Covers the standards catalog, the engine's replay + percent-error metrics against
a published DC-resistance table, the expected (honest) resistivity bias, and the
user-CSV loader.
"""

from __future__ import annotations

import pytest

from simura.wires.validation import (
    STANDARDS,
    WireReference,
    WireRefRow,
    get_standard,
    list_standards,
    load_upload_csv,
    validate_reference,
)


def test_standards_catalog_is_populated_and_indexed():
    ids = {s.id for s in list_standards()}
    assert {"copper-annealed-20c", "aluminum-20c"} <= ids
    assert len(list_standards()) == len(STANDARDS)
    assert get_standard("copper-annealed-20c").material == "copper"
    with pytest.raises(KeyError):
        get_standard("does-not-exist")


def test_standard_to_dict_hides_rows_but_reports_count():
    d = get_standard("copper-annealed-20c").to_dict()
    assert "_rows" not in d
    assert d["n_points"] == 10
    assert isinstance(d["what_it_validates"], list)


def test_copper_validation_bias_matches_resistivity_gap():
    # Simura models pure copper (1.68e-8) vs the annealed IACS standard
    # (1.7241e-8): the model should read ~2.5% below across every gauge.
    report = validate_reference(get_standard("copper-annealed-20c").reference())
    assert report.n_points == 10
    expected_bias = (1.68e-8 / 1.7241e-8 - 1.0) * 100.0  # ~ -2.56 %
    assert report.metrics["mean_bias_pct"] == pytest.approx(expected_bias, abs=0.3)
    # The gap is a near-constant scale factor, so RMSE ~ |bias| and spread is tiny.
    assert report.metrics["rmse_pct"] == pytest.approx(abs(expected_bias), abs=0.3)
    assert report.metrics["max_abs_pct"] < abs(expected_bias) + 0.5


def test_aluminum_validation_has_larger_bias_than_copper():
    cu = validate_reference(get_standard("copper-annealed-20c").reference())
    al = validate_reference(get_standard("aluminum-20c").reference())
    assert abs(al.metrics["mean_bias_pct"]) > abs(cu.metrics["mean_bias_pct"])


def test_overlay_arrays_are_aligned_and_ordered():
    report = validate_reference(get_standard("copper-annealed-20c").reference())
    o = report.overlay
    n = report.n_points
    assert len(o["awg"]) == len(o["published_ohm_per_km"]) == len(o["model_ohm_per_km"]) == n
    assert len(o["error_pct"]) == n
    # Rows run thin -> thick, so resistance is monotonically decreasing.
    assert o["published_ohm_per_km"] == sorted(o["published_ohm_per_km"], reverse=True)


def test_temperature_standard_resistance_is_higher_than_20c():
    r20 = validate_reference(get_standard("copper-annealed-20c").reference())
    r75 = validate_reference(get_standard("copper-annealed-75c").reference())
    # Same gauges, hotter reference -> every published & modelled value is larger.
    assert r75.overlay["published_ohm_per_km"][0] > r20.overlay["published_ohm_per_km"][0]
    assert r75.overlay["model_ohm_per_km"][0] > r20.overlay["model_ohm_per_km"][0]


def test_zero_error_when_reference_matches_the_model():
    # Build a reference straight from Simura's own model: error must be ~0.
    from simura.wires import Wire, WireSpec

    rows = []
    for awg in (14, 10, 6):
        r = Wire(WireSpec(material="copper", awg=awg, length_m=1.0, ambient_temp_c=20.0))
        rows.append(WireRefRow(awg=awg, area_mm2=1.0, published_ohm_per_km=r.resistance_ohm(20.0) * 1000.0))
    ref = WireReference(standard_id="self", material="copper", ref_temp_c=20.0, rows=rows)
    report = validate_reference(ref)
    assert report.metrics["max_abs_pct"] == pytest.approx(0.0, abs=1e-6)


def test_upload_loader_parses_awg_and_resistance(tmp_path):
    csv = tmp_path / "measured.csv"
    csv.write_text("awg,resistance_ohm_per_km\n14,8.3\n10,3.28\n6,1.30\n", encoding="utf-8")
    ref = load_upload_csv(str(csv), material="copper")
    assert ref.n_points == 3
    assert ref.data_source == "user-upload"
    report = validate_reference(ref)
    # Close to the annealed standard, so errors are single-digit percent.
    assert report.metrics["max_abs_pct"] < 5.0


def test_upload_loader_unit_conversion_mohm_per_m(tmp_path):
    # 1 mΩ/m == 1 Ω/km, so the two files must validate identically.
    a = tmp_path / "a.csv"
    a.write_text("awg,r\n10,3.28\n6,1.30\n", encoding="utf-8")
    ref_a = load_upload_csv(str(a), resistance_col="r", resistance_unit="ohm/km")
    ref_b = load_upload_csv(str(a), resistance_col="r", resistance_unit="mohm/m")
    assert ref_a.rows[0].published_ohm_per_km == pytest.approx(ref_b.rows[0].published_ohm_per_km)


def test_upload_loader_rejects_missing_column(tmp_path):
    csv = tmp_path / "bad.csv"
    csv.write_text("gauge,ohms\n14,8.3\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_upload_csv(str(csv))


def test_upload_loader_skips_nonstandard_gauges(tmp_path):
    csv = tmp_path / "mixed.csv"
    # AWG 99 isn't a standard size and must be dropped, leaving two valid rows.
    csv.write_text("awg,resistance_ohm_per_km\n14,8.3\n99,1.0\n10,3.28\n", encoding="utf-8")
    ref = load_upload_csv(str(csv))
    assert ref.n_points == 2
