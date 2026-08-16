"""CLI smoke test for the lights library. Fully offline and deterministic.

Examples::

    python -m simura.lights --catalog
    python -m simura.lights --spectrum --lamp led-9-e27
    python -m simura.lights --evaluate --lamp led-15-e27 --n 6 --length 8 --width 6
    python -m simura.lights --recommend --length 8 --width 6 --task office
    python -m simura.lights --layout --lamp led-15-e27 --rows 2 --cols 3
    python -m simura.lights --dim --lamp inc-60-e27
    python -m simura.lights --simulate --lamp mh-250-e40 --duration 900
    python -m simura.lights --simulate --lamp led-100-flood --weather --duration 86400
"""

from __future__ import annotations

import argparse
import sys

from .catalog import list_lamp_types, list_technologies
from .lamp import Light, LightSpec
from .layout import Layout
from .photometry import task_lux
from .planning import evaluate_installation, recommend_lamp
from .profiles import ConstantDrive
from .simulator import LightSimConfig, LightSimulator


def _reconfigure_stdout() -> None:
    # Windows consoles default to cp1252; force UTF-8 so output never crashes.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def _cmd_catalog() -> int:
    print("TECHNOLOGIES")
    print(f"  {'key':<22}{'family':<16}{'CRI':>5}{'life h':>9}  name")
    print("  " + "-" * 76)
    for t in list_technologies():
        print(f"  {t.key:<22}{t.family:<16}{t.cri:>5.0f}{t.rated_life_h:>9.0f}  {t.name}")

    print()
    print("LAMPS  (published figures; the model predicts its own)")
    print(f"  {'id':<18}{'technology':<22}{'W':>7}{'pub lm':>9}{'lm/W':>7}{'CCT':>7}{'beam':>7}")
    print("  " + "-" * 77)
    for lamp in list_lamp_types():
        print(
            f"  {lamp.id:<18}{lamp.technology:<22}{lamp.rated_power_w:>7.0f}"
            f"{lamp.rated_flux_lm:>9.0f}{lamp.published_efficacy_lm_per_w:>7.1f}"
            f"{lamp.color_temp_k:>7.0f}{lamp.beam_angle_deg:>7.0f}"
        )
    return 0


def _cmd_spectrum(args) -> int:
    light = Light(_spec(args))
    light.time_lit_s = 1e9
    point = light.operating_point(1.0, args.ambient)
    spd = light.spectrum()

    print(f"lamp            : {light.lamp_type.name if light.lamp_type else light.tech.name}")
    print(f"technology      : {light.tech.name}  ({light.tech.family})")
    print(f"input power     : {point.input_power_w:.2f} W")
    print(f"radiant power   : {point.radiant_power_w:.2f} W "
          f"({point.radiant_power_w / point.input_power_w * 100:.0f}% of input)")
    print(f"luminous flux   : {point.luminous_flux_lm:.0f} lm")
    print(f"efficacy        : {point.efficacy_lm_per_w:.1f} lm/W")
    print(f"efficacy of rad : {point.ler_lm_per_w:.1f} lm/W  (the spectrum's own ceiling)")
    print(f"colour temp     : {point.color_temp_k:.0f} K" if point.color_temp_k > 0
          else "colour temp     : n/a (too far off the Planckian locus to have one)")
    print(f"published CRI   : {light.tech.cri:.0f}")
    print(f"source temp     : {point.source_temp_c:.0f} °C")
    print(f"visible fraction: {point.visible_fraction * 100:.1f}% of radiated power")

    print()
    print("spectral power distribution (relative):")
    peak = max(spd.values) or 1.0
    for nm in range(400, 740, 10):
        i = int(nm - 360)
        bar = "#" * int(round(48 * spd.values[i] / peak))
        print(f"  {nm:>4} nm |{bar}")
    return 0


def _cmd_evaluate(args) -> int:
    a = evaluate_installation(
        _spec(args), n_luminaires=args.n, length_m=args.length, width_m=args.width,
        mounting_height_m=args.height, task=args.task,
        maintenance_hours=args.maintenance_hours,
    )
    print(f"task            : {args.task}  ({a.target_lux:.0f} lux target)")
    print(f"luminaires      : {a.n_luminaires} x {a.flux_per_luminaire_lm:.0f} lm")
    print(f"maintained       : {a.maintained_lux:.0f} lux   (initial {a.initial_lux:.0f} lux)")
    print(f"installed power : {a.power_w:.0f} W   ({a.power_density_w_per_m2:.2f} W/m²)")
    print(f"efficacy        : {a.efficacy_lm_per_w:.1f} lm/W")
    print(f"colour          : {a.color_temp_k:.0f} K, CRI {a.cri:.0f}")
    print(f"annual energy   : {a.annual_energy_kwh:.0f} kWh")
    print(f"room index      : {a.room.room_index:.2f}   UF {a.room.utilisation_factor:.2f}")
    print("status          : " + ("OK" if a.ok else "PROBLEMS"))
    for p in a.problems:
        print(f"  - {p}")
    return 0 if a.ok else 2


