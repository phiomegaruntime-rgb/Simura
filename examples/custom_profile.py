"""Drive the pack with a custom load profile -- a real-ish grid duty cycle.

A load profile is anything with ``current(t, pack_voltage_v) -> amps`` (positive
= discharge). The built-ins (``ConstantCurrent``, ``ConstantPower``,
``ChargeDischargeCycle``, ``sinusoidal``) cover the common cases; this example
shows how little it takes to plug in your own -- here, a simplified daily grid
dispatch: charge midday off cheap/solar power, discharge into the morning and
evening demand peaks, idle overnight.

This is a great "good first area" for contributors: drop in a profile digitized
from a real duty cycle and see how the pack's SoC and temperature respond.

Usage:
    python examples/custom_profile.py

Only needs numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from simura.sim import PackConfig, SimConfig, Simulator  # noqa: E402

# One simulated "day" compressed to 24 * 60 s = 1440 s (a minute per hour) so the
# example runs in a blink. Schedule is (start_hour, end_hour, pack_amps); positive
# discharges, negative charges.
HOURS_S = 60.0  # simulated seconds per "hour"
SCHEDULE: list[tuple[float, float, float]] = [
    (0, 6, 0.0),      # overnight idle
    (6, 9, 18.0),     # morning demand peak (discharge)
    (9, 12, -6.0),    # late-morning top-up (charge)
    (12, 15, -14.0),  # midday solar charge
    (15, 18, 2.0),    # afternoon light load
    (18, 22, 20.0),   # evening peak (heavy discharge)
    (22, 24, 0.0),    # wind down
]


class GridDispatch:
    """A piecewise daily dispatch schedule as a Simura load profile."""

    def __init__(self, schedule: list[tuple[float, float, float]], hour_s: float) -> None:
        self.schedule = schedule
        self.hour_s = hour_s
        self.day_s = 24 * hour_s

    def current(self, t: float, pack_voltage_v: float) -> float:
        hour = (t % self.day_s) / self.hour_s
        for start, end, amps in self.schedule:
            if start <= hour < end:
                return amps
        return 0.0


def main() -> None:
    pack = PackConfig(series=12, parallel=2, initial_soc=0.6)
    sim = SimConfig(dt_s=1.0, duration_s=2 * 24 * HOURS_S)  # two days
    profile = GridDispatch(SCHEDULE, HOURS_S)

    print("Simulated two-day grid dispatch (a minute per hour):\n")
    print(f"{'hour':>5} {'amps':>6} {'V':>7} {'SoC':>6} {'Tmax[C]':>8}")
    print("-" * 36)

    for i, tel in enumerate(Simulator(pack, sim, profile).run()):
        hour_of_day = int((tel.time_s / HOURS_S) % 24)
        # Print once per simulated hour.
        if i % int(HOURS_S) == 0:
            amps = profile.current(tel.time_s, tel.pack_voltage_v)
            print(
                f"{hour_of_day:5d} {amps:6.1f} {tel.pack_voltage_v:7.2f} "
                f"{tel.pack_soc:6.3f} {tel.max_temp_c:8.2f}"
            )


if __name__ == "__main__":
    main()
