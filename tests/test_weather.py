"""Tests for the weather subpackage and its coupling to the battery pack.

Everything here is fully offline: the synthetic provider is deterministic, the
Open-Meteo parser is exercised against a saved fixture (no network), and the
end-to-end coupling test proves cell temperatures track a diurnal ambient.
"""

from __future__ import annotations

import calendar

import pytest

from simura.sim import (
    ConstantCurrent,
    EnvironmentCoupling,
    PackConfig,
    SimConfig,
    Simulator,
)
from simura.weather import (
    CachedProvider,
    CsvReplayProvider,
    OpenMeteoProvider,
    StaticProvider,
    SyntheticProvider,
    WeatherSample,
    WeatherSeries,
    build_provider,
    places_from_payload,
    search_places,
)
from simura.weather.providers.open_meteo import _parse_gmt


def _epoch(y=2024, mo=1, d=1, h=12) -> float:
    return float(calendar.timegm((y, mo, d, h, 0, 0, 0, 0, 0)))


# -- sample contract -------------------------------------------------------
def test_weather_sample_roundtrips():
    s = WeatherSample(timestamp=1.0, air_temp_c=20.0, wind_speed_ms=3.0, solar_w_m2=500.0)
    back = WeatherSample.from_dict(s.to_dict())
    assert back == s


def test_from_dict_ignores_unknown_keys():
    s = WeatherSample.from_dict({"timestamp": 1.0, "air_temp_c": 5.0, "bogus": 9})
    assert s.air_temp_c == 5.0


# -- static ----------------------------------------------------------------
def test_static_provider_is_constant():
    p = StaticProvider(air_temp_c=15.0, wind_speed_ms=1.0)
    assert p.at(0).air_temp_c == 15.0
    assert p.at(1e9).air_temp_c == 15.0
    assert p.at(1e9).source == "static"


# -- synthetic -------------------------------------------------------------
def test_synthetic_is_deterministic():
    p = SyntheticProvider(seed=7)
    ts = _epoch(h=14)
    assert p.at(ts) == p.at(ts)


def test_synthetic_diurnal_shape():
    p = SyntheticProvider(mean_temp_c=20, temp_amplitude_c=10, solar_peak_w_m2=800)
    noon = p.at(_epoch(h=12))
    midnight = p.at(_epoch(h=0))
    afternoon = p.at(_epoch(h=15))
    dawn = p.at(_epoch(h=5))
    # Solar zero at night, positive at noon.
    assert noon.solar_w_m2 > 500
    assert midnight.solar_w_m2 == 0.0
    # Temperature peaks in the afternoon, troughs near dawn.
    assert afternoon.air_temp_c > dawn.air_temp_c
    assert dawn.air_temp_c == pytest.approx(10.0, abs=0.5)  # mean - amplitude


def test_synthetic_tz_offset_shifts_solar_noon():
    # With +6h offset, UTC 06:00 becomes local noon -> near-peak solar.
    p = SyntheticProvider(tz_offset_h=6.0, solar_peak_w_m2=800)
    assert p.at(_epoch(h=6)).solar_w_m2 > 700


# -- series interpolation --------------------------------------------------
def test_weather_series_interpolates_and_clamps():
    s = WeatherSeries(
        [
            WeatherSample(timestamp=0.0, air_temp_c=10.0),
            WeatherSample(timestamp=100.0, air_temp_c=20.0),
        ]
    )
    assert s.at(50.0).air_temp_c == pytest.approx(15.0)
    assert s.at(-10.0).air_temp_c == 10.0  # clamp low
    assert s.at(999.0).air_temp_c == 20.0  # clamp high


# -- csv replay ------------------------------------------------------------
def test_csv_replay_provider(tmp_path):
    csv = tmp_path / "wx.csv"
    csv.write_text(
        "timestamp,air_temp_c,wind_speed_ms,solar_w_m2\n"
        "2024-01-01T00:00:00Z,10,2,0\n"
        "2024-01-01T01:00:00Z,12,4,100\n",
        encoding="utf-8",
    )
    p = CsvReplayProvider(str(csv))
    mid = p.at(_epoch(h=0) + 1800)  # halfway between the two rows
    assert mid.air_temp_c == pytest.approx(11.0)
    assert mid.source == "csv"


# -- open-meteo parsing (no network) --------------------------------------
FIXTURE = {
    "latitude": 52.5,
    "longitude": 13.4,
    "hourly": {
        "time": ["2024-01-01T00:00", "2024-01-01T01:00", "2024-01-01T02:00"],
        "temperature_2m": [5.0, 6.0, 7.0],
        "wind_speed_10m": [3.0, 3.5, 4.0],
        "shortwave_radiation": [0.0, 0.0, 10.0],
        "relative_humidity_2m": [80.0, 82.0, 85.0],
    },
}


def test_open_meteo_parses_fixture():
    series = OpenMeteoProvider.from_payload(FIXTURE)
    assert len(series) == 3
    s = series.at(_epoch(h=1))
    assert s.air_temp_c == pytest.approx(6.0)
    assert s.wind_speed_ms == pytest.approx(3.5)
    assert s.humidity_frac == pytest.approx(0.82)  # percent -> fraction
    assert s.source == "open-meteo"


def test_open_meteo_at_uses_injected_fetch(monkeypatch):
    p = OpenMeteoProvider(52.5, 13.4)
    monkeypatch.setattr(p, "_fetch", lambda: FIXTURE)
    assert p.at(_epoch(h=2)).air_temp_c == pytest.approx(7.0)


def test_parse_gmt_naive_is_utc():
    assert _parse_gmt("2024-01-01T00:00") == _epoch(h=0)


def test_open_meteo_rejects_empty_payload():
    with pytest.raises(ValueError):
        OpenMeteoProvider.from_payload({"hourly": {"time": []}})


