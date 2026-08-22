"""Watch an explanation change because the physics changed.

Run a pack twice — once healthy, once with an internal short in one cell — and
print what `simura.explain` says about each. Nothing in this script tells the
explainer that a fault is present, and nothing in `simura.explain` contains a
sentence about internal shorts. The fault-heat term appears in the second
ranking because the fault put heat into the model's heat balance, and the prose
follows the ranking.

That is the whole design decision of Component 16 in one file:
**an explanation is attributed, never asserted.**

    python examples/explain_a_fault.py

Then try the same thing through the other lenses and depths::

    python -m simura.explain --battery --short --domain safety --level physics
"""

from __future__ import annotations

import sys

from simura.builder import FaultSpec, ProfileSpec, SystemSpec, build_simulator
from simura.explain import brief, explain_pack, render_all

# Windows consoles default to cp1252; the prose has em-dashes in it.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


def run(faults: list[FaultSpec]):
    spec = SystemSpec(
        series=4,
        parallel=3,
        duration_s=900.0,
        dt_s=1.0,
        profile=ProfileSpec("constant_current", {"amps": 24.0}),
        faults=faults,
    )
    sim = build_simulator(spec)
    for _ in sim.run():
        pass
    return sim


def rule(title: str) -> None:
    print(f"\n{title}\n" + "=" * len(title))


SHORT = FaultSpec("internal_short", 2, 1, 300.0, {"r_short_ohm": 1.0})

healthy = run([])
broken = run([SHORT])

rule("The same pack, twice — 4s3p at 24 A for 15 minutes")
print(f"healthy: hottest cell {float(healthy.pack.temp_c.max()):.1f} °C")
print(f"shorted: hottest cell {float(broken.pack.temp_c.max()):.1f} °C  "
      "(a resistive path inside one cell)")

# ---------------------------------------------------------------------------
# 1. The overview. One sentence per quantity, for someone who has never seen
#    a battery simulation.
# ---------------------------------------------------------------------------
rule("1. Healthy, to a newcomer")
print(brief(explain_pack(healthy), domain="newcomer"))

rule("2. Shorted, to a newcomer")
print(brief(explain_pack(broken), domain="newcomer"))

# ---------------------------------------------------------------------------
# 2. The ranking underneath. This is where the difference is a computation
#    rather than a phrase: a term exists in one and not the other.
# ---------------------------------------------------------------------------
rule("3. What changed in the heat balance")
for label, sim in (("healthy", healthy), ("shorted", broken)):
    heat = next(a for a in explain_pack(sim) if a.key == "cell.heat_balance")
    print(f"\n{label}: {heat.total:+.3f} W net, {len(heat.terms)} terms")
    for t in heat.terms:
        print(f"    {t.label:<28} {t.value:>9.3f} W   {t.share * 100:>5.1f}%")

fault_term = next(
    a for a in explain_pack(broken) if a.key == "cell.heat_balance"
).term("fault_heat")
print(
    f"\nThe shorted pack has a term the healthy one does not: "
    f"{fault_term.label.lower()} at {fault_term.value:.1f} W, "
    f"{fault_term.share * 100:.0f}% of everything going on in that cell."
)

# ---------------------------------------------------------------------------
# 3. The signature that names the fault, and it is arithmetic, not a rule.
#    Charge is leaving the cell faster than it is leaving the terminals.
# ---------------------------------------------------------------------------
rule("4. Why this is a short and not a cooling fault")
rate = next(a for a in explain_pack(broken) if a.key == "cell.charge_rate")
load = rate.term("load")
parasitic = rate.term("parasitic")
print(
    f"The cell is losing {abs(rate.total):.0f} %/h of charge, but only "
    f"{abs(load.value):.0f} %/h of that reaches the terminals. The other "
    f"{abs(parasitic.value):.0f} %/h goes nowhere — which is what a short is, and "
    "what tells it apart from a cooling fault, where the cell is just as hot and "
    "loses no charge at all."
)

# ---------------------------------------------------------------------------
# 4. Same computation, three readers. The lens changes the order and the words,
#    never the numbers.
# ---------------------------------------------------------------------------
rule("5. The same shorted pack, three readers")
for domain in ("safety", "operations", "battery"):
    first = render_all(explain_pack(broken), domain=domain, level="overview")[0]
    print(f"\n{domain:<12} leads with {first.key}")
    print(f"             {first.headline}")

# ---------------------------------------------------------------------------
# 5. Depth adds, never contradicts.
# ---------------------------------------------------------------------------
rule("6. One quantity, three depths")
heat = next(a for a in explain_pack(broken) if a.key == "cell.heat_balance")
for level in ("overview", "working", "physics"):
    from simura.explain import render

    e = render(heat, "newcomer", level)
    print(f"\n[{level}]  {e.headline}")
    if e.causes:
        print(f"          {len(e.causes)} causes listed")
    if e.equation:
        print(f"          {e.equation}")
        print(f"          evaluated at {len(e.operating_point)} values, "
              f"{len(e.limits)} stated limits")
print("\nThe headline is identical at all three. Depth adds detail; it never "
      "changes the claim.")