def _cmd_recommend(args) -> int:
    rec = recommend_lamp(
        length_m=args.length, width_m=args.width, mounting_height_m=args.height,
        task=args.task, family=args.family,
    )
    print(f"task       : {args.task}  ({task_lux(args.task):.0f} lux target)")
    if rec.lamp_type is not None:
        print(f"recommended: {rec.n_luminaires} x {rec.lamp_type.id}  ({rec.lamp_type.name})")
    print(f"rationale  : {rec.rationale}")
    print("status     : " + ("OK" if rec.ok else "NO ADEQUATE LAMP"))
    if rec.alternatives:
        print()
        print(f"  {'lamp':<18}{'n':>4}{'W':>9}{'W/m²':>8}{'lux':>7}{'lm/W':>7}{'CRI':>5}")
        for alt in rec.alternatives:
            print(
                f"  {alt['lamp_id']:<18}{alt['n_luminaires']:>4}{alt['power_w']:>9.0f}"
                f"{alt['power_density_w_per_m2']:>8.2f}{alt['maintained_lux']:>7.0f}"
                f"{alt['efficacy_lm_per_w']:>7.1f}{alt['cri']:>5.0f}"
            )
    return 0 if rec.ok else 2


def _cmd_layout(args) -> int:
    layout = Layout(length_m=args.length, width_m=args.width, grid_n=args.grid)
    layout.grid_regular(args.rows, args.cols, args.height, _spec(args))
    result = layout.solve(target_lux=task_lux(args.task), min_uniformity=0.6)

    print(f"{args.rows}x{args.cols} luminaires over {args.length:g} x {args.width:g} m "
          f"at {args.height:g} m")
    print(f"average : {result.average_lux:.0f} lux")
    print(f"min/max : {result.min_lux:.0f} / {result.max_lux:.0f} lux")
    print(f"U0      : {result.uniformity:.2f}   (0.6 wanted for a working interior)")
    print(f"power   : {result.total_power_w:.0f} W  ({result.power_density_w_per_m2:.2f} W/m²)")
    print()
    print("illuminance field (lux):")
    for row in result.grid:
        print("  " + " ".join(f"{v:>6.0f}" for v in row))
    print()
    print("status  : " + ("OK" if result.ok else "PROBLEMS"))
    for p in result.problems:
        print(f"  - {p}")
    return 0 if result.ok else 2


def _cmd_dim(args) -> int:
    light = Light(_spec(args))
    light.time_lit_s = 1e9
    print("Dimming: what a dimmer actually costs you.")
    print(f"  {'drive':>6}{'power W':>10}{'flux lm':>10}{'lm/W':>8}{'CCT K':>8}{'source °C':>11}")
    for pct in (100, 90, 80, 70, 60, 50, 40, 30, 20, 10):
        p = light.operating_point(pct / 100.0, args.ambient)
        cct = f"{p.color_temp_k:.0f}" if p.color_temp_k > 0 else "—"
        print(
            f"  {pct:>5}%{p.input_power_w:>10.2f}{p.luminous_flux_lm:>10.1f}"
            f"{p.efficacy_lm_per_w:>8.2f}{cct:>8}{p.source_temp_c:>11.0f}"
        )
    return 0


