"""CLI for the wire-model validator. Fully offline and deterministic.

Examples::

    python -m simura.wires.validation --list
    python -m simura.wires.validation --standard copper-annealed-20c
"""

from __future__ import annotations

import argparse
import sys

from .engine import validate_reference
from .standards import get_standard, list_standards


def _reconfigure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def _cmd_list() -> int:
    print(f"{'id':<22}{'material':<10}{'refT':>6}{'pts':>5}  name")
    print("-" * 72)
    for s in list_standards():
        print(f"{s.id:<22}{s.material:<10}{s.ref_temp_c:>5.0f}C{len(s._rows):>5}  {s.name}")
    return 0


def _cmd_validate(standard_id: str) -> int:
    ref = get_standard(standard_id).reference()
    report = validate_reference(ref)
    m = report.metrics
    print(f"standard : {report.standard_id}  ({report.material}, {report.ref_temp_c:.0f} C)")
    print(f"points   : {report.n_points} gauges")
    print(f"RMSE     : {m['rmse_pct']:.2f} %")
    print(f"MAE      : {m['mae_pct']:.2f} %")
    print(f"max err  : {m['max_abs_pct']:.2f} %")
    print(f"bias     : {m['mean_bias_pct']:+.2f} %")
    print()
    o = report.overlay
    print(f"  {'AWG':>5}{'published':>12}{'model':>12}{'err %':>9}   ({report.unit})")
    for i in range(report.n_points):
        awg = int(o["awg"][i])
        label = f"{1 - awg}/0" if awg <= 0 else str(awg)
        print(
            f"  {label:>5}{o['published_ohm_per_km'][i]:>12.4f}"
            f"{o['model_ohm_per_km'][i]:>12.4f}{o['error_pct'][i]:>9.2f}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    ap = argparse.ArgumentParser(description="Validate the Simura wire model against a standard.")
    ap.add_argument("--list", action="store_true", help="list bundled standards")
    ap.add_argument("--standard", default="copper-annealed-20c", help="standard id to validate against")
    args = ap.parse_args(argv)

    if args.list:
        return _cmd_list()
    return _cmd_validate(args.standard)


if __name__ == "__main__":
    raise SystemExit(main())
