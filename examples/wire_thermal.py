"""Watch a wire heat up under load -- and cross its insulation rating.

An undersized conductor doesn't fail instantly; it *heats*. This runs a 14 AWG
copper wire at 25 A (well over its ~20 A rating) and shows the temperature climb
from ambient toward the ``I^2*R / k_cool`` steady state, past the 90 C insulation
limit. Because resistance rises with temperature, the loss climbs too -- the same
positive-feedback that makes over-current wiring dangerous.

Compare with a correctly-sized 10 AWG wire at the same current, which settles well
within its rating.

Usage:
    python examples/wire_thermal.py

Only needs numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from simura.wires import (  # noqa: E402
    ConstantCurrent,
    WireSimConfig,
    WireSimulator,
    WireSpec,
)


def _run(awg: int, current_a: float) -> None:
    sim = WireSimulator(
        spec=WireSpec(awg=awg, length_m=2.0, insulation="THHN-90", ambient_temp_c=25.0),
        sim_config=WireSimConfig(dt_s=1.0, duration_s=900.0),
        profile=ConstantCurrent(current_a),
    )
    frames = sim.run_to_list()
    print(f"\n{awg} AWG copper @ {current_a:.0f} A  (rating {frames[0].temp_rating_c:.0f} C, "
          f"ampacity {frames[0].ampacity_a:.0f} A)")
    print(f"  {'t (s)':>6}{'temp C':>9}{'loss W':>9}{'util %':>8}")
    step = max(1, len(frames) // 8)
    for f in frames[::step]:
        print(f"  {f.time_s:>6.0f}{f.temp_c:>9.1f}{f.power_loss_w:>9.2f}"
              f"{f.ampacity_utilization * 100:>8.0f}")
    last = frames[-1]
    print(f"  settled ~{last.temp_c:.0f} C -> "
          f"{'OVER TEMP' if last.over_temp else 'within rating'}")


def main() -> None:
    print("Thermal transient of a wire under constant current")
    _run(awg=14, current_a=25.0)   # undersized -> overheats
    _run(awg=10, current_a=25.0)   # right-sized -> fine


if __name__ == "__main__":
    main()
