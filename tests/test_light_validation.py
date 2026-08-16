"""Tests for the lighting-model validator. Fully offline and deterministic.

The bundled standards need no network. The *live* daylight validation does, so
its provider is injected here with a saved Open-Meteo payload -- the same seam
:class:`~simura.weather.providers.OpenMeteoProvider` exposes everywhere else --
and no request is ever made.
"""

from __future__ import annotations

import math

import pytest

from simura.lights.validation import (
    QUANTITIES,
    UPLOAD_QUANTITIES,
    LightReference,
    LightRefRow,
    get_standard,
    list_standards,
    load_upload_csv,
    validate_daylight_live,
    validate_reference,
)
from simura.lights.validation.live import CLEAR_KT, MIN_ELEVATION_DEG
from simura.weather.providers import OpenMeteoProvider


# -- the standards catalog -------------------------------------------------
def test_every_standard_is_documented_and_runnable():
    standards = list_standards()
    assert len(standards) >= 5
    for s in standards:
        assert s.quantity in QUANTITIES
        assert s.citation and s.license and s.what_it_validates
        assert s.to_dict()["n_points"] >= 2
        # Every one must actually run.
        report = validate_reference(s.reference())
        assert report.n_points == s.to_dict()["n_points"]


def test_standards_cover_the_model_at_different_depths():
    quantities = {s.quantity for s in list_standards()}
    # The observer, the colour maths, the whole lamp, and both derating laws.
    assert {
        "photopic_response",
        "color_temperature",
        "luminous_efficacy",
        "flux_vs_junction_temp",
        "flux_vs_ambient_temp",
    } <= quantities


def test_unknown_standard_lists_the_known_ones():
    with pytest.raises(KeyError, match="lamp-efficacy-published"):
        get_standard("no-such-standard")


# -- what the model actually scores ----------------------------------------
def test_planckian_locus_is_reproduced_closely():
    """An exact reference: a blackbody's CCT is its own temperature, by definition.

    Every kelvin of error here is the model's own, accumulated through the
    spectral integration, the tristimulus transform and McCamy's approximation.
    """
    report = validate_reference(get_standard("blackbody-cct-locus").reference())
    assert report.metrics["rmse_pct"] < 2.0
    assert abs(report.metrics["mean_bias_pct"]) < 1.5


def test_photopic_fit_is_accurate_in_absolute_terms():
    """V(lambda) against the tabulated CIE observer.

    Judged in absolute units, not percent: the curve passes through ~0.0004 in the
    far violet, where any error at all is a huge relative one. That is exactly why
    the report carries both.
    """
    report = validate_reference(get_standard("cie-photopic-1931").reference())
    assert report.metrics["rmse"] < 0.01        # absolute, on a 0..1 curve
    assert report.metrics["max_abs"] < 0.02
    # And the relative error is large, precisely because of the tails.
    assert report.metrics["max_abs_pct"] > report.metrics["mae_pct"]


def test_whole_lamp_efficacy_is_predicted_across_every_family():
    report = validate_reference(get_standard("lamp-efficacy-published").reference())
    assert report.n_points >= 18
    assert report.metrics["rmse_pct"] < 12.0
    assert abs(report.metrics["mean_bias_pct"]) < 6.0


def test_derating_curves_are_reproduced():
    for standard_id in ("led-junction-derating", "fluorescent-ambient-response"):
        report = validate_reference(get_standard(standard_id).reference())
        assert report.metrics["rmse_pct"] < 15.0


def test_report_carries_both_absolute_and_relative_metrics():
    report = validate_reference(get_standard("lamp-efficacy-published").reference())
    for key in ("rmse", "mae", "max_abs", "mean_bias",
                "rmse_pct", "mae_pct", "max_abs_pct", "mean_bias_pct"):
        assert key in report.metrics


def test_overlay_lines_up_with_the_reference():
    spec = get_standard("blackbody-cct-locus")
    report = validate_reference(spec.reference())
    o = report.overlay
    assert len(o["x"]) == len(o["published"]) == len(o["model"]) == report.n_points
    for i in range(report.n_points):
        assert o["error"][i] == pytest.approx(o["model"][i] - o["published"][i], abs=1e-4)


