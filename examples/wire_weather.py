"""Weather changes what a conductor can carry -- the basis of dynamic line rating.

The same wire at the same current settles at very different temperatures depending
on the weather. This runs a 14 AWG copper conductor at 25 A (over its ~20 A rating)
under three conditions and shows the steady-state temperature:

1. A still, hot day  -- worst case: no wind to cool it, warm ambient.
2. A windy day       -- forced convection carries the heat away.
3. A sunny still day -- absorbed sunlight adds a heat load on top of I^2*R.

This is the standard conductor heat balance (cf. IEEE Std 738): I^2*R + solar in,
convection out. Weather is coupled through the reusable simura.weather package,
exactly as it is for the battery pack -- the wire model just exposes ambient, a
wind-driven cooling multiplier, and a solar heat load.

Usage:
    python examples/wire_weather.py

Only needs numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from simura.weather import StaticProvider  # noqa: E402
from simura.wires import (  # noqa: E402
    ConstantCurrent,
    WireSimConfig,
    WireSimulator,
    WireSpec,
)

EPOCH = 1_704_110_400.0  # fixed instant so the run is reproducible


def settle(label: str, air_temp_c: float, wind_ms: float, solar: float) -> None:
    weather = StaticProvider(air_temp_c=air_temp_c, wind_speed_ms=wind_ms, solar_w_m2=solar)
    sim = WireSimulator(
        spec=WireSpec(awg=14, length_m=5.0, insulation="THHN-90"),
        sim_config=WireSimConfig(dt_s=1.0, duration_s=2400.0),
        profile=ConstantCurrent(25.0),
        weather=weather,
        weather_epoch0=EPOCH,
    )
    last = sim.run_to_list()[-1]
    verdict = "OVER TEMP" if last.over_temp else "within rating"
    print(
        f"{label:<20} ambient {air_temp_c:>4.0f} C  wind {wind_ms:>3.0f} m/s  "
        f"sun {solar:>4.0f} W/m2  ->  {last.temp_c:6.1f} C  ({verdict})"
    )


def main() -> None:
    print("14 AWG copper, 5 m, carrying 25 A (rating ~20 A):\n")
    settle("still + hot", air_temp_c=40.0, wind_ms=0.0, solar=0.0)
    settle("windy + hot", air_temp_c=40.0, wind_ms=8.0, solar=0.0)
    settle("sunny + still", air_temp_c=25.0, wind_ms=0.0, solar=1000.0)
    settle("windy + sunny", air_temp_c=25.0, wind_ms=8.0, solar=1000.0)
    print(
        "\nSame wire, same current -- the wind pulls tens of degrees off the "
        "conductor while the sun pushes it back up. That spread is exactly why "
        "line ratings are weather-dependent."
    )


if __name__ == "__main__":
    main()
