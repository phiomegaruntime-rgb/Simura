"""CLI smoke test for the wire library. Fully offline and deterministic.

Examples::

    python -m simura.wires --catalog
    python -m simura.wires --evaluate --awg 12 --length 20 --current 15 --voltage 12
    python -m simura.wires --recommend --current 15 --length 20 --voltage 12 --max-drop 3
    python -m simura.wires --network
    python -m simura.wires --simulate --awg 14 --current 25
"""

from __future__ import annotations

import argparse
import sys

from .catalog import list_wire_types
from .network import WireNetwork
from .planning import evaluate_run, recommend_gauge
from .profiles import ConstantCurrent
from .simulator import WireSimConfig, WireSimulator
from .wire import WireSpec


def _reconfigure_stdout() -> None:
    # Windows consoles default to cp1252; force UTF-8 so output never crashes.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def _cmd_catalog() -> int:
    print(f"{'id':<16}{'material':<14}{'awg':>5}{'mm2':>8}{'insul':>14}{'amp':>7}")
    print("-" * 64)
    for w in list_wire_types():
        print(
            f"{w.id:<16}{w.material:<14}{w.awg:>5}{w.area_mm2:>8.2f}"
            f"{w.insulation:>14}{w.ampacity_a:>7.0f}"
        )
    return 0


def _cmd_evaluate(args) -> int:
    spec = WireSpec(material=args.material, awg=args.awg, length_m=args.length,
                    insulation=args.insulation, ambient_temp_c=args.ambient)
    a = evaluate_run(spec, args.current, system_voltage_v=args.voltage,
                     max_drop_pct=args.max_drop, round_trip=not args.one_way)
    print(f"resistance      : {a.resistance_ohm * 1000:.3f} mOhm")
    print(f"voltage drop    : {a.voltage_drop_v:.3f} V"
          + (f"  ({a.voltage_drop_pct:.2f}%)" if a.voltage_drop_pct is not None else ""))
    print(f"power loss      : {a.power_loss_w:.2f} W")
    print(f"conductor temp  : {a.steady_state_temp_c:.1f} C  (rating {a.temp_rating_c:.0f} C)")
    print(f"ampacity        : {a.ampacity_utilization * 100:.0f}% of {a.ampacity_a:.0f} A")
    print("status          : " + ("OK" if a.ok else "PROBLEMS"))
    for p in a.problems:
        print(f"  - {p}")
    return 0 if a.ok else 2


def _cmd_recommend(args) -> int:
    rec = recommend_gauge(args.current, args.length, system_voltage_v=args.voltage,
                          max_drop_pct=args.max_drop, material=args.material,
                          ambient_c=args.ambient, round_trip=not args.one_way)
    if rec.wire_type is not None:
        print(f"recommended: {rec.wire_type.id}  ({rec.wire_type.name})")
    print(f"rationale  : {rec.rationale}")
    print("status     : " + ("OK" if rec.ok else "NO ADEQUATE WIRE"))
    return 0 if rec.ok else 2


def _demo_network() -> WireNetwork:
    """A 12 V source feeding two loads down a shared trunk, then a branch."""
    net = WireNetwork()
    net.add_node("source", voltage=12.0)
    net.add_node("junction", load_a=8.0)
    net.add_node("end", load_a=6.0)
    net.add_segment("trunk", "source", "junction", WireSpec(awg=12, length_m=5.0))
    net.add_segment("branch", "junction", "end", WireSpec(awg=14, length_m=8.0))
    return net


def _cmd_network() -> int:
    result = _demo_network().solve()
    print("node voltages:")
    for nid, v in result.node_voltages.items():
        print(f"  {nid:<10} {v:.3f} V")
    print("\nsegments:")
    print(f"  {'id':<10}{'I (A)':>8}{'drop (V)':>10}{'loss (W)':>10}{'temp C':>9}{'util %':>8}")
    for s in result.segments:
        print(f"  {s.id:<10}{s.current_a:>8.2f}{s.voltage_drop_v:>10.3f}"
              f"{s.power_loss_w:>10.3f}{s.temp_c:>9.1f}{s.ampacity_utilization * 100:>8.0f}")
    print(f"\ntotal loss : {result.total_loss_w:.3f} W")
    print(f"worst      : {result.worst_segment}")
    print("status     : " + ("OK" if result.ok else "PROBLEMS"))
    for p in result.problems:
        print(f"  - {p}")
    return 0 if result.ok else 2


