"""CLI for the "get familiar" layer. Fully offline and deterministic.

Examples::

    python -m simura.explain --cards
    python -m simura.explain --card battery.thermal
    python -m simura.explain --glossary
    python -m simura.explain --define ampacity
    python -m simura.explain --coverage
    python -m simura.explain --battery --short --domain safety --level working
    python -m simura.explain --wire --awg 12 --length 40 --current 18 --voltage 12
    python -m simura.explain --lamp led-9-e27 --domain newcomer

The battery demo runs a real simulation and explains it, so the output is the
model's own arithmetic rather than a canned paragraph -- pass ``--short`` and
watch the fault-heat term appear in the ranking that was not there before.
"""

from __future__ import annotations

import argparse
import sys

from .cards import coverage, get_card, list_cards
from .glossary import define, list_terms
from .levels import LEVELS
from .narrate import render_all


def _reconfigure_stdout() -> None:
    # Windows consoles default to cp1252; force UTF-8 so output never crashes.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def _wrap(text: str, indent: str = "  ", width: int = 78) -> str:
    import textwrap

    return textwrap.fill(text, width=width, initial_indent=indent, subsequent_indent=indent)


def _show(attributions, domain: str, level: str) -> None:
    for e in render_all(attributions, domain, level):
        print()
        print(f"* {e.headline}")
        if e.summary:
            print(_wrap(e.summary, "    "))
        for c in e.causes:
            print(_wrap(f"- {c}", "    "))
        if e.equation:
            print(f"    eq: {e.equation}")
        if e.caveat:
            print(_wrap(f"note: {e.caveat}", "    "))


# -- commands --------------------------------------------------------------


def _cmd_cards(component: str | None) -> int:
    print(f"{'id':<24}{'component':<12}title")
    print("-" * 74)
    for c in list_cards(component):
        print(f"{c.id:<24}{c.component:<12}{c.title}")
    return 0


def _cmd_card(card_id: str) -> int:
    c = get_card(card_id)
    print(f"{c.title}  [{c.component}]  ({c.source})")
    print(_wrap(c.what))
    print("\nWhy it matters")
    print(_wrap(c.why))
    if c.equation:
        print(f"\n  {c.equation}")
    if c.reads_like:
        print("\nReads like, if your field is...")
        for k, v in c.reads_like.items():
            print(_wrap(f"{k}: {v}", "  "))
    if c.limits:
        print("\nWhat it cannot tell you")
        for lim in c.limits:
            print(_wrap(f"- {lim}", "  "))
    if c.params:
        print(f"\nSettings ({len(c.params)})")
        for p in c.params:
            unit = f" ({p.unit})" if p.unit else ""
            print(f"  {p.key}{unit} -- {p.label}")
            print(_wrap(p.why, "      "))
    return 0


def _cmd_glossary() -> int:
    for e in list_terms():
        print(f"{e.term}{f' ({e.unit})' if e.unit else ''}")
        print(_wrap(e.short))
    return 0


def _cmd_define(term: str) -> int:
    e = define(term)
    if e is None:
        print(f"no glossary entry for {term!r}")
        return 1
    print(f"{e.term}{f' ({e.unit})' if e.unit else ''}")
    print(_wrap(e.short))
    if e.card:
        print(f"  more: {e.card}")
    return 0


def _cmd_coverage() -> int:
    c = coverage()
    print(f"{c['documented']}/{c['parameters_in_code']} parameters documented")
    for m in c["missing"]:
        print(f"  MISSING  {m['surface']}.{m['key']}")
    for o in c["orphaned"]:
        print(f"  ORPHANED {o['surface']}.{o['key']} (in {o['card']})")
    print("complete" if c["complete"] else "INCOMPLETE")
    return 0 if c["complete"] else 1


