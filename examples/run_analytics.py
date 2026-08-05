"""Run the full intelligence pipeline offline -- no broker, no database.

Drives the physics simulator through a fault scenario and feeds each telemetry
frame through the same pure libraries the ``analytics`` service uses in the live
stack: peer-consensus anomaly detection (Component 4) and diagnosis / state-of-
health / remaining-useful-life / safety (Component 5). It prints a timeline and
then the final assessment, so you can see the twin name the fault *before* the
pack crosses any absolute temperature limit.

Usage:
    python examples/run_analytics.py                 # internal short (default)
    python examples/run_analytics.py --scenario healthy
    python examples/run_analytics.py --scenario cooling

Only needs numpy -- the detection and health engines are pure libraries.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from a source checkout without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from celltwin.detect import AnomalyEngine  # noqa: E402
from celltwin.health import AssessmentEngine  # noqa: E402
from celltwin.sim import (  # noqa: E402
    ChargeDischargeCycle,
    CoolingFault,
    InternalShort,
    PackConfig,
    ResistanceGrowth,
    SimConfig,
    Simulator,
)

SCENARIOS = {
    "healthy": [],
    "short": [InternalShort(cell=(3, 0), r_short_ohm=2.0, start_s=600.0)],
    "cooling": [CoolingFault(cell=(3, 0), effectiveness=0.2, start_s=600.0)],
    "resistance": [ResistanceGrowth(cell=(3, 0), multiplier=3.0, start_s=600.0)],
}


def main() -> None:
    # The diagnosis rationale contains unicode (e.g. "25σ hotter"); Windows
    # consoles default to cp1252, so switch stdout to UTF-8 when we can.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="short")
    parser.add_argument("--duration", type=float, default=1600.0, help="simulated seconds")
    args = parser.parse_args()

    pack = PackConfig(series=12, parallel=2, initial_soc=0.9)
    sim = SimConfig(dt_s=1.0, duration_s=args.duration)
    profile = ChargeDischargeCycle(discharge_a=20.0, charge_a=15.0)
    simulator = Simulator(pack, sim, profile, SCENARIOS[args.scenario])

    anomaly_engine = AnomalyEngine()
    assess_engine = AssessmentEngine()

    print(f"Scenario: {args.scenario}\n")
    print(f"{'t[s]':>6} {'Tmax[C]':>8} {'anom[z]':>7} {'diagnosis':>18} {'conf':>5} "
          f"{'SoH':>5} {'safety':>8}")
    print("-" * 66)

    last = None
    for i, tel in enumerate(simulator.run()):
        anomaly = anomaly_engine.update(tel)
        assessment = assess_engine.update(tel, anomaly)
        last = (tel, anomaly, assessment)
        if i % 120 == 0 or i == int(sim.duration_s / sim.dt_s) - 1:
            diag = assessment.diagnosis
            soh = f"{assessment.pack_soh * 100:4.0f}%"
            print(
                f"{tel.time_s:6.0f} {tel.max_temp_c:8.2f} {anomaly.max_score:7.1f} "
                f"{diag.fault_type:>18} {diag.confidence * 100:4.0f}% {soh:>5} "
                f"{assessment.safety_state:>8}"
            )

    if last is not None:
        tel, anomaly, assessment = last
        diag = assessment.diagnosis
        print("\nFinal assessment:")
        print(f"  Fault:          {diag.fault_type} ({diag.confidence * 100:.0f}% confidence)")
        print(f"  Rationale:      {diag.rationale}")
        print(f"  Pack SoH:       {assessment.pack_soh * 100:.1f}%  "
              f"(worst cell {assessment.worst_cell_soh * 100:.1f}%)")
        ttc = assessment.min_time_to_critical_s
        print(f"  Time-to-crit:   {ttc:.0f} s" if ttc is not None else "  Time-to-crit:   n/a")
        print(f"  Safety state:   {assessment.safety_state}")
        print(f"  Max cell temp:  {tel.max_temp_c:.1f} C (limit 60 C)")


if __name__ == "__main__":
    main()