# -- cache + fallback ------------------------------------------------------
class _Boom:
    def at(self, timestamp):
        raise RuntimeError("network down")


def test_cached_provider_falls_back_on_error():
    fallback = StaticProvider(air_temp_c=99.0)
    p = CachedProvider(_Boom(), fallback=fallback)
    assert p.at(123.0).air_temp_c == 99.0
    assert p.degraded is True


def test_cached_provider_caches_by_bucket():
    calls = {"n": 0}

    class _Counter:
        def at(self, timestamp):
            calls["n"] += 1
            return WeatherSample(timestamp=timestamp, air_temp_c=1.0)

    p = CachedProvider(_Counter(), bucket_s=600.0)
    p.at(0.0)
    p.at(300.0)  # same 600 s bucket -> cached
    assert calls["n"] == 1


# -- config factory --------------------------------------------------------
def test_build_provider_dispatch():
    assert build_provider({"type": "none"}) is None
    assert build_provider(None) is None
    assert isinstance(build_provider({"type": "static", "air_temp_c": 5}), StaticProvider)
    assert isinstance(build_provider({"type": "synthetic"}), SyntheticProvider)


def test_build_provider_open_meteo_is_cached():
    p = build_provider({"type": "open_meteo", "latitude": 1.0, "longitude": 2.0})
    assert isinstance(p, CachedProvider)


def test_build_provider_unknown_raises():
    with pytest.raises(ValueError):
        build_provider({"type": "nope"})


# -- coupling --------------------------------------------------------------
def test_coupling_maps_weather_to_effect():
    c = EnvironmentCoupling(wind_cooling_gain=0.1, solar_absorptivity=0.5,
                            exposed_area_m2_per_cell=0.01)
    eff = c.apply(WeatherSample(timestamp=0, air_temp_c=30, wind_speed_ms=10, solar_w_m2=1000))
    assert eff.ambient_c == 30.0
    assert eff.cooling_mult == pytest.approx(2.0)          # 1 + 0.1*10
    assert eff.solar_heat_w == pytest.approx(0.5 * 1000 * 0.01)  # 5 W


def test_coupling_clamps_and_floors():
    c = EnvironmentCoupling(wind_cooling_gain=1.0, max_cooling_mult=3.0)
    hi = c.apply(WeatherSample(timestamp=0, air_temp_c=20, wind_speed_ms=100))
    assert hi.cooling_mult == 3.0                          # clamped
    calm = c.apply(WeatherSample(timestamp=0, air_temp_c=20, wind_speed_ms=0))
    assert calm.cooling_mult == 1.0                        # floor


# -- end-to-end: cells track the diurnal ambient --------------------------
def _rest_sim(epoch0):
    cfg = PackConfig(series=3, parallel=1, ambient_temp_c=25.0)
    sim_cfg = SimConfig(dt_s=10.0, duration_s=3 * 3600.0)
    wx = SyntheticProvider(mean_temp_c=20, temp_amplitude_c=12, tz_offset_h=0)
    return Simulator(cfg, sim_cfg, ConstantCurrent(0.0), weather=wx, weather_epoch0=epoch0)


def test_cells_follow_ambient_hot_vs_cold_start():
    # A resting pack should drift toward whatever ambient the weather dictates.
    hot = _rest_sim(_epoch(h=15)).run_to_list()   # afternoon peak
    cold = _rest_sim(_epoch(h=3)).run_to_list()    # pre-dawn cold
    # Frames carry the weather that produced them.
    assert hot[0].weather is not None
    assert hot[0].weather["air_temp_c"] > cold[0].weather["air_temp_c"]
    # After a few hours the hot-start pack is warmer than the cold-start pack.
    assert hot[-1].max_temp_c > cold[-1].max_temp_c


def test_no_weather_keeps_fixed_ambient():
    cfg = PackConfig(series=3, parallel=1, ambient_temp_c=25.0)
    sim = Simulator(cfg, SimConfig(dt_s=10.0, duration_s=3600.0), ConstantCurrent(0.0))
    frames = sim.run_to_list()
    assert frames[-1].weather is None
    assert frames[-1].max_temp_c == pytest.approx(25.0, abs=1e-6)


# -- geocoding ("point a site somewhere") -------------------------------------

def test_places_from_payload_parses_and_labels():
    places = places_from_payload(
        {
            "results": [
                {
                    "name": "Berlin",
                    "latitude": 52.52437,
                    "longitude": 13.41053,
                    "country": "Germany",
                    "admin1": "Berlin",
                    "timezone": "Europe/Berlin",
                    "elevation": 74.0,
                }
            ]
        }
    )
    assert len(places) == 1
    p = places[0]
    assert (p.latitude, p.longitude) == pytest.approx((52.52437, 13.41053))
    # The timezone is the point: it's what makes a local clock possible.
    assert p.timezone == "Europe/Berlin"
    assert p.label == "Berlin, Berlin, Germany"
    assert p.to_dict()["label"] == p.label


def test_places_from_payload_tolerates_empty_and_malformed():
    # A query that matches nothing comes back with no "results" key at all.
    assert places_from_payload({}) == []
    assert places_from_payload({"results": []}) == []
    # One bad row must not lose the good ones alongside it.
    places = places_from_payload(
        {
            "results": [
                {"name": "Nowhere"},  # no coordinates
                {"name": "Oslo", "latitude": 59.91, "longitude": 10.75},
            ]
        }
    )
    assert [p.name for p in places] == ["Oslo"]
    assert places[0].label == "Oslo"  # no country/admin1 to append


def test_search_places_short_circuits_a_blank_query():
    """A blank box must not become a network call."""
    assert search_places("   ") == []
