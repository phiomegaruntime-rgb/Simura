"""Light a room: check a lamp, size the installation, then see where the light falls.

The lighting analog of ``wire_planning.py``: it exercises the three things
:mod:`simura.lights` is for --

1. **Evaluate** a chosen lamp and count against a task (illuminance, colour,
   installed power) -- at the *end* of a maintenance cycle, not on day one.
2. **Recommend** the catalog lamp that meets the target at the lowest installed
   power, with every alternative ranked beside it.
3. **Solve the illuminance field** on a grid, because an average hides the two
   failures that matter: dark patches between fittings and pools under them.

Usage:
    python examples/light_planning.py

Needs nothing but the standard library.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Windows consoles default to cp1252; force UTF-8 so the units never crash it.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from simura.lights import (  # noqa: E402
    Layout,
    LightSpec,
    evaluate_installation,
    recommend_lamp,
    task_lux,
)

# A small open-plan office: 12 x 9 m, luminaires 2.5 m above the desks.
LENGTH_M, WIDTH_M, HEIGHT_M = 12.0, 9.0, 2.5
TASK = "office"


def main() -> None:
    target = task_lux(TASK)
    print(f"A {LENGTH_M:g} x {WIDTH_M:g} m {TASK}, {target:.0f} lux on the desks\n")

    print("1) Evaluate an obvious first guess: 20 x 15 W LED bulbs")
    print("-" * 62)
    a = evaluate_installation(
        LightSpec(lamp_type="led-15-e27"),
        n_luminaires=20,
        length_m=LENGTH_M, width_m=WIDTH_M, mounting_height_m=HEIGHT_M,
        task=TASK,
        maintenance_hours=8000.0,      # three years of office use
    )
    print(f"  maintained    : {a.maintained_lux:.0f} lux  (new: {a.initial_lux:.0f} lux)")
    print(f"  installed     : {a.power_w:.0f} W  ({a.power_density_w_per_m2:.2f} W/m²)")
    print(f"  efficacy      : {a.efficacy_lm_per_w:.0f} lm/W at {a.color_temp_k:.0f} K, CRI {a.cri:.0f}")
    print(f"  annual energy : {a.annual_energy_kwh:.0f} kWh")
    print(f"  verdict       : {'OK' if a.ok else 'PROBLEMS'}")
    for p in a.problems:
        print(f"    - {p}")

    print("\n2) Let the catalog choose")
    print("-" * 62)
    rec = recommend_lamp(
        length_m=LENGTH_M, width_m=WIDTH_M, mounting_height_m=HEIGHT_M, task=TASK,
    )
    print(f"  {rec.rationale}\n")
    print(f"  {'lamp':<18}{'family':<15}{'n':>4}{'W/m²':>8}{'lux':>7}{'kWh/yr':>9}{'CRI':>5}")
    for alt in rec.alternatives:
        print(
            f"  {alt['lamp_id']:<18}{alt['family'].replace('_', ' '):<15}"
            f"{alt['n_luminaires']:>4}{alt['power_density_w_per_m2']:>8.2f}"
            f"{alt['maintained_lux']:>7.0f}{alt['annual_energy_kwh']:>9.0f}{alt['cri']:>5.0f}"
        )
    print("\n  (ranked by installed power. Which technology wins depends on the")
    print("   space: a cold store rules out fluorescent, a gallery rules out")
    print("   sodium, and anywhere light must return instantly rules out every")
    print("   high-pressure discharge lamp.)")

    print("\n3) Two ways to deliver the same light — what the average hides")
    print("-" * 62)
    # Roughly equal installed lumens, delivered by many small fittings or by a
    # few big ones. The lumen method scores them almost identically; the field
    # does not.
    for lamp_id, rows, cols in (("led-15-e27", 7, 9), ("led-100-flood", 2, 5)):
        layout = Layout(length_m=LENGTH_M, width_m=WIDTH_M, grid_n=9)
        layout.grid_regular(rows, cols, HEIGHT_M + 0.75, LightSpec(lamp_type=lamp_id))
        result = layout.solve(target_lux=target, min_uniformity=0.6)
        print(
            f"  {rows}x{cols} {lamp_id:<15} "
            f"avg {result.average_lux:>4.0f} lux  "
            f"min {result.min_lux:>4.0f}  max {result.max_lux:>4.0f}  "
            f"U0 {result.uniformity:.2f}  {result.power_density_w_per_m2:.1f} W/m²"
        )
        for problem in result.problems:
            print(f"      - {problem}")

    print("\n  Both land near the target on average. The sparse layout does it with")
    print("  bright pools and dark gaps between them, and a room lit that way reads")
    print("  as badly lit however good its average is — which is why uniformity is")
    print("  a requirement in its own right, not a nicety.")


if __name__ == "__main__":
    main()
