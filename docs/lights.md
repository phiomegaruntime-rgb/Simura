# Lights

Batteries store energy and wires move it. **Lighting is where a large share of it
is finally spent** — and it is the one place where the useful output is not
measured in watts at all, but in what a human eye can see.

The `simura.lights` package models a light source the way `simura.sim` models a
cell: real physics from first principles, a catalog of real parts, injectable
faults, and the design questions an engineer actually asks. Like `simura.weather`
and `simura.wires`, it is a **standalone, domain-agnostic package** — it knows
light and the human eye, not batteries.

## Efficacy is computed, never looked up

This is the design decision everything else follows from.

A light source is, physically, a **spectral power distribution**: how many watts
it radiates at each wavelength. Everything a lighting engineer quotes falls out
of that SPD and the eye's response to it:

| Quantity | Relation |
| --- | --- |
| Luminous flux | `Φv = 683 · ∫ Φe(λ)·V(λ) dλ` |
| Efficacy of radiation | `LER = Φv / ∫ Φe(λ) dλ` (lm per **radiated** watt) |
| Chromaticity | `X,Y,Z = ∫ Φe·x̄,ȳ,z̄ dλ → (x, y)` |
| Colour temperature | `CCT = f(x, y)` |
| Lamp efficacy | `LER × radiant_efficiency × transmission × derating` |

