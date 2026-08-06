"""Tests for the system builder (celltwin.builder).

Pure-library: spec round-tripping, validation, offline preview, and that every
profile/fault type actually builds and runs.
"""

from __future__ import annotations

import pytest

from celltwin.builder import (
    FAULT_TYPES,
    PROFILE_TYPES,
    FaultSpec,
    ProfileSpec,
    SpecError,
    SystemSpec,
    WeatherSpec,
    build_simulator,
    builder_options,
    preview,
    validate_spec,
)


# -- spec serialization ----------------------------------------------------
def test_spec_roundtrips_through_dict():
    s = SystemSpec(
        name="RT",
        chemistry="LFP",
        series=16,
        parallel=4,
        profile=ProfileSpec("constant_current", {"amps": 12.0}),
        faults=[FaultSpec("internal_short", 3, 1, 500.0, {"r_short_ohm": 1.5})],
    )
    back = SystemSpec.from_dict(s.to_dict())
    assert back == s
    assert back.profile.type == "constant_current"
    assert back.faults[0].series == 3 and back.faults[0].params["r_short_ohm"] == 1.5


def test_from_dict_ignores_unknown_keys_and_fills_defaults():
    s = SystemSpec.from_dict({"name": "partial", "bogus": 1, "series": 8})
    assert s.name == "partial"
    assert s.series == 8
    assert s.parallel == 2  # default preserved
    assert s.profile.type == "cycle"


# -- validation ------------------------------------------------------------
def test_default_spec_is_valid():
    assert validate_spec(SystemSpec()) == []
    assert builder_options()["default_spec"]  # non-empty


def test_validation_catches_common_mistakes():
    s = SystemSpec(
        series=0,
        parallel=2,
        capacity_ah=-1.0,
        chemistry="XYZ",
        initial_soc=1.5,
        dt_s=0.0,
        faults=[FaultSpec("internal_short", 9, 0, -5.0)],
    )
    errs = " | ".join(validate_spec(s))
    assert "series must be >= 1" in errs
    assert "capacity_ah must be > 0" in errs
    assert "unknown chemistry" in errs
    assert "initial_soc" in errs
    assert "dt_s must be > 0" in errs
    assert "out of range" in errs  # fault cell


def test_validation_rejects_too_many_steps():
    s = SystemSpec(dt_s=0.001, duration_s=1_000_000.0)
    assert any("exceeds" in e for e in validate_spec(s))


def test_validation_flags_bad_profile_and_fault_types():
    s = SystemSpec(profile=ProfileSpec("teleport", {}), faults=[FaultSpec("levitation", 0, 0, 0)])
    errs = " | ".join(validate_spec(s))
    assert "unknown profile type" in errs
    assert "unknown type 'levitation'" in errs


# -- build + preview -------------------------------------------------------
def test_preview_healthy_summary_is_sane():
    r = preview(SystemSpec())
    assert 0.0 <= r.final_soc <= 1.0
    assert r.peak_temp_c > r.min_pack_voltage_v * 0  # finite/real
    assert r.n_steps == 3600
    assert len(r.sparkline["t"]) <= 200
    assert not r.temp_limit_exceeded  # a healthy NMC cycle stays cool


def test_preview_invalid_spec_raises_specerror():
    with pytest.raises(SpecError) as exc:
        preview(SystemSpec(series=0))
    assert exc.value.errors  # carries the list of problems


def test_preview_lfp_uses_lfp_voltage_range():
    r = preview(SystemSpec(chemistry="LFP", series=16, parallel=4, initial_soc=0.9))
    # 16 LFP cells in series sit well below a 16S NMC pack of the same count.
    assert 40.0 < r.max_pack_voltage_v < 60.0


def test_preview_severe_short_trips_temperature_limit():
    # A hard internal short dumps tens of watts into one cell; it crosses the
    # temperature limit on its own (no runaway needed, so no exp() blow-up).
    s = SystemSpec(
        series=6,
        parallel=1,
        temp_max_c=45.0,
        profile=ProfileSpec("constant_current", {"amps": 5.0}),
        faults=[FaultSpec("internal_short", 2, 0, 100.0, {"r_short_ohm": 0.3})],
    )
    r = preview(s)
    assert r.temp_limit_exceeded
    assert r.time_to_limit_s is not None and r.time_to_limit_s >= 100.0


def test_every_profile_and_fault_type_builds_and_runs():
    for ptype in PROFILE_TYPES:
        s = SystemSpec(duration_s=60.0, profile=ProfileSpec(ptype, {}))
        sim = build_simulator(s)
        frames = [next(sim.run()) for _ in range(1)]
        assert frames and frames[0].pack_voltage_v > 0

    for ftype in FAULT_TYPES:
        s = SystemSpec(
            duration_s=60.0,
            faults=[FaultSpec(ftype, 0, 0, 0.0, {})],
        )
        assert validate_spec(s) == []
        r = preview(s)
        assert r.n_steps == 60


# -- weather integration ---------------------------------------------------
def test_weatherspec_roundtrips_through_dict():
    s = SystemSpec(
        weather=WeatherSpec("synthetic", {"mean_temp_c": 30.0, "tz_offset_h": 2.0})
    )
    back = SystemSpec.from_dict(s.to_dict())
    assert back.weather.type == "synthetic"
    assert back.weather.params["mean_temp_c"] == 30.0


def test_spec_without_weather_defaults_to_none():
    back = SystemSpec.from_dict({"name": "no weather"})
    assert back.weather.type == "none"


def test_preview_with_synthetic_weather_is_reproducible():
    s = SystemSpec(
        dt_s=5.0,
        duration_s=4 * 3600.0,
        profile=ProfileSpec("constant_current", {"amps": 0.0}),
        weather=WeatherSpec("synthetic", {"mean_temp_c": 20.0, "temp_amplitude_c": 10.0}),
    )
    r1 = preview(s)
    r2 = preview(s)
    assert r1.weather_type == "synthetic"
    assert r1.min_ambient_c is not None and r1.max_ambient_c > r1.min_ambient_c
    assert "ambient" in r1.sparkline
    assert r1.peak_temp_c == r2.peak_temp_c  # deterministic (pinned epoch)


def test_open_meteo_spec_validates_coordinates():
    ok = SystemSpec(weather=WeatherSpec("open_meteo", {"latitude": 52.5, "longitude": 13.4}))
    assert validate_spec(ok) == []
    bad = SystemSpec(weather=WeatherSpec("open_meteo", {"latitude": 999}))
    errs = validate_spec(bad)
    assert any("latitude" in e for e in errs)
    assert any("longitude" in e for e in errs)


def test_unknown_weather_type_is_rejected():
    errs = validate_spec(SystemSpec(weather=WeatherSpec("tornado", {})))
    assert any("weather" in e for e in errs)


def test_builder_options_exposes_weather():
    opts = builder_options()
    assert "synthetic" in opts["weather_types"]
    assert "open_meteo" in opts["weather_params"]
