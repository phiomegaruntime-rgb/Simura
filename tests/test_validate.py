"""Tests for the validation library (simura.validate).

Pure-library, offline: everything runs against the bundled *synthetic* sample
(``demo-synthetic``) so no dataset download and no SciPy are required.
"""

from __future__ import annotations

import numpy as np
import pytest

from simura.validate import (
    ReferenceRun,
    ValidationReport,
    datasets_for_chemistry,
    get_dataset,
    list_datasets,
    load_generic_csv,
    load_sample,
    loader_for,
    sample_path,
    validate_run,
)


# -- catalog ---------------------------------------------------------------
def test_catalog_non_empty_and_unique_ids():
    ds = list_datasets()
    assert len(ds) >= 5
    ids = [d.id for d in ds]
    assert len(ids) == len(set(ids))
    assert "demo-synthetic" in ids


def test_catalog_required_fields_present():
    for d in list_datasets():
        assert d.name and d.institution and d.chemistry
        assert d.license and d.citation, f"{d.id} missing license/citation"
        assert d.loader in {
            "generic_csv",
            "nasa_mat",
            "oxford_mat",
            "calce_csv",
            "sandia_csv",
        }
        assert isinstance(d.what_it_validates, tuple) and d.what_it_validates


def test_get_dataset_roundtrip_and_unknown():
    assert get_dataset("demo-synthetic").id == "demo-synthetic"
    with pytest.raises(KeyError):
        get_dataset("does-not-exist")


def test_datasets_for_chemistry_filters():
    lfp = datasets_for_chemistry("lfp")
    assert all("lfp" in d.chemistry.lower() for d in lfp)
    assert datasets_for_chemistry("NMC")  # case-insensitive, non-empty


def test_only_synthetic_entry_ships_a_sample():
    for d in list_datasets():
        if d.sample:
            assert d.synthetic, f"{d.id} ships data but isn't marked synthetic"


# -- reference invariants --------------------------------------------------
def test_reference_run_length_mismatch_raises():
    with pytest.raises(ValueError):
        ReferenceRun(
            dataset_id="x",
            time_s=np.arange(5.0),
            current_a=np.zeros(4),
            voltage_v=np.zeros(5),
        )


def test_reference_run_helpers():
    ref = ReferenceRun(
        dataset_id="x",
        time_s=np.array([0.0, 10.0, 20.0, 30.0]),
        current_a=np.array([0.0, 1.0, 1.0, 0.0]),
        voltage_v=np.array([4.0, 3.9, 3.8, 3.85]),
    )
    assert ref.n_samples == 4
    assert ref.duration_s == 30.0
    assert ref.dt_s() == 10.0
    ov = ref.overlay(max_points=2)
    assert len(ov["t"]) == 2


# -- loader ----------------------------------------------------------------
def test_load_sample_shapes_and_sign():
    spec = get_dataset("demo-synthetic")
    assert sample_path(spec).exists()
    ref = load_sample(spec)
    assert ref.n_samples > 100
    assert ref.time_s.shape == ref.current_a.shape == ref.voltage_v.shape
    assert ref.temperature_c is not None
    # discharge-positive: the sample's first big segment is a discharge (I > 0).
    assert ref.current_a.max() > 0
    # terminal voltage is a single Li-ion cell, not a pack.
    assert 2.5 < ref.voltage_v.max() < 4.3


def test_loader_for_dispatch():
    assert loader_for(get_dataset("demo-synthetic")) is load_generic_csv
    assert loader_for(get_dataset("nasa-pcoe")).__name__ == "load_nasa_mat"


def test_load_generic_csv_sign_flip(tmp_path):
    p = tmp_path / "cell.csv"
    p.write_text(
        "time_s,current_a,voltage_v\n0,1.0,4.0\n10,1.0,3.9\n20,1.0,3.8\n",
        encoding="utf-8",
    )
    ref = load_generic_csv(p, discharge_positive=False, temp_col=None)
    # charge-positive source flipped to discharge-positive convention.
    assert ref.current_a[0] == -1.0


# -- engine ----------------------------------------------------------------
def test_validate_run_metrics_and_overlay():
    ref = load_sample(get_dataset("demo-synthetic"))
    report = validate_run(ref, data_source="test")
    assert isinstance(report, ValidationReport)
    m = report.metrics
    for k in ("rmse", "mae", "max_abs_err", "mean_bias"):
        assert np.isfinite(m[k])
    # The model should track the synthetic cell to well within 100 mV nominal.
    assert m["rmse"] < 0.1
    # overlay is downsampled and aligned.
    assert len(report.overlay["t"]) <= 400
    assert len(report.overlay["v_measured"]) == len(report.overlay["v_model"])


def test_validate_run_fit_improves_or_matches():
    ref = load_sample(get_dataset("demo-synthetic"))
    report = validate_run(ref, fit=True)
    assert report.fitted is not None
    # Fitting the two most sensitive knobs never does worse than nominal.
    assert report.fitted["metrics"]["rmse"] <= report.metrics["rmse"] + 1e-9
    # The sample was generated at R0=25 mOhm; the fit should land near it.
    assert 0.020 <= report.fitted["r0_ohm"] <= 0.030
    assert "v_model_fitted" in report.overlay