def _cmd_simulate(args) -> int:
    spec = WireSpec(material=args.material, awg=args.awg, length_m=args.length,
                    insulation=args.insulation, ambient_temp_c=args.ambient)
    # Optional weather coupling: a deterministic synthetic diurnal cycle, so the
    # conductor cools with the wind and warms in the sun over the run.
    weather = None
    if args.weather:
        from ..weather import SyntheticProvider
        weather = SyntheticProvider(mean_temp_c=args.ambient, temp_amplitude_c=6.0,
                                    wind_mean_ms=args.wind, solar_peak_w_m2=args.solar)
    sim = WireSimulator(spec=spec, sim_config=WireSimConfig(dt_s=1.0, duration_s=args.duration),
                        profile=ConstantCurrent(args.current), weather=weather,
                        weather_epoch0=1704110400.0 if weather else None)
    frames = sim.run_to_list()
    header = f"{'t (s)':>7}{'temp C':>9}{'R mOhm':>9}{'loss W':>9}{'util %':>8}"
    if args.weather:
        header += f"{'amb C':>8}{'wind':>7}{'sun':>7}"
    print(header)
    step = max(1, len(frames) // 12)
    for f in frames[::step]:
        row = (f"{f.time_s:>7.0f}{f.temp_c:>9.2f}{f.resistance_ohm * 1000:>9.3f}"
               f"{f.power_loss_w:>9.3f}{f.ampacity_utilization * 100:>8.0f}")
        if f.weather:
            row += (f"{f.weather['air_temp_c']:>8.1f}{f.weather['wind_speed_ms']:>7.1f}"
                    f"{f.weather['solar_w_m2']:>7.0f}")
        print(row)
    last = frames[-1]
    print(f"\nsettled at {last.temp_c:.1f} C (rating {last.temp_rating_c:.0f} C), "
          f"{'OVER TEMP' if last.over_temp else 'within rating'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    ap = argparse.ArgumentParser(description="Wire simulation & wiring planning smoke test.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--catalog", action="store_true", help="list catalog wire types")
    mode.add_argument("--evaluate", action="store_true", help="check one run")
    mode.add_argument("--recommend", action="store_true", help="size a gauge")
    mode.add_argument("--network", action="store_true", help="solve a demo network")
    mode.add_argument("--simulate", action="store_true", help="thermal transient")

    ap.add_argument("--material", default="copper")
    ap.add_argument("--awg", type=int, default=12)
    ap.add_argument("--length", type=float, default=20.0, help="conductor length (m)")
    ap.add_argument("--current", type=float, default=15.0, help="load current (A)")
    ap.add_argument("--voltage", type=float, default=12.0, help="system voltage (V)")
    ap.add_argument("--insulation", default="THHN-90")
    ap.add_argument("--ambient", type=float, default=25.0)
    ap.add_argument("--max-drop", type=float, default=3.0, help="allowable %% voltage drop")
    ap.add_argument("--duration", type=float, default=600.0, help="--simulate seconds")
    ap.add_argument("--one-way", action="store_true", help="single conductor (no round trip)")
    ap.add_argument("--weather", action="store_true", help="--simulate with a synthetic diurnal weather cycle")
    ap.add_argument("--wind", type=float, default=4.0, help="peak wind (m/s) for --weather")
    ap.add_argument("--solar", type=float, default=900.0, help="peak solar (W/m^2) for --weather")
    args = ap.parse_args(argv)

    if args.catalog:
        return _cmd_catalog()
    if args.recommend:
        return _cmd_recommend(args)
    if args.network:
        return _cmd_network()
    if args.simulate:
        return _cmd_simulate(args)
    # default to evaluate
    return _cmd_evaluate(args)


if __name__ == "__main__":
    raise SystemExit(main())
