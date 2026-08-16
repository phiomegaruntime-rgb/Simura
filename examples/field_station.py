"""One site, every component: design an off-grid field station end to end.

Each Simura component has its own example already -- this is the one that shows
them *composing*. A remote workshop has to be lit through a winter night off a
battery, and no one part of that problem can be solved on its own:

* the **lights** decide how much current the site draws,
* the current decides what **wire** the run needs,
* the wire's voltage drop comes back and changes what the lights actually do,
* the **battery** has to carry all of it overnight,
* and the **weather** moves all four at once -- ambient sets a fluorescent's
  vapour pressure and an LED's junction temperature in *opposite* directions,
  cools the cable, warms the pack, and decides whether the sun did any of the
  work for free.

Run it and the loop closes: the design that passes at 20 C fails at -10 C, and
the cable chosen for the LED is the wrong cable for the filament.

Usage:
    python examples/field_station.py

Only needs numpy. Add --live to pull the real sky over the site from Open-Meteo
instead of the built-in synthetic day (needs a network connection).
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
    Light,
    LightSpec,
    evaluate_installation,
    recommend_lamp,
    task_lux,
)
from simura.sim import (  # noqa: E402
    CellParams,
    ConstantCurrent,
    PackConfig,
    SimConfig,
    Simulator,
)
from simura.weather import StaticProvider, SyntheticProvider  # noqa: E402
from simura.wires import (  # noqa: E402
    WireSpec,
    evaluate_run,
    recommend_gauge,
)

# -- the site ----------------------------------------------------------------

# A 14 x 8 m workshop at a remote station, lit to a workshop's standard, running
# off a 48 V battery bank 35 m away in its own hut. The distance is the whole
# reason this is interesting: 35 m of cable at 48 V is a real voltage-drop
# problem, and voltage drop is what turns a lighting design into a wiring one.
LENGTH_M, WIDTH_M, MOUNT_M = 14.0, 8.0, 2.6
TASK = "workshop"
BUS_V = 48.0
RUN_M = 35.0
NIGHT_H = 14.0  # a midwinter night at high latitude

EPOCH = 1_704_110_400.0  # fixed instant, so the run is reproducible

RULE = "-" * 72


def head(n: int, title: str) -> None:
    print(f"\n{n}) {title}")
    print(RULE)


# -- 1. the sky --------------------------------------------------------------


def sky(live: bool) -> tuple[float, float, float, str]:
    """The design condition: a cold, still, sunless winter night."""
    if live:
        try:
            from simura.weather import OpenMeteoProvider

            # Tromso, Norway -- somewhere a midwinter night really is 14 hours.
            provider = OpenMeteoProvider(latitude=69.65, longitude=18.96)
            s = provider.at(EPOCH)
            return s.air_temp_c, s.wind_speed_ms, s.solar_w_m2, "Open-Meteo (live)"
        except Exception as exc:  # network, rate limit, anything
            print(f"  (live weather unavailable -- {type(exc).__name__}; using synthetic)")

    # The synthetic provider gives a full diurnal cycle with no network at all.
    s = SyntheticProvider(
        mean_temp_c=-8.0, temp_amplitude_c=4.0, solar_peak_w_m2=0.0, wind_mean_ms=1.5
    ).at(EPOCH)
    return s.air_temp_c, s.wind_speed_ms, s.solar_w_m2, "synthetic"


# -- 2..5 the chain ----------------------------------------------------------


def main(live: bool = False) -> None:
    print(f"Simura field station -- {LENGTH_M:g} x {WIDTH_M:g} m {TASK}, "
          f"{task_lux(TASK):.0f} lux, {BUS_V:g} V bus, {RUN_M:g} m from the battery hut")

    head(1, "The sky over the site")
    air_c, wind_ms, solar, src = sky(live)
    print(f"  source        : {src}")
    print(f"  air           : {air_c:.1f} °C")
    print(f"  wind          : {wind_ms:.1f} m/s")
    print(f"  solar         : {solar:.0f} W/m²   ({'night' if solar < 1 else 'some daylight'})")
    print("\n  This one sample is handed to every component below. Nothing")
    print("  re-derives the weather; they all read the same sky.")

    # -- lights --------------------------------------------------------------
    head(2, "Light the workshop — let the catalog choose")
    warm = StaticProvider(air_temp_c=20.0, wind_speed_ms=0.0, solar_w_m2=0.0)
    cold = StaticProvider(air_temp_c=air_c, wind_speed_ms=wind_ms, solar_w_m2=solar)

    rec = recommend_lamp(
        length_m=LENGTH_M, width_m=WIDTH_M, mounting_height_m=MOUNT_M,
        task=TASK, maintenance_hours=8000.0, weather=warm,
    )
    print(f"  {rec.rationale}")
    lamp_id = rec.lamp_type.id if rec.lamp_type else "led-15-e27"
    n_lum = rec.n_luminaires

    print(f"\n  {'lamp':<18}{'family':<15}{'n':>4}{'W/m²':>8}{'lux':>7}{'CRI':>5}")
    for alt in rec.alternatives[:5]:
        print(f"  {alt['lamp_id']:<18}{alt['family'].replace('_', ' '):<15}"
              f"{alt['n_luminaires']:>4}{alt['power_density_w_per_m2']:>8.2f}"
              f"{alt['maintained_lux']:>7.0f}{alt['cri']:>5.0f}")

    # -- the weather bites ---------------------------------------------------
    head(3, "Now design it for the night it will actually run in")
    print(f"  The same installation, evaluated at {air_c:.0f} °C instead of 20 °C.")
    print("  Ambient does not move every technology the same way:\n")
    print(f"  {'lamp':<18}{'at 20 °C':>12}{'at ' + format(air_c, '.0f') + ' °C':>12}{'change':>10}")
    for cand in (lamp_id, "fl-t8-36", "hps-150-e40"):
        a_warm = evaluate_installation(
            LightSpec(lamp_type=cand), n_luminaires=n_lum,
            length_m=LENGTH_M, width_m=WIDTH_M, mounting_height_m=MOUNT_M,
            task=TASK, maintenance_hours=8000.0, weather=warm,
        )
        a_cold = evaluate_installation(
            LightSpec(lamp_type=cand), n_luminaires=n_lum,
            length_m=LENGTH_M, width_m=WIDTH_M, mounting_height_m=MOUNT_M,
            task=TASK, maintenance_hours=8000.0, weather=cold,
        )
        delta = (a_cold.maintained_lux / a_warm.maintained_lux - 1.0) * 100.0 if a_warm.maintained_lux else 0.0
        print(f"  {cand:<18}{a_warm.maintained_lux:>9.0f} lx{a_cold.maintained_lux:>9.0f} lx{delta:>9.1f}%")
    print("\n  Three technologies, three different answers to the same night. The")
    print("  LED gains — its junction runs cooler. The fluorescent tube collapses,")
    print("  because ambient sets its mercury vapour pressure. The sodium lamp")
    print("  barely notices: its arc tube runs at a temperature the weather cannot")
    print("  reach. None of that comes from a lookup table — it falls out of the")
    print("  spectrum each lamp is computed to radiate.")

    # A quieter failure the same call catches: an incandescent is *dead* at 8000
    # hours. It is rated for about a thousand, so a maintained-lumen check does
    # not dim it -- it zeroes it.
    dead = evaluate_installation(
        LightSpec(lamp_type="inc-60-e27"), n_luminaires=n_lum,
        length_m=LENGTH_M, width_m=WIDTH_M, mounting_height_m=MOUNT_M,
        task=TASK, maintenance_hours=8000.0, weather=warm,
    )
    fresh = evaluate_installation(
        LightSpec(lamp_type="inc-60-e27"), n_luminaires=n_lum,
        length_m=LENGTH_M, width_m=WIDTH_M, mounting_height_m=MOUNT_M,
        task=TASK, maintenance_hours=0.0, weather=warm,
    )
    print(f"\n  (And the filament nobody costed: inc-60-e27 gives {fresh.maintained_lux:.0f} lx new")
    print(f"   and {dead.maintained_lux:.0f} lx at 8000 h — it is rated for about a thousand. At the end")
    print("   of this maintenance cycle it is not dim, it is out.)")

    # -- wires ---------------------------------------------------------------
    head(4, "Size the cable the lights hang off")
    chosen = evaluate_installation(
        LightSpec(lamp_type=lamp_id), n_luminaires=n_lum,
        length_m=LENGTH_M, width_m=WIDTH_M, mounting_height_m=MOUNT_M,
        task=TASK, maintenance_hours=8000.0, weather=cold,
    )
    load_a = chosen.power_w / BUS_V
    print(f"  {n_lum} × {lamp_id} = {chosen.power_w:.0f} W at {BUS_V:g} V → {load_a:.1f} A")
    print(f"  over {RUN_M:g} m, out and back.\n")

    wrec = recommend_gauge(
        current_a=load_a, length_m=RUN_M, system_voltage_v=BUS_V,
        max_drop_pct=3.0, round_trip=True, weather=cold,
    )
    print(f"  {wrec.rationale}")
    if wrec.wire_type is not None:
        wa = wrec.assessment
        print(f"  chosen        : {wrec.wire_type.id}")
        print(f"  voltage drop  : {wa.voltage_drop_v:.2f} V  ({wa.voltage_drop_pct:.2f} %)")
        print(f"  loss          : {wa.power_loss_w:.1f} W")
        print(f"  conductor     : {wa.steady_state_temp_c:.1f} °C")

    # The point of the exercise: what the *undersized* cable does.
    print("\n  And the cable somebody actually pulls, because it was on the van:")
    thin = evaluate_run(
        WireSpec(wire_type="cu-14-thhn90", length_m=RUN_M),
        current_a=load_a, system_voltage_v=BUS_V,
        max_drop_pct=3.0, round_trip=True, weather=cold,
    )
    print(f"  cu-14-thhn90  : {thin.voltage_drop_v:.2f} V drop "
          f"({thin.voltage_drop_pct:.2f} %), {thin.power_loss_w:.1f} W lost, "
          f"{thin.steady_state_temp_c:.1f} °C")
    for p in thin.problems:
        print(f"    - {p}")

    # -- the loop closes -----------------------------------------------------
    head(5, "What that voltage drop does back at the fitting")
    sagged = BUS_V - thin.voltage_drop_v
    print(f"  That thin cable leaves the lamps {sagged:.1f} V instead of {BUS_V:.0f} V.")
    print("  Walk the bus down and the two technologies fail in completely")
    print("  different ways:\n")
    print(f"  {'bus':>6}  {'LED flux':>9}{'LED amps':>10}   |{'filament flux':>15}"
          f"{'amps':>7}{'colour':>9}")
    for frac in (1.0, 0.95, 0.9, 0.85, 0.8, sagged / BUS_V):
        v = BUS_V * frac
        row = f"  {v:>5.1f}V  "
        for cand in (lamp_id, "inc-60-e27"):
            light = Light(LightSpec(lamp_type=cand, supply_voltage_v=BUS_V))
            full = light.at_supply(BUS_V, ambient_c=air_c)
            low = light.at_supply(v, ambient_c=air_c)
            flux_pct = (low.point.luminous_flux_lm / full.point.luminous_flux_lm * 100.0
                        if full.point.luminous_flux_lm else 0.0)
            amp_pct = (low.supply_current_a / full.supply_current_a * 100.0
                       if full.supply_current_a else 0.0)
            if cand == lamp_id:
                row += f"{flux_pct:>8.1f}%{amp_pct:>9.1f}%   |"
            else:
                row += f"{flux_pct:>14.1f}%{amp_pct:>6.1f}%{low.point.color_temp_k:>8.0f}K"
        print(row)
    print("\n  The LED holds its light almost perfectly — and pays for it by pulling")
    print("  *more* current as the bus sags, which sags the bus further. Then its")
    print("  driver hits its limit and the light goes out completely, with no")
    print("  warning at all. The filament dims from the very first volt and reddens")
    print("  as it goes: far worse light, and the only honest voltmeter on the site.")

    # -- battery -------------------------------------------------------------
    head(6, "Carry it through the night")
    wh = chosen.power_w * NIGHT_H
    print(f"  {chosen.power_w:.0f} W for {NIGHT_H:g} h = {wh:.0f} Wh at {BUS_V:g} V "
          f"→ {wh / BUS_V:.0f} Ah out of the bank.\n")

    # A 16S4P bank of 100 Ah cells, run at the site's real draw and in the site's
    # real weather -- the same simulator the twin core streams from.
    sim = Simulator(
        sim_config=SimConfig(dt_s=10.0, duration_s=NIGHT_H * 3600.0),
        pack_config=PackConfig(
            series=16, parallel=4,
            cell=CellParams(capacity_ah=100.0),
            initial_soc=0.95,
            ambient_temp_c=air_c,
        ),
        profile=ConstantCurrent(amps=load_a),
        weather=cold,
        weather_epoch0=EPOCH,
    )
    frames = list(sim.run())
    first, last = frames[0], frames[-1]
    print(f"  pack          : 16S4P, 100 Ah cells")
    print(f"  start         : {first.pack_soc * 100:5.1f} % SoC, "
          f"{first.pack_voltage_v:6.2f} V, {first.max_temp_c:5.1f} °C")
    print(f"  after {NIGHT_H:g} h    : {last.pack_soc * 100:5.1f} % SoC, "
          f"{last.pack_voltage_v:6.2f} V, {last.max_temp_c:5.1f} °C")
    print(f"  used          : {(first.pack_soc - last.pack_soc) * 100:.1f} % of the bank")
    print(f"  imbalance     : {last.voltage_imbalance_v * 1000:.1f} mV across the string")
    print(f"\n  The bank ends the night at {last.max_temp_c:.1f} °C with {air_c:.0f} °C")
    print("  outside — it is working too gently to heat itself out of the cold, and")
    print("  a lithium bank that cold is exactly where charge acceptance falls off.")
    print("  Which is the next thing this site would have to solve, and the reason")
    print("  the twin is worth having before the cable is ever pulled.")

    # -- the point -----------------------------------------------------------
    print(f"\n{RULE}")
    print("Four physics, one site, one sky. The lighting choice set the")
    print("current, the current set the cable, the cable came back and changed")
    print("the light, and the weather moved all of it at once — in different")
    print("directions for different physics. That is the whole argument for")
    print("putting them in one platform instead of five spreadsheets.")
    print(RULE)


if __name__ == "__main__":
    main(live="--live" in sys.argv)
