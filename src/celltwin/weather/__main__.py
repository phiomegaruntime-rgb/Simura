"""CLI smoke test for the weather providers.

Examples::

    python -m celltwin.weather --synthetic --hours 24
    python -m celltwin.weather --open-meteo --lat 52.52 --lon 13.41 --hours 12

The synthetic mode is fully offline and deterministic.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

from .config import build_provider


def _reconfigure_stdout() -> None:
    # Windows consoles default to cp1252; force UTF-8 so output never crashes.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    ap = argparse.ArgumentParser(description="Sample a weather provider over N hours.")
    ap.add_argument("--synthetic", action="store_true", help="offline diurnal model")
    ap.add_argument("--open-meteo", action="store_true", help="live Open-Meteo API")
    ap.add_argument("--lat", type=float, default=52.52)
    ap.add_argument("--lon", type=float, default=13.41)
    ap.add_argument("--tz-offset-h", type=float, default=0.0)
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--step-h", type=float, default=1.0)
    args = ap.parse_args(argv)

    if args.open_meteo:
        spec = {"type": "open_meteo", "latitude": args.lat, "longitude": args.lon}
    else:
        spec = {"type": "synthetic", "tz_offset_h": args.tz_offset_h}

    provider = build_provider(spec)
    if provider is None:
        print("no provider built")
        return 1

    t0 = time.time()
    print(f"{'time (UTC)':<20} {'temp C':>8} {'wind m/s':>9} {'solar W/m2':>11} {'humidity':>9}")
    print("-" * 60)
    n = int(args.hours / args.step_h)
    for i in range(n + 1):
        ts = t0 + i * args.step_h * 3600.0
        s = provider.at(ts)
        when = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        hum = "-" if s.humidity_frac is None else f"{s.humidity_frac * 100:.0f}%"
        print(f"{when:<20} {s.air_temp_c:>8.1f} {s.wind_speed_ms:>9.1f} {s.solar_w_m2:>11.0f} {hum:>9}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
