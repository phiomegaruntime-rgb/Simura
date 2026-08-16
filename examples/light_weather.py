"""Weather-coupled lighting: the sky decides how much light you have to make.

Weather reaches a luminaire through two entirely separate channels, and this
script shows both:

1. **Thermally** -- ambient temperature moves light output in *opposite*
   directions depending on the technology. A fluorescent tube near freezing
   loses more than half its output (ambient sets the mercury vapour pressure); a
   cold LED gets brighter (the junction runs cooler). That single fact decided
   what went into every unheated warehouse in the last decade.
2. **Optically** -- daylight already on the task is light the fitting does not
   have to supply. A photocell switches a street light against the real sunset,
   and a daylight-linked dimmer holds a constant desk illuminance while the sky
   does most of the work.

Runs offline against a synthetic diurnal cycle. Point it at a real place with
``--live`` and it uses Open-Meteo (free, no API key).

Usage:
    python examples/light_weather.py
    python examples/light_weather.py --live --lat 51.5 --lon -0.13
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Windows consoles default to cp1252; force UTF-8 so the units never crash it.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from simura.lights import (  # noqa: E402
    ConstantDrive,
    DaylightHarvesting,
    Schedule,
    Light,
    LightSimConfig,
    LightSimulator,
    LightSpec,
    PhotocellControl,
)
from simura.weather import SyntheticProvider  # noqa: E402

# Start at midnight so the simulation clock and the wall clock agree — a
# schedule that says "on at seven" then really means seven in the morning.
# The spring equinox, for a day that is neither the best nor the worst case.
EPOCH0 = 1710892800.0          # 2024-03-20 00:00 UTC


def weather_source(args):
    """A real place if asked for, otherwise a deterministic synthetic day."""
    if args.live:
        from simura.weather import OpenMeteoProvider

        print(f"Fetching live weather for {args.lat:.3f}, {args.lon:.3f} …\n")
        return OpenMeteoProvider(latitude=args.lat, longitude=args.lon), None
    return (
        SyntheticProvider(
            mean_temp_c=args.ambient, temp_amplitude_c=8.0,
            wind_mean_ms=3.0, solar_peak_w_m2=750.0,
        ),
        EPOCH0,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Weather-coupled lighting.")
    ap.add_argument("--live", action="store_true", help="use live Open-Meteo weather")
    ap.add_argument("--lat", type=float, default=51.5074)
    ap.add_argument("--lon", type=float, default=-0.1278)
    ap.add_argument("--ambient", type=float, default=6.0,
                    help="mean ambient for the synthetic day (°C)")
    args = ap.parse_args()

    print("1) The same ambient, two technologies, opposite answers")
    print("=" * 70)
    print(f"  {'ambient':>9}{'T8 fluorescent':>18}{'15 W LED':>16}")
    print("  " + "-" * 45)
    for ambient in (-15.0, -5.0, 5.0, 15.0, 25.0, 35.0, 45.0):
        out = []
        for lamp_id in ("fl-t8-36", "led-15-e27"):
            light = Light(LightSpec(lamp_type=lamp_id))
            light.time_lit_s = 1e9
            flux = light.operating_point(1.0, ambient).luminous_flux_lm
            ref = light.operating_point(1.0, 25.0).luminous_flux_lm
            out.append(f"{flux:>7.0f} lm ({flux / ref * 100:>3.0f}%)")
        print(f"  {ambient:>7.0f}°C{out[0]:>18}{out[1]:>16}")
    print("\n  A tube in an unheated space at -5 °C delivers barely half its rated")
    print("  output. The LED beside it delivers slightly more than rated.")

    weather, epoch0 = weather_source(args)

    print("\n\n2) A street light on a photocell, over 24 hours")
    print("=" * 70)
    sim = LightSimulator(
        spec=LightSpec(lamp_type="hps-150-e40"),
        sim_config=LightSimConfig(dt_s=1800.0, duration_s=86400.0, mounting_height_m=8.0),
        profile=ConstantDrive(1.0),
        weather=weather,
        control=PhotocellControl(switch_on_lux=55.0),
        weather_epoch0=epoch0,
    )
    frames = sim.run_to_list()
    print(f"  {'time':>7}{'daylight':>12}{'lamp':>8}{'power':>9}{'on road':>10}")
    print("  " + "-" * 46)
    for f in frames[::2]:
        stamp = datetime.fromtimestamp(
            (epoch0 or 0) + f.time_s, timezone.utc
        ).strftime("%H:%M") if epoch0 else f"{f.time_s / 3600:.1f}h"
        print(
            f"  {stamp:>7}{f.daylight_lux or 0:>10.0f}lx"
            f"{'ON' if f.lit else 'off':>8}{f.input_power_w:>8.0f}W"
            f"{f.illuminance_lux:>9.0f}lx"
        )

    on_hours = sum(1 for f in frames if f.lit) * 0.5
    energy = sum(f.input_power_w for f in frames) * 1800.0 / 3_600_000.0
    print(f"\n  Lit for {on_hours:.1f} h, {energy:.2f} kWh. A timeclock set for the")
    print("  same job would have to be reset every few weeks; the photocell just")
    print("  follows the sun.")

    print("\n\n3) A daylit office, dimming against the sky")
    print("=" * 70)

    # A 07:00-19:00 working day. The schedule decides whether the lights are on;
    # the daylight sensor decides how bright — which is how these are really built.
    office_hours = Schedule(start_s=7 * 3600.0, on_s=12 * 3600.0, period_s=86400.0)

    def office_energy(control) -> tuple[float, list]:
        sim = LightSimulator(
            spec=LightSpec(lamp_type="led-100-flood"),
            sim_config=LightSimConfig(
                dt_s=1800.0, duration_s=86400.0, mounting_height_m=2.5, target_lux=500.0
            ),
            profile=office_hours,
            weather=weather,
            coupling=_indoor_coupling(),
            control=control,
            weather_epoch0=epoch0,
        )
        frames = sim.run_to_list()
        return sum(f.input_power_w for f in frames) * 1800.0 / 3_600_000.0, frames

    scheduled_only, _ = office_energy(None)
    harvested, frames = office_energy(
        DaylightHarvesting(target_lux=500.0, full_output_lux=520.0)
    )

    print(f"  {'time':>7}{'daylight':>12}{'dim':>7}{'power':>9}{'total':>10}")
    print("  " + "-" * 46)
    for f in frames[12:40:2]:
        stamp = datetime.fromtimestamp(
            (epoch0 or 0) + f.time_s, timezone.utc
        ).strftime("%H:%M") if epoch0 else f"{f.time_s / 3600:.1f}h"
        print(
            f"  {stamp:>7}{f.daylight_lux or 0:>10.0f}lx{f.drive * 100:>6.0f}%"
            f"{f.input_power_w:>8.0f}W{f.illuminance_lux:>9.0f}lx"
        )

    saving = (1 - harvested / scheduled_only) * 100 if scheduled_only else 0.0
    print(f"\n  Schedule only     : {scheduled_only:.2f} kWh")
    print(f"  + daylight linked : {harvested:.2f} kWh   ({saving:.0f}% less)")
    print("\n  That saving is not an assumption — it is what this sky, over this")
    print("  place, on this day, actually delivered through the windows.")
    print("\n  Read it as the best case, though. This is one sensor at one")
    print("  well-daylit perimeter desk, and it says the electric light can stay")
    print("  off all day. A whole floorplate has a dim core that no amount of")
    print("  daylight reaches, and its real saving is a fraction of this one.")


def _indoor_coupling():
    """An indoor luminaire beside a window: no wind, no sun on the housing.

    The 0.035 is a *daylight factor*, not a glass transmission — the share of the
    exterior horizontal illuminance that actually lands on a perimeter desk once
    the window's size, frame, glazing and the room's depth are accounted for.
    A generous but realistic figure for a well-daylit workspace.
    """
    from simura.lights import LightEnvironmentCoupling

    return LightEnvironmentCoupling(outdoor=False, window_transmission=0.035)


if __name__ == "__main__":
    main()
