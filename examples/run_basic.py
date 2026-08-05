"""Run a basic simulation and print a telemetry summary.

Usage:
    python examples/run_basic.py            # healthy pack, charge/discharge cycle
    python examples/run_basic.py --fault    # inject an internal short + runaway

No plotting dependencies required; it prints a compact table. Install the
``examples`` extra (matplotlib) if you want to add your own plots.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from a source checkout without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from celltwin.sim import (  # noqa: E402
    ChargeDischargeCycle,
    InternalShort,
    PackConfig,
    SimConfig,
    Simulator,
    ThermalRunaway,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fault", action="store_true", help="inject a fault sequence")
    args = parser.parse_args()

    pack = PackConfig(series=12, parallel=2, initial_soc=0.9)
    sim = SimConfig(dt_s=1.0, duration_s=2400.0)
    profile = ChargeDischargeCycle(discharge_a=20.0, charge_a=15.0)

    faults = []
    if args.fault:
        # A soft internal short in cell (module 3, parallel-slot 0) starting at
        # t=600s, which heats the cell and can trip a thermal runaway.
        faults = [
            InternalShort(cell=(3, 0), r_short_ohm=2.0, start_s=600.0),
            ThermalRunaway(cell=(3, 0), trigger_c=70.0, start_s=600.0),
        ]

    simulator = Simulator(pack, sim, profile, faults)

    print(f"{'t[s]':>6} {'V':>7} {'I[A]':>7} {'SoC':>6} {'Tmax[C]':>8} {'imbal[V]':>9}")
    for i, tel in enumerate(simulator.run()):
        if i % 120 == 0 or i == int(sim.duration_s / sim.dt_s) - 1:
            print(
                f"{tel.time_s:6.0f} {tel.pack_voltage_v:7.2f} {tel.pack_current_a:7.1f} "
                f"{tel.pack_soc:6.3f} {tel.max_temp_c:8.2f} {tel.voltage_imbalance_v:9.4f}"
            )


if __name__ == "__main__":
    main()
