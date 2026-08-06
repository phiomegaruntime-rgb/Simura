# Weather

Real batteries don't live in a temperature-controlled lab. A rack in an outdoor
cabinet bakes in the afternoon sun, sheds heat on a windy night, and cools toward
whatever the air temperature is. The **weather** layer adds that environment to
the twin: it drives the pack's ambient temperature, convective cooling, and solar
heat load from a real (or synthetic) weather source.

It is built as a **standalone, domain-agnostic package** (`celltwin.weather`) that
knows nothing about batteries — so it can be reused in any project where the
environment drives a system's behaviour. The battery-specific translation is a
thin adapter in `celltwin.sim.environment`.

## Providers

Everything implements one tiny interface — `WeatherProvider.at(timestamp)` returns
a `WeatherSample` (air temperature, wind speed, solar irradiance, humidity) for a
Unix-epoch instant:

| Provider | Use it for |
| --- | --- |
| `StaticProvider` | Constant conditions — the "no variation" baseline. |
| `SyntheticProvider` | A deterministic diurnal cycle. Offline, reproducible — the default for tests, CI, and previews. |
| `CsvReplayProvider` | Replay a downloaded or hand-authored weather CSV, interpolated by timestamp. |
| `OpenMeteoProvider` | Live / forecast / historical data from the free [Open-Meteo](https://open-meteo.com) API — **no API key required**. |
| `CachedProvider` | Wraps a live source: caches by time bucket and **falls back to an offline model on any error**, so a network blip never crashes a run. |

```python
from celltwin.weather import SyntheticProvider

wx = SyntheticProvider(mean_temp_c=22, temp_amplitude_c=10, tz_offset_h=1)
sample = wx.at(1_704_110_400)          # 2024-01-01 12:00 UTC
print(sample.air_temp_c, sample.solar_w_m2, sample.wind_speed_ms)
```

## How weather affects the pack

The pack's thermal model already has one environmental input — the ambient it
cools toward. The coupling (`celltwin.sim.environment.EnvironmentCoupling`) maps a
weather sample onto **three physical levers**:

| Weather variable | Effect on the pack |
| --- | --- |
| **Air temperature** | The ambient the pack cools toward (`T_amb`). |
| **Wind speed** | A multiplier on convective cooling conductance (`k_cool`). |
| **Solar irradiance** | An added heat load on each sun-exposed cell. |

The coupling coefficients (wind-cooling gain, solar absorptivity, exposed area per
cell, shading) are **illustrative** — a plausible generic outdoor enclosure, not a
calibrated CFD model, exactly like the nominal `k_cool` and the OCV tables. They
are all parameters you can tune per deployment.

!!! note "A resting pack tracks ambient"
    With no load, a pack simply drifts toward the weather's air temperature —
    warm in the afternoon, cold before dawn. Under load, the environment sets the
    baseline that the pack's own ohmic and solar heating build on top of.

## Adding weather to a system

Weather is an optional, declarative part of a `SystemSpec` — a `WeatherSpec` with a
`type` and provider `params`. `type="none"` (the default) keeps the fixed
`ambient_temp_c`, so existing specs are unchanged.

```python
from celltwin.builder import SystemSpec, ProfileSpec, WeatherSpec, preview

spec = SystemSpec(
    name="Outdoor LFP rack", chemistry="LFP", series=16, parallel=4,
    profile=ProfileSpec("cycle", {"discharge_a": 40, "charge_a": 30}),
    # Deterministic diurnal climate, offline:
    weather=WeatherSpec("synthetic", {"mean_temp_c": 32, "temp_amplitude_c": 10, "tz_offset_h": 2}),
)
r = preview(spec)
print(r.weather_type, r.min_ambient_c, r.max_ambient_c, r.max_solar_w_m2)
```

Live weather for a real location (no API key):

```python
spec.weather = WeatherSpec("open_meteo", {"latitude": 34.05, "longitude": -118.24})
```

The **offline preview** always substitutes a synthetic stand-in for live sources,
so it never makes a network call and stays reproducible. To see *real* conditions,
run the system live — start it in the fleet from the dashboard, or stream it:

```bash
python -m celltwin.publisher --spec my-system.json --speed 60 --loop
```

A twin-core-run simulation performs the live provider's first fetch **off the
event loop**, and every telemetry frame carries the `weather` conditions it ran
under (visible in the dashboard's system view).

## CLI

Sample any provider over a window of hours:

```bash
python -m celltwin.weather --synthetic --hours 24
python -m celltwin.weather --open-meteo --lat 52.52 --lon 13.41 --hours 12
```

## Honest limits

- Coupling coefficients are illustrative, not fitted to a specific enclosure.
- Open-Meteo is best-effort external data; wrapped in `CachedProvider`, a run
  **degrades gracefully** to the offline model rather than failing.
- Live weather conditions are shown on live telemetry but are **not persisted to
  history** (no schema change) in this release.