def _cmd_battery(args) -> int:
    from ..builder import FaultSpec, ProfileSpec, SystemSpec, build_simulator
    from .battery import explain_pack

    faults = (
        [FaultSpec("internal_short", 1, 0, 200.0, {"r_short_ohm": 1.0})]
        if args.short
        else []
    )
    spec = SystemSpec(
        series=4, parallel=3, duration_s=args.duration, dt_s=1.0,
        profile=ProfileSpec("constant_current", {"amps": args.current}),
        faults=faults,
    )
    sim = build_simulator(spec)
    for _ in sim.run():
        pass
    hottest = float(sim.pack.temp_c.max())
    print(
        f"{spec.series}s{spec.parallel}p at {args.current:.0f} A for "
        f"{args.duration:.0f} s{' with an internal short' if args.short else ''} "
        f"-- hottest cell {hottest:.1f} C"
    )
    _show(explain_pack(sim), args.domain, args.level)
    return 0


def _cmd_wire(args) -> int:
    from ..wires import WireSpec
    from .wires import explain_run

    spec = WireSpec(awg=args.awg, length_m=args.length, ambient_temp_c=args.ambient)
    print(
        f"AWG {args.awg} copper, {args.length:.0f} m, {args.current:.0f} A on "
        f"{args.voltage:.0f} V, round trip, {args.ambient:.0f} C ambient"
    )
    _show(
        explain_run(spec, args.current, args.voltage, round_trip=True, ambient_c=args.ambient),
        args.domain,
        args.level,
    )
    return 0


def _cmd_lamp(args) -> int:
    from ..lights import LightSpec, evaluate_installation
    from ..lights.lamp import Light
    from .lights import explain_installation

    spec = LightSpec(lamp_type=args.lamp)
    lamp = Light(spec)
    lamp.time_lit_s = 1e9
    assessment = evaluate_installation(
        spec, n_luminaires=args.count, length_m=10.0, width_m=8.0,
        mounting_height_m=2.5, task="office",
        maintenance_hours=args.hours, dirt_frac=args.dirt,
    )
    print(
        f"{args.count} x {args.lamp} in a 10x8 m office, {args.hours:.0f} h old, "
        f"{args.dirt * 100:.0f}% dirt -- {assessment.maintained_lux:.0f} lux "
        f"against a {assessment.target_lux:.0f} lux target"
    )
    _show(explain_installation(assessment, point=lamp.operating_point()), args.domain, args.level)
    return 0


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    p = argparse.ArgumentParser(prog="python -m simura.explain", description=__doc__)
    p.add_argument("--cards", action="store_true", help="list every model card")
    p.add_argument("--component", help="narrow --cards to one component")
    p.add_argument("--card", help="print one model card in full")
    p.add_argument("--glossary", action="store_true", help="print the whole glossary")
    p.add_argument("--define", help="look up one term (aliases work)")
    p.add_argument("--coverage", action="store_true",
                   help="check the cards against the code, both directions")

    p.add_argument("--battery", action="store_true", help="explain a simulated pack")
    p.add_argument("--short", action="store_true", help="inject an internal short first")
    p.add_argument("--current", type=float, default=24.0)
    p.add_argument("--duration", type=float, default=900.0)

    p.add_argument("--wire", action="store_true", help="explain a wire run")
    p.add_argument("--awg", type=int, default=12)
    p.add_argument("--length", type=float, default=40.0)
    p.add_argument("--voltage", type=float, default=12.0)
    p.add_argument("--ambient", type=float, default=35.0)

    p.add_argument("--lamp", help="explain a lighting installation using this lamp id")
    p.add_argument("--count", type=int, default=12)
    p.add_argument("--hours", type=float, default=20000.0)
    p.add_argument("--dirt", type=float, default=0.15)

    p.add_argument("--domain", default="newcomer", help="whose vocabulary to use")
    p.add_argument("--level", default="working", choices=list(LEVELS))
    args = p.parse_args(argv)

    try:
        if args.cards:
            return _cmd_cards(args.component)
        if args.card:
            return _cmd_card(args.card)
        if args.glossary:
            return _cmd_glossary()
        if args.define:
            return _cmd_define(args.define)
        if args.coverage:
            return _cmd_coverage()
        if args.battery:
            return _cmd_battery(args)
        if args.wire:
            return _cmd_wire(args)
        if args.lamp:
            return _cmd_lamp(args)
    except KeyError as exc:
        print(f"error: {exc}")
        return 1

    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
