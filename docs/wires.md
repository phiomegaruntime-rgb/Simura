# Wires

A battery is only half of an electrical system — the other half is the **wiring**
that moves its energy somewhere useful. The `simura.wires` package models a
conductor the way `simura.sim` models a cell: real physics (resistance, voltage
drop, ohmic loss, electro-thermal heating), a catalog of real parts to pick from,
injectable faults, and — the part an engineer actually reaches for — **wiring
logic and planning**.

Like `simura.weather`, it is a **standalone, domain-agnostic package**: it knows
conductors and electrical physics, not batteries. The multi-node network solver
lets several nodes and wires be composed and solved together, independent of any
battery model.

## The physics

For a single conductor of cross-section `A` and length `L`:

| Quantity | Relation |
| --- | --- |
| Resistance | `R(T) = rho_20·(1 + alpha·(T − 20))·L / A` |
| Voltage drop | `ΔV = I·R` |
| Ohmic loss | `P = I²·R` |
| Temperature | `dT/dt = (I²R − k_cool·(T − T_amb)) / C_th` (explicit Euler) |

Resistance rises with temperature and temperature rises with `I²R` loss — the
positive feedback that makes an over-current wire dangerous. Steady state is
`ΔT = I²R / k_cool`; thermal capacity and convective cooling default to
geometry-based estimates from the conductor's size.

## The catalog

The "parts bin" is a curated directory of conductor materials (copper, aluminium,
tinned copper), AWG gauges, insulation classes (PVC / THHN / XLPE / silicone, each
with a temperature rating), and off-the-shelf `WireType`s with reference ampacity.

```python
from simura.wires import list_wire_types, wire_type_for, awg_area_mm2

awg_area_mm2(12)                 # 3.31 mm^2 (the textbook value)
wire_type_for("cu-12-thhn90")    # Copper 12 AWG THHN-90, 25 A reference ampacity
```

!!! warning "Reference values only"
    Ampacity depends on installation, grouping, ambient temperature and the
    governing code (NEC / IEC). The catalog figures are single-conductor,
    free-air reference numbers for orientation — **size real wiring against the
    applicable code.**

## Planning a run

`evaluate_run` checks one wire against one load; `recommend_gauge` sizes the
smallest catalog wire that satisfies ampacity, voltage drop and temperature.
Neither raises — problems come back as a list.

```python
from simura.wires import WireSpec, evaluate_run, recommend_gauge

a = evaluate_run(WireSpec(awg=12, length_m=20), current_a=15,
                 system_voltage_v=12, max_drop_pct=3, round_trip=True)
print(a.voltage_drop_pct, a.problems)   # 27.8, ['voltage drop 27.8% exceeds ...']

rec = recommend_gauge(current_a=15, length_m=20, system_voltage_v=12, max_drop_pct=3)
print(rec.wire_type.name, rec.rationale)
```

`round_trip=True` accounts for the there-and-back path of a two-conductor DC
circuit (the conductor *temperature* is always evaluated per single conductor).

### Planning for the weather

Both checks take an optional `weather` sample (a [`WeatherSample`](weather.md)),
so you can size for a specific day rather than a nominal 25 °C:

```python
from simura.weather import StaticProvider

hot = StaticProvider(air_temp_c=45, wind_speed_ms=0, solar_w_m2=800).at(0)
a = evaluate_run(WireSpec(wire_type="cu-12-thhn90", length_m=20),
                 current_a=24, system_voltage_v=48, round_trip=True, weather=hot)
print(a.ampacity_a, a.steady_state_temp_c, a.problems)
# ampacity derated to ~21.6 A, conductor ~121 °C -> over ampacity AND over rating

rec = recommend_gauge(current_a=50, length_m=2, system_voltage_v=48,
                      max_drop_pct=10, weather=hot)   # a hot day sizes the gauge up
```

Weather moves two things:

- **Ampacity is derated for ambient** using the standard correction
  `sqrt((T_rating − T_amb) / (T_rating − T_ref))` (ref ≈ 30 °C) — less headroom to
  the insulation rating on a hot day, more on a cold one. This is **ambient-only
  and deliberately conservative**: it does not credit the wind (which you can't
  guarantee), so `recommend_gauge` never under-sizes.
- **The predicted conductor temperature** reflects the full weather — ambient plus
  wind cooling and absorbed sun — so on a windy day the run can read *within* its
  temperature rating even while the (conservative) ampacity check still flags it.