def test_unknown_quantity_is_rejected():
    ref = LightReference(
        standard_id="bogus",
        quantity="vibes",
        rows=[LightRefRow("a", 1.0, 1.0), LightRefRow("b", 2.0, 2.0)],
    )
    with pytest.raises(ValueError, match="vibes"):
        validate_reference(ref)


def test_a_reference_needs_at_least_two_points():
    with pytest.raises(ValueError):
        LightReference(standard_id="x", quantity="luminous_efficacy",
                       rows=[LightRefRow("a", 1.0, 1.0)])


# -- user uploads ----------------------------------------------------------
def test_upload_measured_efficacy(tmp_path):
    csv = tmp_path / "measured.csv"
    csv.write_text(
        "lamp_id,x,value\n"
        "led-9-e27,9,88.0\n"
        "led-15-e27,15,99.5\n"
        "fl-t8-36,39,84.0\n",
        encoding="utf-8",
    )
    ref = load_upload_csv(csv, quantity="luminous_efficacy", key_col="lamp_id")
    assert ref.data_source == "user-upload" and ref.n_points == 3
    report = validate_reference(ref)
    assert report.data_source == "user-upload"
    assert report.metrics["rmse_pct"] < 30.0


def test_upload_renormalises_a_relative_curve(tmp_path):
    """A file normalised elsewhere must not be reported as error.

    These values are percentages *and* normalised at 40 C rather than 25 C. Both
    get corrected, so what is compared is the shape rather than the convention.
    """
    csv = tmp_path / "derating.csv"
    csv.write_text(
        "x,value\n25,103.0\n40,100.0\n55,97.0\n70,94.0\n85,91.0\n",
        encoding="utf-8",
    )
    ref = load_upload_csv(csv, quantity="flux_vs_junction_temp")
    at_25 = next(r.published for r in ref.rows if r.x == 25.0)
    assert at_25 == pytest.approx(1.0, abs=1e-9)
    report = validate_reference(ref)
    assert report.metrics["mae_pct"] < 10.0


def test_upload_efficacy_without_a_lamp_id_column_is_refused(tmp_path):
    csv = tmp_path / "bad.csv"
    csv.write_text("x,value\n9,88\n15,99\n", encoding="utf-8")
    with pytest.raises(ValueError, match="key_col"):
        load_upload_csv(csv, quantity="luminous_efficacy")


def test_upload_rejects_unknown_quantity_and_missing_columns(tmp_path):
    csv = tmp_path / "x.csv"
    csv.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown quantity"):
        load_upload_csv(csv, quantity="brightness")
    with pytest.raises(ValueError, match="not in"):
        load_upload_csv(csv, quantity="photopic_response", x_col="nm", value_col="v")


def test_upload_needs_two_usable_rows(tmp_path):
    csv = tmp_path / "thin.csv"
    csv.write_text("x,value\n555,1.0\nnonsense,oops\n", encoding="utf-8")
    with pytest.raises(ValueError, match="at least two"):
        load_upload_csv(csv, quantity="photopic_response")


def test_every_upload_quantity_is_one_the_engine_knows():
    assert set(UPLOAD_QUANTITIES) <= set(QUANTITIES)


# -- the live daylight validation (no network) -----------------------------
class _FakeOpenMeteo(OpenMeteoProvider):
    """An Open-Meteo provider fed from a synthetic payload instead of the network.

    Overrides only :meth:`_fetch`, which is the seam the real provider exposes for
    exactly this -- so everything under test is the production parsing and
    validation path.
    """

    def __init__(self, payload: dict, **kw) -> None:
        super().__init__(latitude=51.5, longitude=-0.13, **kw)
        self._payload = payload

    def _fetch(self) -> dict:
        return self._payload


def _clear_sky_payload(start_epoch: float, hours: int, clear_frac: float = 1.0) -> dict:
    """Hourly irradiance that follows the model's own clear-sky curve.

    Scaling it by ``clear_frac`` simulates uniform cloud, so the test can check
    that the report separates the model's error from the weather's.
    """
    from datetime import datetime, timezone

    from simura.lights.environment import clear_sky_ghi_w_m2, solar_elevation_deg

    times, temps, winds, solar, humidity = [], [], [], [], []
    for i in range(hours):
        ts = start_epoch + i * 3600.0
        elevation = solar_elevation_deg(51.5, -0.13, ts)
        times.append(
            datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M")
        )
        temps.append(12.0)
        winds.append(2.0)
        solar.append(clear_sky_ghi_w_m2(elevation) * clear_frac)
        humidity.append(70.0)
    return {
        "hourly": {
            "time": times,
            "temperature_2m": temps,
            "wind_speed_10m": winds,
            "shortwave_radiation": solar,
            "relative_humidity_2m": humidity,
        }
    }


