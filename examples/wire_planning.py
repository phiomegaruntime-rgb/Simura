"""Plan a wire run: check a gauge, size the right one, then solve a small network.

The wiring analog of ``run_basic.py``: it exercises the three things
:mod:`simura.wires` is for --

1. **Evaluate** a chosen wire against a load (ampacity, voltage drop, temperature).
2. **Recommend** the smallest catalog gauge that satisfies the constraints.
3. **Solve a multi-node network** (a source feeding two loads down a shared
   trunk) by nodal analysis.

Usage:
    python examples/wire_planning.py

Only needs numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from simura.wires import (  # noqa: E402
    WireNetwork,
    WireSpec,
    evaluate_run,
    recommend_gauge,
)


def main() -> None:
    # A 12 V circuit, 20 m away, drawing 15 A (round-trip = 40 m of conductor).
    current_a, length_m, system_v, max_drop = 15.0, 20.0, 12.0, 3.0

    print("1) Evaluate a 12 AWG copper run")
    print("-" * 40)
    a = evaluate_run(
        WireSpec(awg=12, length_m=length_m, insulation="THHN-90"),
        current_a, system_voltage_v=system_v, max_drop_pct=max_drop, round_trip=True,
    )
    print(f"  resistance  : {a.resistance_ohm * 1000:.1f} mOhm")
    print(f"  drop        : {a.voltage_drop_v:.2f} V ({a.voltage_drop_pct:.1f}%)")
    print(f"  conductor   : {a.steady_state_temp_c:.0f} C / {a.temp_rating_c:.0f} C rating")
    print(f"  ampacity    : {a.ampacity_utilization * 100:.0f}% of {a.ampacity_a:.0f} A")
    print(f"  verdict     : {'OK' if a.ok else 'PROBLEMS'}")
    for p in a.problems:
        print(f"    - {p}")

    print("\n2) Recommend the right gauge for the same run")
    print("-" * 40)
    rec = recommend_gauge(current_a, length_m, system_voltage_v=system_v,
                          max_drop_pct=max_drop, round_trip=True)
    print(f"  {rec.rationale}")
    print("  (voltage drop, not heat, drives the upsize on a long 12 V run)")

    print("\n3) Solve a small network: 12 V source -> trunk -> two loads")
    print("-" * 40)
    net = WireNetwork()
    net.add_node("source", voltage=12.0)
    net.add_node("junction", load_a=8.0)
    net.add_node("end", load_a=6.0)
    net.add_segment("trunk", "source", "junction", WireSpec(awg=10, length_m=5.0))
    net.add_segment("branch", "junction", "end", WireSpec(awg=12, length_m=8.0))
    result = net.solve()
    for nid, v in result.node_voltages.items():
        print(f"  node {nid:<9} {v:6.3f} V")
    for s in result.segments:
        print(f"  seg  {s.id:<9} {s.current_a:5.1f} A  {s.voltage_drop_v:5.3f} V drop  "
              f"{s.temp_c:4.0f} C  {s.ampacity_utilization * 100:3.0f}% util")
    print(f"  total loss : {result.total_loss_w:.2f} W   verdict: "
          f"{'OK' if result.ok else 'PROBLEMS'}")


if __name__ == "__main__":
    main()