The assessment records the `ambient_temp_c` it used. See the [Weather](#weather)
section below for the underlying coupling.

## Networks

Connect several nodes and wires, fix a source voltage, draw loads, and solve the
whole thing with nodal analysis. Each segment's current, drop, loss, temperature
and utilisation come back, plus a rolled-up problem list.

```python
from simura.wires import WireNetwork, WireSpec

net = WireNetwork()
net.add_node("source", voltage=12.0)
net.add_node("junction", load_a=8.0)
net.add_node("end", load_a=6.0)
net.add_segment("trunk", "source", "junction", WireSpec(awg=10, length_m=5))
net.add_segment("branch", "junction", "end", WireSpec(awg=12, length_m=8))
result = net.solve()
print(result.node_voltages)   # source > junction > end
```

Resistance and temperature are iterated to a fixed point, so segments warm up and
currents re-settle self-consistently.

## Simulating a transient

`WireSimulator` steps a wire through a current profile and yields `WireTelemetry`
frames — the same generator shape as the battery `Simulator`.

```python
from simura.wires import WireSimulator, WireSimConfig, WireSpec, ConstantCurrent

sim = WireSimulator(
    spec=WireSpec(awg=14, length_m=2, insulation="THHN-90"),
    sim_config=WireSimConfig(dt_s=1.0, duration_s=900.0),
    profile=ConstantCurrent(25.0),   # over the 20 A rating
)
for frame in sim.run():
    ...   # frame.temp_c climbs past frame.temp_rating_c -> frame.over_temp
```

## Weather

A conductor's temperature is a heat balance with its environment, so weather is a
first-order driver — the same standard conductor heat balance behind *dynamic line
rating* (cf. IEEE Std 738): `I²R + solar` heats it, `convection + radiation` cools
it. The `WireSimulator` couples to the **reusable [`simura.weather`](weather.md)
package** exactly as the battery pack does, through a thin wire-specific
translation (`simura.wires.environment`) that maps a `WeatherSample` onto three
levers the `Wire` model already has:

| Weather | Lever | Effect |
| --- | --- | --- |
| Air temperature | ambient `T_amb` | the temperature the conductor cools toward |
| Wind speed | convective cooling `k_cool` | forced convection carries heat away faster |
| Solar irradiance | absorbed heat load | a sunlit conductor runs warm at zero current |

```python
from simura.weather import SyntheticProvider
from simura.wires import WireSimulator, WireSimConfig, WireSpec, ConstantCurrent

sim = WireSimulator(
    spec=WireSpec(awg=14, length_m=5, insulation="THHN-90"),
    sim_config=WireSimConfig(dt_s=1.0, duration_s=2400.0),
    profile=ConstantCurrent(25.0),
    weather=SyntheticProvider(mean_temp_c=30, wind_mean_ms=4, solar_peak_w_m2=900),
)
last = sim.run_to_list()[-1]
print(last.temp_c, last.weather)   # conditions ride along on every frame
```

The same 25 A conductor settles near **210 °C** on a still, hot day but around
**90 °C** in a stiff breeze — which is precisely why real line ratings are
weather-dependent. Any `WeatherProvider` works (`StaticProvider`,
`SyntheticProvider`, `CsvReplayProvider`, live `OpenMeteoProvider`); the
coefficients (`WireEnvironmentCoupling`) are illustrative and tunable per
installation. Wind rides the fault-effect `cooling_mult` channel and solar the
`extra_heat_w` channel, so the integrator needs no new inputs.

!!! note "Exposed runs vs. conduit"
    Wind and sun matter most for *exposed* conductors (overhead drops, PV strings,
    outdoor battery leads). For an indoor or in-conduit run, set
    `shading_frac=1` (no solar) and a low wind — ambient still applies.

## Faults

The same accumulator pattern as the battery side: `ResistanceGrowth` (corrosion),
`ContactResistance` (loose joint), `ConductorDamage` (nicked strands), `Insulation
Degradation` (aged insulation), `GroundFault` (leakage). They compose and are
windowed in time.

## Validation

The wiring counterpart to the battery [Validation](validation.md) pipeline: check
the conductor model against **published reference standards** rather than lab
datasets. A conductor's authoritative reference is a compact, public table — DC
resistance per unit length by gauge — so the whole check runs offline.

`simura.wires.validation` bundles a few standards (annealed copper at 20 °C and
75 °C, hard-drawn aluminium), replays each gauge through the *same* `Wire` the
twin uses, and reports the per-gauge percent error.

```python
from simura.wires.validation import get_standard, validate_reference

report = validate_reference(get_standard("copper-annealed-20c").reference())
print(report.metrics)   # {'rmse_pct': 2.55, 'mae_pct': 2.55, 'max_abs_pct': 2.60, 'mean_bias_pct': -2.55}
```

The small, near-constant copper bias is honest and expected: Simura models pure
copper (`ρ = 1.68e-8 Ω·m`) while the standard uses annealed IACS copper
(`1.7241e-8`), so the model reads ~2.5 % below across every gauge. You can also
validate against your **own** measured resistances via `load_upload_csv` (a CSV
with an AWG column and a DC-resistance column).

!!! note "Reference physics, not a code table"
    The published values are computed from the standard resistivity and the
    nominal AWG cross-section (`R = ρ·L/A`). They validate the model's conductor
    physics — **not** installed cable, which adds stranding, coating and code
    derating.

## CLI

```bash
python -m simura.wires --catalog
python -m simura.wires --evaluate --awg 12 --length 20 --current 15 --voltage 12
python -m simura.wires --recommend --current 15 --length 20 --voltage 12 --max-drop 3
python -m simura.wires --network
python -m simura.wires --simulate --awg 14 --current 25
python -m simura.wires --simulate --awg 14 --current 25 --weather --wind 8   # weather-coupled

python -m simura.wires.validation --list
python -m simura.wires.validation --standard copper-annealed-20c
```

See `examples/wire_planning.py`, `examples/wire_thermal.py` and
`examples/wire_weather.py` for runnable walkthroughs.

## In the dashboard

The **Wires** component has two sub-views, backed by the pure-compute
`/api/wires/*` endpoints (no MQTT, no DB):

- **Wiring planner** — pick a run and a load and *check* it (ampacity / voltage
  drop / temperature, with the problems listed) or *recommend* the smallest
  adequate gauge, plus the full catalog as a table. A **Weather (optional)** panel
  sizes the run for a specific day — ambient derates the ampacity, wind and sun
  move the predicted temperature.
- **Validation** — validate the conductor model against a bundled standard or your
  own measured-resistance CSV, with metric tiles and a published-vs-model
  resistance chart.
