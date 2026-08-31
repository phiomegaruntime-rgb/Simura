"""CLI for building imports. Fully offline: one file in, one plan out.

The point of this command is the same as the library CLI's: the thing it does is
useful with no broker, no database and no dashboard running. Somebody handed a
model can find out what is in it, what Simura could not read, and what it would
cost to light -- from a shell, in one line.

Examples::

    python -m simura.space --import office.ifc
    python -m simura.space --import office.ifc --fidelity
    python -m simura.space --import office.ifc --diagnose
    python -m simura.space --import block-a.xml --save plan.json
    python -m simura.space --import floor.dxf --wall-layers A-WALL,I-WALL
    python -m simura.space --demo --rooms 6 --save demo.json
    python -m simura.space --plan plan.json --rooms-table
    python -m simura.space --plan plan.json --light
    python -m simura.space --plan plan.json --route 3,3 21,3
    python -m simura.space --plan plan.json --weather

Two of these are worth running on every real model, and they answer different
questions. ``--fidelity`` is "what could the importer not read". ``--diagnose``
is "the import worked and the result still is not my building" -- stray
coordinates, suspicious extents, sealed storeys. A model can pass the first and
fail the second badly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import build_provider, detect_format
from .couple import lighting_targets, summary, weather_spec
from .diagnose import report as diagnose_report
from .plan import FloorPlan
from .provider import PlanError
from .providers import RectangleProvider
from .routing import route


def _reconfigure_stdout() -> None:
    # Windows consoles default to cp1252; force UTF-8 so output never crashes.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def _load(args: argparse.Namespace) -> FloorPlan:
    """The plan this invocation is about, from whichever source was named."""
    if args.demo:
        return RectangleProvider(
            rooms=args.rooms, levels=args.levels, name="Example building"
        ).plan()

    source = args.import_path or args.plan
    if not source:
        raise PlanError("give --import FILE, --plan FILE.json, or --demo")

    kind = args.format or detect_format(source, Path(source).read_bytes()[:4096])
    params: dict[str, object] = {"path": source}
    if kind == "dxf":
        if args.wall_layers:
            params["wall_layers"] = args.wall_layers
        if args.room_layers:
            params["room_layers"] = args.room_layers
        if args.scale:
            params["scale"] = args.scale
    provider = build_provider({"type": kind, **params})
    if provider is None:
        raise PlanError(f"nothing to import from {source}")
    return provider.plan()


def _print_overview(plan: FloorPlan) -> None:
    report = summary(plan)
    width, depth = report["size_m"]
    print(f"{plan.name or '(unnamed)'}   [{plan.id}]")
    print(
        f"  {report['spaces']} rooms, {report['walls']} walls, "
        f"{report['openings']} openings, {report['levels']} level(s)"
    )
    print(
        f"  {report['floor_area_m2']:.1f} m² over {width:.1f} x {depth:.1f} m, "
        f"drawn in {report['source_units']}"
    )
    if report["located"]:
        print(
            f"  at {report['latitude']:.5f}, {report['longitude']:.5f}"
            f"   true north {report['north_deg']:.1f}°"
        )
    else:
        print("  no coordinates in the model — weather cannot be configured from it")
    if report["occupancies"]:
        kinds = ", ".join(f"{n}x {k}" for k, n in report["occupancies"].items())
        print(f"  rooms: {kinds}")
    print(f"  {plan.fidelity.summary()}")


def _print_fidelity(plan: FloorPlan) -> None:
    """The list this whole component exists to be able to print."""
    fid = plan.fidelity
    print(f"\nWhat the import could not read — {fid.source_name or fid.source_format}")
    print(f"  source sha256 {fid.source_sha256[:16] or '(none)'}")
    print(
        f"  read {fid.entities_used} of {fid.entities_seen} entities "
        f"({fid.coverage * 100:.0f}%)"
    )

    if fid.inferences:
        print(f"\n  Assumed ({len(fid.inferences)}):")
        for item in fid.inferences:
            mark = "default" if item.provenance == "default" else "derived"
            print(f"    [{mark}] {item.subject}.{item.field} = {item.value}")
            print(f"             {item.basis}")
    else:
        print("\n  Assumed: nothing. Every value came out of the file.")

    if fid.skipped:
        print(f"\n  Skipped ({sum(s.count for s in fid.skipped)}):")
        for item in fid.skipped:
            print(f"    {item.count:>4}x {item.entity} — {item.reason}")

    for warning in fid.warnings:
        print(f"\n  ! {warning}")


def _print_diagnose(plan: FloorPlan) -> None:
    """What is measurably odd about this plan. See :mod:`simura.space.diagnose`."""
    r = diagnose_report(plan)
    width, depth = r["size_m"]
    print(f"\nDiagnosis — {plan.name or plan.id}")
    print(f"  footprint      {width:,.1f} x {depth:,.1f} m")
    print(f"  bounds         {r['bounds']}")
    print(f"  room area      {r['floor_area_m2']:,.1f} m²")
    print(f"  doors {r['doors']}, windows {r['windows']}")
    print("  largest rooms  " + ", ".join(f"{a:,.1f}" for a in r["largest_rooms_m2"]))
    print("  smallest rooms " + ", ".join(f"{a:,.1f}" for a in r["smallest_rooms_m2"]))

    print("\n  per storey:")
    for level in r["levels"]:
        print(
            f"    {(level['name'] or level['id'])[:22]:<24} "
            f"el {level['elevation_m']:>8,.2f} m   "
            f"{level['rooms']:>3} rooms  {level['walls']:>4} walls  "
            f"{level['floor_area_m2']:>10,.1f} m²"
        )

    if not r["findings"]:
        print("\n  Nothing looks wrong with this plan.")
        return

    print("")
    for finding in r["findings"]:
        mark = {"error": "!!", "warning": " !", "note": "  "}.get(finding["severity"], "  ")
        print(f"  {mark} {finding['what']}")
        for line in _wrap(finding["detail"], 74):
            print(f"       {line}")
        for subject in finding["subjects"]:
            print(f"         - {subject}")
        print("")


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def _print_rooms(plan: FloorPlan) -> None:
    print(f"\n{'room':<28} {'use':<16} {'area':>8} {'l x w':>14} {'h':>6}  shape")
    print("-" * 84)
    for space in sorted(plan.spaces, key=lambda s: (s.level_id, s.name)):
        length, width, _ = space.extents()
        shape = "rectangle" if space.rectangular() else "irregular"
        if space.inferred:
            shape += f"  (assumed: {', '.join(space.inferred)})"
        print(
            f"{(space.name or space.id)[:27]:<28} {space.occupancy:<16} "
            f"{space.area_m2:>7.1f}m {length:>6.1f} x{width:>5.1f} "
            f"{space.height_m:>5.2f}m  {shape}"
        )


def _print_lighting(plan: FloorPlan) -> None:
    """What it would take to light every room, and what that costs."""
    try:
        from ..lights.planning import recommend_lamp
    except Exception as exc:  # pragma: no cover - lights is part of the package
        print(f"lighting is unavailable: {exc}")
        return

    print(f"\n{'room':<28} {'target':>7} {'lamp':<24} {'n':>3} {'W/m²':>7}  verdict")
    print("-" * 92)
    total_w = 0.0
    total_area = 0.0
    undesignable = 0

    for target in lighting_targets(plan):
        if not target.designable:
            undesignable += 1
        result = recommend_lamp(**target.kwargs())
        assessment = result.assessment
        if assessment is None:
            print(f"{target.name[:27]:<28} {'—':>7} {'no lamp meets it':<24}")
            continue
        total_w += assessment.power_w
        total_area += target.area_m2
        verdict = "ok" if result.ok else "; ".join(assessment.problems)[:40]
        print(
            f"{(target.name or target.space_id)[:27]:<28} "
            f"{assessment.target_lux:>6.0f}lx "
            f"{(result.lamp_type.name if result.lamp_type else '—')[:23]:<24} "
            f"{result.n_luminaires:>3} "
            f"{assessment.power_density_w_per_m2:>6.1f}   {verdict}"
        )

    if total_area > 0:
        print(
            f"\n  whole building: {total_w:.0f} W over {total_area:.0f} m² "
            f"= {total_w / total_area:.1f} W/m²"
        )
    if undesignable:
        print(
            f"  {undesignable} room(s) could not be designed as read — see "
            f"--fidelity for why"
        )


def _print_route(plan: FloorPlan, start: str, end: str) -> None:
    def point(text: str) -> tuple[float, float]:
        parts = text.replace(" ", "").split(",")
        if len(parts) != 2:
            raise PlanError(f"a point is 'x,y' in metres, not {text!r}")
        return (float(parts[0]), float(parts[1]))

    result = route(plan, point(start), point(end))
    print(f"\ncable route {start} -> {end}")
    for leg in result.legs:
        print(f"  {leg.kind:<11} {leg.length_m:>7.2f} m   {leg.description}")
    print(
        f"  {'':<11} {'-' * 9}\n"
        f"  {'total':<11} {result.length_m:>7.2f} m   "
        f"({result.horizontal_m:.1f} horizontal + {result.vertical_m:.1f} vertical "
        f"+ {result.slack_m:.1f} slack)"
    )
    for problem in result.problems:
        print(f"  ! {problem}")


def _print_weather(plan: FloorPlan) -> None:
    spec = weather_spec(plan)
    if spec is None:
        print(
            "\nThe model carries no coordinates, so no weather source can be built "
            "from it. Set one by hand, or import a model with an IfcSite."
        )
        return
    print("\nWeather source implied by the model — paste into a SystemSpec:")
    print(json.dumps({"weather": {"type": spec.pop("type"), "params": spec}}, indent=2))


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    parser = argparse.ArgumentParser(
        prog="python -m simura.space",
        description="Import a building model as a 2D floor plan.",
    )
    parser.add_argument("--import", dest="import_path", metavar="FILE",
                        help="a building file: .ifc, .xml/.gbxml, .dxf")
    parser.add_argument("--plan", metavar="FILE.json", help="a plan saved earlier")
    parser.add_argument("--demo", action="store_true",
                        help="a generated example building, no file needed")
    parser.add_argument("--format", choices=("ifc", "ifc_full", "gbxml", "dxf", "json"),
                        help="override the format detected from the file")
    parser.add_argument("--rooms", type=int, default=4, help="--demo: rooms per level")
    parser.add_argument("--levels", type=int, default=1, help="--demo: how many storeys")
    parser.add_argument("--wall-layers", help="DXF: comma-separated wall layer names")
    parser.add_argument("--room-layers", help="DXF: comma-separated room layer names")
    parser.add_argument("--scale", type=float, help="DXF: metres per drawing unit")
    parser.add_argument("--save", metavar="FILE.json", help="write the plan out")
    parser.add_argument("--fidelity", action="store_true",
                        help="everything the import assumed or skipped")
    parser.add_argument("--diagnose", action="store_true",
                        help="what is measurably odd about the resulting plan")
    parser.add_argument("--rooms-table", action="store_true", help="list every room")
    parser.add_argument("--light", action="store_true",
                        help="design lighting for every room and total it up")
    parser.add_argument("--route", nargs=2, metavar=("X,Y", "X,Y"),
                        help="trace a cable run between two points, in metres")
    parser.add_argument("--weather", action="store_true",
                        help="the weather source the model's coordinates imply")
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")

    args = parser.parse_args(argv)
    if not (args.import_path or args.plan or args.demo):
        parser.print_help()
        return 2

    try:
        plan = _load(args)
    except PlanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(plan.to_json())
        return 0

    _print_overview(plan)
    if args.fidelity:
        _print_fidelity(plan)
    if args.diagnose:
        _print_diagnose(plan)
    if args.rooms_table:
        _print_rooms(plan)
    if args.light:
        _print_lighting(plan)
    if args.route:
        try:
            _print_route(plan, args.route[0], args.route[1])
        except (PlanError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    if args.weather:
        _print_weather(plan)

    if args.save:
        Path(args.save).write_text(plan.to_json(), encoding="utf-8")
        print(f"\nsaved {args.save}  ({plan.id})")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
