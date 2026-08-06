"""Weather coupling demo: the same pack, run under different environments.

Shows how :mod:`celltwin.weather` drives the pack's ambient temperature, wind
cooling, and solar heat load through the environmental coupling
(:mod:`celltwin.sim.environment`). A resting pack simply drifts toward whatever
ambient the weather source dictates -- warm in the afternoon, cold before dawn.

Fully offline and deterministic (synthetic diurnal model). Run::

    python examples/weather_demo.py
"""

from __future__ import annotations

import calendar
import sys

from celltwin.builder import ProfileSpec, SystemSpec, WeatherSpec, preview
from celltwin.sim import ConstantCurrent, PackConfig, SimConfig, Simulator
from celltwin.weather import SyntheticProvider


def _reconfigure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def epoch(hour: int) -> float:
    """Unix epoch for 2024-01-01 at the given UTC hour."""
    return float(calendar.timegm((2024, 1, 1, hour, 0, 0, 0, 0, 0)))


def run_rest(epoch0: float) -> list:
    """A resting 3-cell pack for 4 hours under a synthetic diurnal climate."""
    cfg = PackConfig(series=3, parallel=1, ambient_temp_c=25.0)
    sim_cfg = SimConfig(dt_s=10.0, duration_s=4 * 3600.0)
    weather = SyntheticProvider(mean_temp_c=20.0, temp_amplitude_c=12.0, tz_offset_h=0.0)
    sim = Simulator(cfg, sim_cfg, ConstantCurrent(0.0), weather=weather, weather_epoch0=epoch0)
    return sim.run_to_list()


def main() -> int:
    _reconfigure_stdout()

    print("A resting pack tracks whatever ambient the weather dictates")
    print("-" * 62)
    print(f"{'start of run':<18}{'start ambient':>14}{'end cell temp':>15}{'end ambient':>13}")
    for label, hour in [("afternoon (15:00)", 15), ("pre-dawn (03:00)", 3)]:
        frames = run_rest(epoch(hour))
        first, last = frames[0], frames[-1]
        print(
            f"{label:<18}{first.weather['air_temp_c']:>12.1f} C"
            f"{last.max_temp_c:>13.2f} C{last.weather['air_temp_c']:>11.1f} C"
        )

    print("\nSame system via the builder + offline preview (LFP, cycling, synthetic weather)")
    print("-" * 62)
    spec = SystemSpec(
        system_id="wx-lfp-16s4p",
        name="Weather-coupled LFP",
        chemistry="LFP",
        series=16,
        parallel=4,
        dt_s=2.0,
        duration_s=8 * 3600.0,
        profile=ProfileSpec("cycle", {"discharge_a": 40.0, "charge_a": 30.0}),
        weather=WeatherSpec("synthetic", {"mean_temp_c": 32.0, "temp_amplitude_c": 10.0, "tz_offset_h": 2.0}),
    )
    r = preview(spec)
    print(f"weather source     : {r.weather_type}")
    print(f"ambient range      : {r.min_ambient_c:.1f} .. {r.max_ambient_c:.1f} C")
    print(f"peak solar         : {r.max_solar_w_m2:.0f} W/m^2")
    print(f"peak cell temp     : {r.peak_temp_c:.1f} C (limit {r.temp_limit_c:.0f} C)")
    print(f"temp limit reached : {r.temp_limit_exceeded}")

    print("\nGo live with real weather for a location (Open-Meteo, no API key):")
    print("  spec.weather = WeatherSpec('open_meteo', {'latitude': 34.05, 'longitude': -118.24})")
    print("  python -m celltwin.publisher --spec wx-lfp-16s4p.json --speed 60 --loop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