def test_report_to_dict_is_json_shaped():
    ref = load_sample(get_dataset("demo-synthetic"))
    d = validate_run(ref, fit=True).to_dict()
    assert set(["dataset_id", "metrics", "overlay", "params", "fitted"]).issubset(d)
    assert isinstance(d["metrics"]["rmse"], float)


# -- chemistry-specific OCV -------------------------------------------------
def test_ocv_table_registry_and_key_resolution():
    from simura.sim import OCV_TABLES, chemistry_key_for, ocv_table_for

    assert set(["NMC", "LFP", "LCO", "NCA"]).issubset(OCV_TABLES)
    # compound labels resolve to the first recognized (primary) chemistry.
    assert chemistry_key_for("NMC/LCO") == "NMC"
    assert chemistry_key_for("NMC-LCO") == "NMC"
    assert chemistry_key_for("LFP") == "LFP"
    assert chemistry_key_for("unobtainium") is None
    # unknown chemistry falls back to the NMC table (not an error).
    assert ocv_table_for("unobtainium") is OCV_TABLES["NMC"]


def test_ocv_tables_are_strictly_increasing():
    # inverse SoC-from-OCV needs strictly increasing OCV; also physically sane.
    from simura.sim import OCV_TABLES

    for name, table in OCV_TABLES.items():
        socs = [s for s, _ in table]
        ocvs = [v for _, v in table]
        assert socs == sorted(socs), f"{name} SoC not sorted"
        assert all(b > a for a, b in zip(ocvs, ocvs[1:])), f"{name} OCV not strictly increasing"


def test_lfp_validates_clean_with_lfp_curve_bad_with_nmc():
    """The whole point: an LFP cell needs the LFP OCV curve to validate cleanly."""
    ref = load_sample(get_dataset("demo-synthetic-lfp"))
    assert 3.0 < ref.voltage_v.max() < 3.7  # LFP voltage range, not NMC

    # Auto-selects the LFP curve from ref.chemistry.
    good = validate_run(ref, fit=True)
    assert good.ocv_curve == "LFP"
    assert good.metrics["rmse"] < 0.06

    # Forcing the wrong (NMC) curve is badly off, and fitting R0/SoC can't rescue it.
    bad = validate_run(ref, chemistry="NMC", fit=True)
    assert bad.ocv_curve == "NMC"
    assert bad.metrics["rmse"] > 0.15
    assert bad.fitted["metrics"]["rmse"] > 0.10
    assert bad.metrics["rmse"] > 3 * good.metrics["rmse"]


def test_synthetic_for_matches_chemistry():
    from simura.validate import synthetic_for

    assert synthetic_for("LFP").id == "demo-synthetic-lfp"
    assert synthetic_for(get_dataset("stanford-tri").chemistry).id == "demo-synthetic-lfp"
    # no bundled LCO sample -> falls back to the NMC demo.
    assert synthetic_for("LCO").id == "demo-synthetic"


# -- uploads (the pure dispatcher behind /api/validation/upload) ------------
def test_load_upload_generic_columns_and_scale(tmp_path):
    from simura.validate import load_upload

    p = tmp_path / "cell.csv"
    # custom column names, current in mA, charge logged positive.
    p.write_text(
        "sec,amp_mA,volt\n0,0,4.02\n10,5000,3.90\n20,5000,3.85\n30,-4000,3.95\n",
        encoding="utf-8",
    )
    ref = load_upload(
        p,
        chemistry="NMC",
        time_col="sec",
        current_col="amp_mA",
        voltage_col="volt",
        temp_col=None,
        discharge_positive=True,
        current_scale=0.001,
    )
    assert ref.n_samples == 4
    assert ref.chemistry == "NMC"
    assert ref.current_a.max() == 5.0      # 5000 mA * 0.001
    assert ref.current_a.min() == -4.0     # charge stays negative


def test_load_upload_dataset_dispatch_sets_chemistry(tmp_path):
    from simura.validate import load_upload, validate_run

    # A stanford-tri (generic_csv loader) upload defaults chemistry to LFP, so the
    # LFP OCV curve is selected downstream.
    p = tmp_path / "lfp.csv"
    p.write_text(
        "time_s,current_a,voltage_v\n0,0,3.42\n10,5,3.30\n20,5,3.29\n30,0,3.33\n",
        encoding="utf-8",
    )
    ref = load_upload(p, dataset_id="stanford-tri")
    assert ref.chemistry == "LFP"
    assert validate_run(ref).ocv_curve == "LFP"


def test_load_upload_bad_columns_raises(tmp_path):
    from simura.validate import load_upload

    p = tmp_path / "x.csv"
    p.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_upload(p)  # default columns time_s/current_a/voltage_v absent
