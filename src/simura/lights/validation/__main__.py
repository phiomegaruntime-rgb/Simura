"""CLI for the lighting-model validator.

Every bundled standard runs offline and deterministically; ``--live`` is the one
mode that reaches the network (Open-Meteo, no API key).

Examples::

    python -m simura.lights.validation --list
    python -m simura.lights.validation --standard lamp-efficacy-published
    python -m simura.lights.validation --all
    python -m simura.lights.validation --live --lat 51.5 --lon -0.13 --hours 48
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
    print(f"{'id':<32}{'quantity':<24}{'pts':>5}  name")
    print("-" * 96)
    for s in list_standards():
        print(f"{s.id:<32}{s.quantity:<24}{len(s._rows):>5}  {s.name}")
    return 0


def _cmd_validate(standard_id: str) -> int:
    spec = get_standard(standard_id)
    report = validate_reference(spec.reference())
    m = report.metrics
    print(f"standard : {report.standard_id}")
    print(f"quantity : {report.quantity}  ({report.unit})")
    print(f"points   : {report.n_points}")
    print(f"RMSE     : {m['rmse']:.4g} {report.unit}   ({m['rmse_pct']:.2f} %)")
    print(f"MAE      : {m['mae']:.4g} {report.unit}   ({m['mae_pct']:.2f} %)")
    print(f"max err  : {m['max_abs']:.4g} {report.unit}   ({m['max_abs_pct']:.2f} %)")
    print(f"bias     : {m['mean_bias']:+.4g} {report.unit}   ({m['mean_bias_pct']:+.2f} %)")
    print()

    o = report.overlay
    label = f"{report.x_label} ({report.x_unit})" if report.x_unit else report.x_label
    print(f"  {label:<26}{'published':>12}{'model':>12}{'err':>12}{'err %':>9}")
    for i in range(report.n_points):
        print(
            f"  {o['key'][i]:<26}{o['published'][i]:>12.4g}{o['model'][i]:>12.4g}"
            f"{o['error'][i]:>12.4g}{o['error_pct'][i]:>9.2f}"
        )
    return 0


def _cmd_all() -> int:
    print(f"{'standard':<32}{'points':>7}{'RMSE %':>10}{'MAE %':>10}{'bias %':>10}")
    print("-" * 69)
    for s in list_standards():
        r = validate_reference(s.reference())
        m = r.metrics
        print(
            f"{s.id:<32}{r.n_points:>7}{m['rmse_pct']:>10.2f}"
            f"{m['mae_pct']:>10.2f}{m['mean_bias_pct']:>+10.2f}"
        )
    return 0


def _cmd_live(lat: float, lon: float, hours: int) -> int:
    from .live import validate_daylight_live

    print(f"fetching Open-Meteo irradiance for {lat:.4f}, {lon:.4f} …")
    try:
        report = validate_daylight_live(lat, lon, hours=hours)
    except Exception as exc:                      # network, or no daylight in window
        print(f"live validation failed: {exc}")
        return 1

    m = report.metrics
    print(f"source        : {report.source}")
    print(f"daylight hours: {report.n_hours}  ({report.n_clear_hours} clear)")
    print(f"mean clearness: {m['mean_clearness_index']:.3f}")
    print()
    print("clear hours only — the honest test of the geometry + efficacy model:")
    print(f"  RMSE  : {m['clear_rmse_lux']:.0f} lux   ({m['clear_rmse_pct']:.1f} %)")
    print(f"  bias  : {m['clear_mean_bias_lux']:+.0f} lux   ({m['clear_mean_bias_pct']:+.1f} %)")
    print()
    print("all daylight hours — this measures the weather, not the model:")
    print(f"  RMSE  : {m['rmse_lux']:.0f} lux   ({m['rmse_pct']:.1f} %)")
    print(f"  bias  : {m['mean_bias_lux']:+.0f} lux   (clear-sky over-predicts cloud)")
    print()
    print(f"envelope violations (measured above clear-sky): {report.envelope_violations}")

    o = report.overlay
    print()
    print(f"  {'elev°':>7}{'measured lux':>14}{'model lux':>12}{'kt':>7}")
    step = max(1, report.n_hours // 14)
    for i in range(0, report.n_hours, step):
        print(
            f"  {o['elevation_deg'][i]:>7.1f}{o['measured_lux'][i]:>14.0f}"
            f"{o['model_lux'][i]:>12.0f}{o['clearness_index'][i]:>7.2f}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    ap = argparse.ArgumentParser(
        description="Validate the Simura lighting model against published data."
    )
    ap.add_argument("--list", action="store_true", help="list bundled standards")
    ap.add_argument("--all", action="store_true", help="run every bundled standard")
    ap.add_argument(
        "--standard", default="lamp-efficacy-published", help="standard id to validate against"
    )
    ap.add_argument(
        "--live", action="store_true",
        help="validate the daylight model against live Open-Meteo irradiance",
    )
    ap.add_argument("--lat", type=float, default=51.5074, help="--live latitude")
    ap.add_argument("--lon", type=float, default=-0.1278, help="--live longitude")
    ap.add_argument("--hours", type=int, default=48, help="--live window, in hours")
    args = ap.parse_args(argv)

    if args.list:
        return _cmd_list()
    if args.all:
        return _cmd_all()
    if args.live:
        return _cmd_live(args.lat, args.lon, args.hours)
    return _cmd_validate(args.standard)


if __name__ == "__main__":
    raise SystemExit(main())