`V(λ)` is the CIE 1931 photopic luminosity function and 683 lm/W at 555 nm is the
definition of the candela. Simura uses the Wyman–Sloan–Shirley (2013) analytic fit
to the colour-matching functions, which keeps the whole thing pure standard
library — and because the fit is an approximation, its error is itself something
[the validation](#validation) measures rather than assumes.

Deriving efficacy this way is what makes the model *predictive*. Three examples,
none of which is coded anywhere:

- **Dim an incandescent lamp** and the filament cools. The Planck curve slides
  into the infrared, so the efficacy of radiation collapses and the light turns
  orange. At 80% on the dimmer a 60 W lamp still draws 71% of its power and
  delivers 40% of its light.
- **A warm-white LED loses to a cool-white one.** More phosphor means more Stokes
  loss and more light in the deep red where the eye is weak.
- **Low-pressure sodium beats everything ever built** at 180 lm/W and renders no
  colour at all, because all of its light is one yellow doublet 3 nm from the
  eye's peak sensitivity.

```python
from simura.lights import Light, LightSpec

lamp = Light(LightSpec(lamp_type="inc-60-e27"))
lamp.operating_point(1.0).efficacy_lm_per_w    # 14.1 lm/W at 2726 K
lamp.operating_point(0.5).efficacy_lm_per_w    #  3.1 lm/W at 2183 K
```

## Every kind of light source

Four physical families, fourteen technologies, twenty catalog lamps.

### Thermal radiators — `incandescent`, `halogen`

A tungsten filament, hot enough to glow. Everything is solved from its energy
balance:

```
P_electrical(T) = V² / R(T),      R(T) = R_293 · (T/293)^1.2
P_out(T)        = A · M(T) + G_cond · (T − T_ambient)
```

`T` is whatever temperature balances the two, found by bisection. The filament
geometry is back-solved *once* from the catalog's rated power and design
temperature, so the lamp reproduces its own datasheet at the design point and then
predicts everything off it — dimmed, over-volted, or in a cold room.

Tungsten is not a greybody: it emits ~0.44 of a blackbody across the visible but
only ~0.28 in the infrared. Radiating selectively in the band the eye can use is
worth about 50% more efficacy, and no filament lamp's numbers come out right
without it.

### Solid state — `led`, `led_high_cri`, `laser_diode`

A semiconductor junction obeying a diode law, with a forward voltage that falls
as it heats:

```
Vf(I, Tj) = Vf,rated + n·VT·ln(I/I_rated) + (I − I_rated)·Rs + kV·(Tj − 25)
```

Flux is proportional to current, less **efficiency droop** at high current density
and less the junction's thermal derating (about −0.22%/K). The junction sits at
`Tj = T_ambient + P_heat · R_th`, and since none of the heat leaves in the beam,
that thermal path is the entire engineering problem. A luminaire that spreads its
watts over more dies runs each one softer, which buys back droop and lowers the
junction temperature — the standard way to build a high-efficacy fitting out of
ordinary LEDs.

The phosphor blend is not fixed. A lamp's rated colour temperature selects a point
on the curve of blends that produce *white* light — which is what LED binning
really is — and the efficacy is whatever the spectrum there gives.

### Low-pressure discharge — `fluorescent_t8`, `cfl`, `induction`, `low_pressure_sodium`, `neon`

A low-pressure arc in mercury or sodium vapour. Output depends sharply on
**ambient temperature**, because ambient sets the vapour pressure and the 254 nm
resonance output peaks at one pressure. A T8 tube at 0 °C manages a little over
half its rated output, which is exactly why unheated spaces went LED.

The falloff is asymmetric — the pressure drops away below the optimum faster than
it climbs above it — so it is modelled with two Gaussian widths.

### High-pressure discharge — `metal_halide`, `high_pressure_sodium`, `mercury_vapor`, `xenon_arc`

A high-pressure arc. The arc holds a roughly fixed voltage and the ballast sets
the current, so source power is nearly constant; what varies is *availability*.
These lamps take minutes to warm up, and a hot arc tube **will not restrike** until
it has cooled — kill the power to a metal-halide floodlight and you wait ten
minutes for light, which is why they are never used where an instant restart
matters.

!!! warning "Reference values only"
    The catalog's `radiant_efficiency` figures come from each technology's standard
    energy balance, and the published fluxes are long-established catalogue data.
    Real products vary by tens of percent. **Specify real lighting against
    photometric test reports, not against this catalog.**

## Photometry: lumens to lux

Flux is what a lamp emits in every direction. What anybody cares about is
**illuminance** where they are standing.

```
Ω = 2π(1 − cos(θ/2))        solid angle of a beam       [sr]
I = Φ / Ω                   luminous intensity          [cd]
E = I · cos(α) / d²         illuminance                 [lux]
```

The last is the inverse-square law with Lambert's cosine, and between them they
explain nearly every lighting mistake ever made. For a whole room, per-point
geometry is the wrong tool — most light arrives after bouncing — so the **lumen
method** folds that into a utilisation factor:

```
E_average = Φ_total · UF · LLF / area
```

`UF` from the room's shape and surface reflectances, `LLF` the light loss factor
covering lamp ageing and dirt.

## Planning an installation

`evaluate_installation` checks a design; `recommend_lamp` picks one. Neither
raises — problems come back as a list.

```python
from simura.lights import LightSpec, evaluate_installation, recommend_lamp

a = evaluate_installation(
    LightSpec(lamp_type="led-15-e27"), n_luminaires=24,
    length_m=12, width_m=9, mounting_height_m=2.5,
    task="office", maintenance_hours=8000,
)
print(a.maintained_lux, a.power_density_w_per_m2, a.problems)

rec = recommend_lamp(length_m=12, width_m=9, task="office")
print(rec.rationale)
for alt in rec.alternatives:
    print(alt["lamp_id"], alt["power_density_w_per_m2"], alt["cri"])
```

Checks run against illuminance for the task (EN 12464-1-style targets), a minimum
colour rendering index, and an installed-power guideline. Restricting
`recommend_lamp` to one `family` asks what the best possible filament or discharge
answer would have been.

### Maintained, not initial

The commonest lighting mistake is designing for day one. Lamps depreciate,
luminaires collect dirt, and a design that just clears 500 lux new will be
delivering 350 long before anyone replaces anything. Pass `maintenance_hours` and
every lamp is aged that far before its output is counted; `recommend_lamp` does it
by default at 8000 hours.

That ageing is also what makes the comparison fair. A fluorescent tube and an LED
that match on day one do not match three years later.

## Layouts: where the light actually falls

An average hides the two failures that matter. A room lit to a perfect 500 lux
average can have 900 lux under each fitting and 150 between them.

```python
from simura.lights import Layout, LightSpec

layout = Layout(length_m=12, width_m=9)
layout.grid_regular(rows=4, cols=6, height_m=3.0, spec=LightSpec(lamp_type="led-15-e27"))
result = layout.solve(target_lux=500, min_uniformity=0.6)
print(result.average_lux, result.uniformity, result.problems)
```

The measure is **uniformity** `U0 = E_min / E_average`, with 0.6 the usual
requirement for a working interior. The solve uses the standard **split-flux**
treatment: geometry gives the direct component and its shape, and interreflected
light is added as a uniform term sized to the lumen method's utilisation factor.
Bounced light really is close to uniform, which is why a room with light walls is
not just brighter but more even.

Any luminaire can carry faults, so a single failed or fouled fitting can be
dropped into a working layout and the dark patch it leaves measured.

## Weather and daylight

Weather reaches a luminaire through **two entirely separate channels**, which is
one more than it reaches a battery or a conductor through.

**Thermally**, it changes what the lamp can do — and in opposite directions
depending on technology:

| Ambient | T8 fluorescent | 15 W LED |
| --- | --- | --- |
| −15 °C | 24% | 111% |
| −5 °C | 43% | 108% |
| 25 °C | 100% | 100% |
| 45 °C | 71% | 93% |

**Optically**, it changes what the lamp is *needed for*:

```
E_daylight = GHI · 110 lm/W · transmission
```

Feed that into a control and the lamp answers the real sky:

- `PhotocellControl` — dusk-to-dawn switching, the control on essentially every
  outdoor light in the world, and the reason street-lighting energy is a function
  of latitude and season rather than of a timeclock.
- `DaylightHarvesting` — dims to hold a constant *total* illuminance, supplying
  only the difference between the target and what the sky already delivers.

The two layer, exactly as real installations do: a schedule or occupancy sensor
decides *whether* the lights are on, and the daylight sensor decides *how bright*.

!!! warning "Indoors, `transmission` is the daylight factor"
    Not the glass's ~0.8 transmission, but the share of the *exterior horizontal*
    illuminance that reaches a desk — typically **0.02–0.05**. A bright day is
    80 klx outside; putting 0.35 there would claim 28 klx on the desk and make any
    daylight control look miraculous.

Solar geometry and a clear-sky irradiance model are included, so a photocell works
with no weather source at all:

```python
from simura.lights import solar_elevation_deg, clear_sky_ghi_w_m2, daylight_illuminance_lux

h = solar_elevation_deg(51.5, -0.13, 1718971200)   # degrees above the horizon
daylight_illuminance_lux(clear_sky_ghi_w_m2(h))    # lux on a horizontal plane
```

## Faults

Lighting rarely goes dark. It dims, shifts colour, and starts to flicker — and
telling those apart from telemetry is the whole job, because each is a different
maintenance decision.

| Fault | What it does |
| --- | --- |
| `LumenDepreciation` | Output decays while the meter runs — the failure that costs most and is noticed least |
| `PhosphorDegradation` | A cooked phosphor: less light, and what is left drifts blue |
| `HeatsinkLoss` | The thermal path degrades, the junction cooks, and it accelerates |
| `DriverFault` | Control gear delivering the wrong current |
| `SupplyVoltageFault` | A brown-out — brutal on filaments, where light goes as `V^3.4` |
| `Flicker` | Periodic modulation at a chosen depth and frequency |
| `LensFouling` | Purely optical: the lamp is fine, less light escapes |
| `Burnout` | The one unambiguous fault |

## Validation

The lighting model is checked against published data at **five different depths**,
plus the live sky. All bundled references are computed offline.

| Standard | What it validates | Result |
| --- | --- | --- |
| `cie-photopic-1931` | The analytic colour-matching fit against the tabulated CIE observer | RMSE 0.003 absolute |
| `blackbody-cct-locus` | Planck + chromaticity + McCamy: a blackbody's CCT is its own temperature | 0.8% |
| `lamp-efficacy-published` | The whole chain, for 20 real lamps across 4 families | 6.5% |
| `led-junction-derating` | The solid-state thermal derating law | 0.9% |
| `fluorescent-ambient-response` | The vapour-pressure response | 9.0% |

The photopic standard is deliberately reported in **absolute** units as well as
percent: `V(λ)` passes through 0.0004 in the far violet, where any error at all is
a huge relative one. Every report carries both, so neither can flatter the model.

```bash
python -m simura.lights.validation --list
python -m simura.lights.validation --all
python -m simura.lights.validation --standard lamp-efficacy-published
```

### Real-time validation against the live sky

One check here is unlike anything else in Simura: its reference data does not ship
with the repository. It fetches the last 48 hours of **measured shortwave
radiation** for a real place from [Open-Meteo](https://open-meteo.com) (free, no
API key) and checks the daylight model against it.

```bash
python -m simura.lights.validation --live --lat 51.5 --lon -0.13
```

The daylight chain has no fitted parameters — solar geometry, the Haurwitz
clear-sky model, and the 110 lm/W efficacy of daylight — so any gap is real.

**Read it honestly.** A clear-sky model cannot know about clouds, so on an overcast
day it over-predicts badly, and that is the definition of the model rather than a
defect. The report therefore separates the two:

- **clearness index** `kt = measured / clear-sky` per hour;
- **clear-hour metrics**, restricted to the clearest hours — the honest test of
  the geometry and the efficacy constant;
- **envelope violations**, hours where the measurement *exceeded* the clear-sky
  ceiling. A few are normal (cloud edge-brightening); many would mean the
  clear-sky model is systematically low;
- **all-hours metrics**, which measure how cloudy the window was, not how good the
  model is.

You can also validate against your **own** measurements — an integrating sphere, a
lux meter, or a stack of datasheets — as a CSV, in the dashboard or via
`load_upload_csv`.

## CLI

```bash
python -m simura.lights --catalog                       # technologies and lamps
python -m simura.lights --spectrum --lamp led-9-e27     # SPD + everything derived
python -m simura.lights --dim --lamp inc-60-e27         # efficacy and colour vs dimming
python -m simura.lights --recommend --length 12 --width 9 --task office
python -m simura.lights --layout --lamp led-15-e27 --rows 4 --cols 6
python -m simura.lights --simulate --lamp mh-250-e40 --duration 900   # warm-up
python -m simura.lights --simulate --lamp led-100-flood --weather --photocell
```

## In the dashboard

The **Lights** component card opens the lighting planner: describe a space and a
task, check a lamp against it, let the catalog recommend one with every
alternative ranked beside it, and solve the illuminance field as a heatmap. Each
lamp's spectrum is drawn in its own colours underneath, because that is where its
efficacy comes from.

The **Validation** tab renders the five bundled standards as selectable cards, and
below them the live-sky check with a place search.

## In the API

Every route is pure compute — no broker, no database:

```bash
curl localhost:8000/api/lights/catalog
curl -X POST localhost:8000/api/lights/recommend \
  -H 'Content-Type: application/json' \
  -d '{"length_m":12,"width_m":9,"task":"office"}'
curl -X POST localhost:8000/api/lights/spectrum \
  -H 'Content-Type: application/json' -d '{"spec":{"lamp_type":"hps-150-e40"}}'
curl localhost:8000/api/lights/validation/standards
curl -X POST localhost:8000/api/lights/validation/live \
  -H 'Content-Type: application/json' -d '{"latitude":51.5,"longitude":-0.13}'
```

`/api/lights/evaluate`, `/recommend` and `/layout` all accept an optional
`weather` object; `/simulate` takes a full weather *provider* spec, because a run
needs conditions that move.

## See also

- [Weather](weather.md) — the reusable provider package this couples to
- [Wires](wires.md) — the other standalone physics library, same shape
- [Validation](validation.md) — the battery side's equivalent
- [`examples/light_planning.py`](https://github.com/msunkara101/Simura/blob/main/examples/light_planning.py),
  [`light_spectrum.py`](https://github.com/msunkara101/Simura/blob/main/examples/light_spectrum.py),
  [`light_weather.py`](https://github.com/msunkara101/Simura/blob/main/examples/light_weather.py)
