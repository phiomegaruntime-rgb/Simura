"""CLI:  python -m simura.builder [--example | --validate FILE | --preview FILE]

Examples
--------
Write a starter spec you can edit::

    python -m simura.builder --example > my-system.json

Check it, then preview it offline::

    python -m simura.builder --validate my-system.json
    python -m simura.builder --preview my-system.json

Then stream it live into the twin::

    python -m simura.publisher --spec my-system.json --speed 10
"""

from __future__ import annotations

import argparse
import json
import sys

from .options import builder_options
from .preview import SpecError, preview
from .spec import SystemSpec
from .validate import validate_spec


def _reconfigure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def _load(path: str) -> SystemSpec:
    with open(path, "r", encoding="utf-8") as fh:
        return SystemSpec.from_dict(json.load(fh))


def _print_preview(result) -> None:
    r = result
    print(f"System:    {r.name}  ({r.system_id}, {r.chemistry}, {r.series_len}S{r.parallel_len}P)")
    print(f"Ran:       {r.n_steps} steps over {r.duration_s:.0f} s")
    print(f"SoC:       {r.min_soc*100:.1f}% .. final {r.final_soc*100:.1f}%")
    print(f"Voltage:   {r.min_pack_voltage_v:.1f} .. {r.max_pack_voltage_v:.1f} V")
    print(f"Peak temp: {r.peak_temp_c:.1f} C  (limit {r.temp_limit_c:.0f} C)")
    print(f"Energy:    {r.energy_throughput_wh:.1f} Wh throughput, peak {r.peak_power_w/1000:.2f} kW")
    if r.temp_limit_exceeded:
        print(f"SAFETY:    temperature limit crossed at t = {r.time_to_limit_s:.0f} s")
    else:
        print("SAFETY:    within temperature limit")


def main() -> None:
    _reconfigure_stdout()
    parser = argparse.ArgumentParser(
        prog="python -m simura.builder",
        description="Build, validate and preview your own battery system spec.",
    )
    parser.add_argument("--example", action="store_true", help="print a starter spec as JSON")
    parser.add_argument("--validate", metavar="FILE", help="validate a spec JSON file")
    parser.add_argument("--preview", metavar="FILE", help="run a spec offline and summarize")
    args = parser.parse_args()

    if args.example:
        print(json.dumps(builder_options()["default_spec"], indent=2))
        return

    if args.validate:
        errors = validate_spec(_load(args.validate))
        if errors:
            print("INVALID:")
            for e in errors:
                print(f"  - {e}")
            raise SystemExit(1)
        print("OK: spec is valid")
        return

    if args.preview:
        try:
            _print_preview(preview(_load(args.preview)))
        except SpecError as exc:
            print("INVALID:")
            for e in exc.errors:
                print(f"  - {e}")
            raise SystemExit(1)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