def _cmd_simulate(args) -> int:
    weather = None
    if args.weather:
        from ..weather import SyntheticProvider

        weather = SyntheticProvider(
            mean_temp_c=args.ambient, temp_amplitude_c=8.0,
            wind_mean_ms=3.0, solar_peak_w_m2=850.0,
        )

    control = None
    if args.photocell:
        from .environment import PhotocellControl

        control = PhotocellControl()

    sim = LightSimulator(
        spec=_spec(args),
        sim_config=LightSimConfig(
            dt_s=args.dt, duration_s=args.duration,
            mounting_height_m=args.height, target_lux=task_lux(args.task),
        ),
        profile=ConstantDrive(1.0),
        weather=weather,
        control=control,
        weather_epoch0=1704110400.0 if weather else None,
    )
    frames = sim.run_to_list()

    header = f"{'t (s)':>8}{'drive':>7}{'W':>8}{'lm':>9}{'lm/W':>7}{'lux':>8}{'src °C':>8}"
    if args.weather:
        header += f"{'amb °C':>8}{'daylight lux':>14}"
    print(header)
    step = max(1, len(frames) // 16)
    for f in frames[::step]:
        row = (
            f"{f.time_s:>8.0f}{f.drive:>7.2f}{f.input_power_w:>8.1f}"
            f"{f.luminous_flux_lm:>9.0f}{f.efficacy_lm_per_w:>7.1f}"
            f"{f.illuminance_lux:>8.0f}{f.source_temp_c:>8.0f}"
        )
        if f.weather:
            row += f"{f.weather['air_temp_c']:>8.1f}{f.daylight_lux or 0:>14.0f}"
        print(row)

    last = frames[-1]
    energy_kwh = sum(f.input_power_w for f in frames) * args.dt / 3600.0 / 1000.0
    print()
    print(f"ended at {last.luminous_flux_lm:.0f} lm, {last.illuminance_lux:.0f} lux, "
          f"source {last.source_temp_c:.0f} °C")
    print(f"energy: {energy_kwh:.4f} kWh over {args.duration / 3600:.1f} h  "
          f"({last.operating_hours_h:.2f} lamp-hours, {last.switch_cycles:.0f} cycles)")
    return 0


def _spec(args) -> LightSpec:
    if args.lamp:
        return LightSpec(lamp_type=args.lamp, ambient_temp_c=args.ambient)
    return LightSpec(
        technology=args.technology, power_w=args.power, ambient_temp_c=args.ambient
    )


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    ap = argparse.ArgumentParser(description="Light-source simulation & lighting design.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--catalog", action="store_true", help="list technologies and lamps")
    mode.add_argument("--spectrum", action="store_true", help="one lamp's spectrum and output")
    mode.add_argument("--evaluate", action="store_true", help="check a design")
    mode.add_argument("--recommend", action="store_true", help="pick a lamp for a room")
    mode.add_argument("--layout", action="store_true", help="solve an illuminance field")
    mode.add_argument("--dim", action="store_true", help="efficacy and colour vs dim level")
    mode.add_argument("--simulate", action="store_true", help="run it through time")

    ap.add_argument("--lamp", default=None, help="catalog lamp id (see --catalog)")
    ap.add_argument("--technology", default="led", help="technology key, if no --lamp")
    ap.add_argument("--power", type=float, default=15.0, help="rated W, if no --lamp")
    ap.add_argument("--ambient", type=float, default=25.0, help="ambient temperature (°C)")
    ap.add_argument("--task", default="office", help="lighting task (sets the lux target)")
    ap.add_argument("--n", type=int, default=6, help="--evaluate luminaire count")
    ap.add_argument("--length", type=float, default=8.0, help="room length (m)")
    ap.add_argument("--width", type=float, default=6.0, help="room width (m)")
    ap.add_argument("--height", type=float, default=2.25,
                    help="luminaire height above the working plane (m)")
    ap.add_argument("--rows", type=int, default=2, help="--layout luminaire rows")
    ap.add_argument("--cols", type=int, default=3, help="--layout luminaire columns")
    ap.add_argument("--grid", type=int, default=9, help="--layout calculation grid")
    ap.add_argument("--maintenance-hours", type=float, default=0.0,
                    help="age the lamps this far before measuring")
    ap.add_argument("--family", default=None, help="--recommend: restrict to one family")
    ap.add_argument("--duration", type=float, default=1800.0, help="--simulate seconds")
    ap.add_argument("--dt", type=float, default=10.0, help="--simulate timestep (s)")
    ap.add_argument("--weather", action="store_true",
                    help="--simulate with a synthetic diurnal weather cycle")
    ap.add_argument("--photocell", action="store_true",
                    help="--simulate with dusk-to-dawn photocell control")
    args = ap.parse_args(argv)

    if args.catalog:
        return _cmd_catalog()
    if args.spectrum:
        return _cmd_spectrum(args)
    if args.recommend:
        return _cmd_recommend(args)
    if args.layout:
        return _cmd_layout(args)
    if args.dim:
        return _cmd_dim(args)
    if args.simulate:
        return _cmd_simulate(args)
    return _cmd_evaluate(args)


if __name__ == "__main__":
    raise SystemExit(main())