# A midsummer day over London, so the window is guaranteed to contain daylight.
_NOON = 1718971200.0
_START = _NOON - 36 * 3600.0


def test_live_validation_is_near_exact_under_a_clear_sky():
    """Fed its own clear-sky curve, the model must reproduce it almost exactly.

    This is the control: it isolates the geometry and the efficacy constant from
    the weather, and any error is a bug in the pipeline rather than a cloud.
    """
    provider = _FakeOpenMeteo(_clear_sky_payload(_START, 72))
    report = validate_daylight_live(
        51.5, -0.13, hours=48, provider=provider, now_epoch=_NOON + 12 * 3600.0
    )
    assert report.n_hours > 10
    assert report.metrics["rmse_pct"] < 1.0
    assert report.metrics["mean_clearness_index"] == pytest.approx(1.0, abs=0.02)
    assert report.envelope_violations == 0


def test_live_validation_separates_cloud_from_model_error():
    """Under uniform cloud the all-hours error is large and no hour reads as clear.

    That is the point of splitting the metrics: the model has not got worse, the
    sky has. A report that conflated the two would look like a broken model every
    overcast day.
    """
    provider = _FakeOpenMeteo(_clear_sky_payload(_START, 72, clear_frac=0.45))
    report = validate_daylight_live(
        51.5, -0.13, hours=48, provider=provider, now_epoch=_NOON + 12 * 3600.0
    )
    assert report.metrics["mean_clearness_index"] == pytest.approx(0.45, abs=0.02)
    assert report.n_clear_hours == 0            # nothing above the clear threshold
    assert report.metrics["rmse_pct"] > 50.0    # clear-sky over-predicts cloud
    assert report.metrics["mean_bias_lux"] > 0  # and always in that direction


def test_live_validation_flags_measurements_above_the_clear_sky_ceiling():
    provider = _FakeOpenMeteo(_clear_sky_payload(_START, 72, clear_frac=1.4))
    report = validate_daylight_live(
        51.5, -0.13, hours=48, provider=provider, now_epoch=_NOON + 12 * 3600.0
    )
    assert report.envelope_violations > 0


def test_live_validation_ignores_night_and_twilight():
    provider = _FakeOpenMeteo(_clear_sky_payload(_START, 72))
    report = validate_daylight_live(
        51.5, -0.13, hours=48, provider=provider, now_epoch=_NOON + 12 * 3600.0
    )
    assert all(e >= MIN_ELEVATION_DEG for e in report.overlay["elevation_deg"])
    assert all(v > 0 for v in report.overlay["model_lux"])


def test_live_validation_needs_daylight_in_the_window():
    """Polar night is not a model failure, and must not be reported as one."""
    provider = _FakeOpenMeteo(_clear_sky_payload(_START, 72))
    with pytest.raises(ValueError, match="daylight"):
        validate_daylight_live(
            85.0, 0.0, hours=24, provider=provider,
            now_epoch=_NOON - 182 * 86400.0,     # midwinter above the Arctic circle
        )


def test_clear_threshold_is_what_the_report_uses():
    provider = _FakeOpenMeteo(_clear_sky_payload(_START, 72, clear_frac=0.9))
    report = validate_daylight_live(
        51.5, -0.13, hours=48, provider=provider, now_epoch=_NOON + 12 * 3600.0
    )
    expected = sum(1 for kt in report.overlay["clearness_index"] if kt >= CLEAR_KT)
    assert report.n_clear_hours == expected


def test_live_report_serializes():
    provider = _FakeOpenMeteo(_clear_sky_payload(_START, 72))
    report = validate_daylight_live(
        51.5, -0.13, hours=48, provider=provider, now_epoch=_NOON + 12 * 3600.0
    )
    d = report.to_dict()
    assert d["source"] == "open-meteo"
    assert len(d["overlay"]["measured_lux"]) == d["n_hours"]
    assert math.isfinite(d["metrics"]["rmse_lux"])
