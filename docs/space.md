# The building (BIM import)

Every simulation Simura runs stands somewhere. Until now it did not know where.
A rack had an ambient temperature somebody typed, a cable had a length somebody
estimated, a lighting design had a room somebody measured off a drawing, and a
weather source had coordinates somebody looked up. Four numbers, four
opportunities to be wrong, and no way for anyone downstream to tell which had
been measured and which had been remembered.

`simura.space` imports the file that already has all four in it. Give it an IFC
model, a gbXML energy model, or a DXF floor plan, and it produces one small
document — a **floor plan** — that four different simulations then read.

It is a standalone package with no new dependencies: IFC, gbXML and DXF are all
parsed in pure Python, for the same reason [every texture in the 3D
sandbox](dashboard.md) is drawn in code rather than shipped as a sprite. This is
a repository people clone in order to read, and a dependency you cannot open is
a part of the system nobody can inspect.

```bash
python -m simura.space --import block-a.ifc --fidelity
python -m simura.space --import block-a.ifc --light
python -m simura.space --import block-a.ifc --route 3,3 21,3
python examples/import_a_building.py
```

## The design decision everything follows from

**An import declares what it could not read.**

Every importer ever written meets geometry it does not understand, units it has
to guess at, and rooms with no stated height. The ones that raise are useless — a
40 MB model with one unsupported solid in it is still a building somebody wants
to light. So every importer in practice *fills in*: it picks 2.7 m, it assumes
millimetres, it skips the entity and moves on.

That is the right behaviour. Doing it **silently** is not, because of what sits
downstream. A room whose ceiling height was assumed produces a room index, which
produces a utilisation factor, which produces a lux figure a person then designs
against — and nothing anywhere on that chain says the first number was a guess.

The failure is not the guess. The failure is that the guess became
indistinguishable from a measurement one function call after it was made.

So an imported plan carries a **fidelity record**, and it is not optional
decoration:

```
Read 10 of 11 entities from block-a.xml; 4 value(s) assumed; 1 skipped.

  [derived] space:sp-office.height_m = 2.8
            because: stated volume / floor area
  [derived] space:sp-plant.height_m = 2.8
            because: z-extent of the space's own wall surfaces
  [default] wall:srf-party.thickness_m = 0.2
            because: gbXML surfaces are planes; a wall's thickness lives in
                     its Construction, which this importer does not read

  1x Surface[Roof] — not a wall; a 2D layout has no place for roofs
```

Note that the two rooms got their height by different routes. One was derived
from a stated volume and one was measured off the room's own wall surfaces —
different qualities of answer, and the record says which is which rather than
presenting both as 2.8 m.

This is the same commitment the rest of Phase 2 makes in its own vocabulary:
[an explanation is attributed, never asserted](explain.md); [what changed is
computed, and only why is typed](library.md). Here it is applied to the one
place a digital twin meets somebody else's file.

### The consequence: a guess travels with the number built on it

Because inferred fields are named per room, the couplings can carry them
through. A lighting design for a room whose ceiling height was assumed says so,
in the design report, next to the lux figure:

```
Open Plan Office 0.01   500 lx  17 x 15 W LED GLS   10.2 W/m²
     ! the ceiling height was assumed rather than read from the model, and
       mounting height is what the room index is built on
```

## What a floor plan is

One plain JSON document. No live objects, no parser handles, no file references
that have to still be valid — which is what lets it travel into a `SystemSpec`,
into a [library entry](library.md), into `localStorage` in the browser, and back
out unchanged.

| Part | What it holds |
|---|---|
| `georeference` | Latitude, longitude, elevation, and **true north** |
| `levels[]` | Storeys, by elevation, with their heights |
| `spaces[]` | Rooms: a polygon in metres, a ceiling height, and what the room is *for* |
| `walls[]` | An axis, a thickness, a height, inside or outside |
| `openings[]` | Doors and windows, positioned along their wall |
| `fidelity` | Everything above that was assumed rather than read |

**Metres, always.** Building files arrive in millimetres, feet, inches and
occasionally survey feet, and the unit is the single most common way a BIM
import goes wrong — silently, by a factor of a thousand, producing a
plausible-looking plan of a building the size of a desk. Conversion happens in
the importer, everything below that line is metres, and the original unit is
recorded so a suspicious number can be traced.

The plan's `id` is a **content hash**, for the same reason a library entry's is:
two imports of the same bytes are the same plan, and an edited model is a new
plan rather than a mutation of the old one. What somebody designed against
remains fetchable after the model moved on. The hash deliberately excludes the
fidelity record — two importers that produced the same building produced the
same plan, even if one had to assume more to get there.

### A room is what it is for

Geometry alone cannot be simulated. A 24 m² rectangle is a cell office, a
two-bed ward, a substation or a store cupboard, and the four want wildly
different amounts of light and different ambient assumptions. So every room is
classified onto a vocabulary — and that vocabulary is *exactly* the one
`simura.lights` already speaks, so an imported room arrives with an illuminance
target already attached instead of needing one typed in.

The classifier reads the most structured source first — gbXML's closed
`spaceType` enumeration, then IFC's `PredefinedType`, then the room's own name —
and it returns its **basis**, which goes into the fidelity record:

```
office     because gbXML spaceType 'OpenOffice'
storage    because LongName 'Plant Room 3' contains 'plant'
unknown    because no space type, and no keyword in the name
```

It **refuses rather than guesses**. A room it cannot classify is `unknown`, and
the lighting coupling declines to set a target for it instead of defaulting it
to an office. Defaulting is how a plant room ends up designed to 500 lux;
refusing is how somebody notices.

Matching is on **whole words**, so `lab` does not match "Elaborate Suite" and
`plant` does not match "Planting Terrace".

## What the building tells each component

### Weather — where on Earth this is

The strongest join, and the least obvious before you see it. A model that
carries `IfcSite` coordinates already knows the latitude and longitude
[`simura.weather`](weather.md) needs, so importing a building *configures the
sky over it* with nothing typed in:

```python
from simura.space import GbxmlProvider, weather_spec

plan = GbxmlProvider("block-a.xml").plan()
weather_spec(plan)
# {'type': 'open_meteo', 'latitude': 51.4545, 'longitude': -2.5879, ...}
```

The plan also carries **true north**, which is not cosmetic: project north is
almost never true north, and the difference decides which facades take morning
sun — which drives both solar gain on the conductors and the daylight a
photocell sees.

A model with no coordinates returns `None`. That is a fact about the file, not a
failure, and the caller keeps whatever weather it had rather than being handed
`0, 0` in the Gulf of Guinea.

### Lights — how big each room is, and what it is for

Every space becomes a lighting-design problem with its real extents, its ceiling
height, its reflectances and the task its occupancy implies. The result is
literally the argument list [the lighting planner](lights.md) already takes:

```python
from simura.lights.planning import recommend_lamp
from simura.space import lighting_targets

for target in lighting_targets(plan):
    result = recommend_lamp(**target.kwargs())
```

That identity is the point, and it is why the occupancy vocabulary was made to
match the lighting task vocabulary rather than translated between them.

**Rooms that are not rectangles.** The lumen method is written for a rectangular
room, because the room index it computes is a rectangle's. Real rooms are
L-shaped and chamfered. Rather than refuse them, a room is handed over as its
**minimum-area enclosing rectangle** — and the target says that is what happened:

```
! the room is not rectangular, so the lumen method is being applied to an
  8.0 x 4.0 m best-fit rectangle (32.0 m² against the room's actual 24.0 m²)
```

For the illuminance *field*, there is no need to approximate at all.
`Layout(outline=...)` solves over the room's real polygon and masks every grid
point that falls outside it, which changes the answer substantially in exactly
the rooms where the rectangle is worst:

| Same three fittings, same places | Area | Average | U₀ |
|---|---|---|---|
| Solved as its bounding rectangle | 56.0 m² | 54 lux | 0.66 |
| Solved over the real L-shape | 44.0 m² | 68 lux | 0.80 |

A fifth of the "room" the rectangle measured was never floor. A point in the
notch comes back as `null` rather than as zero lux — it is not dark floor, it is
not floor — so a heatmap leaves it blank and the statistics never see it.

### Wires — how long the cable actually is

Voltage drop, ohmic loss and conductor heating all scale with length, so the
whole [wiring answer](wires.md) rests on a number that was previously a guess.
With a floor plan it can be computed:

```
drop          2.60 m   rise from the equipment to the tray at 2.6 m
horizontal    3.00 m   through Open Plan Office 0.01
horizontal    6.07 m   through Plant Room 0.02
drop          2.60 m   drop from the tray to the equipment
             --------
total        14.99 m   (9.1 horizontal + 5.2 vertical + 0.7 slack)
```

The path is the shortest route through a graph of **rooms and the openings that
join them** — so a cable goes through doors rather than through walls. This is
deliberately not a visibility graph or a maze solve over a raster of the plan:
both would produce a shorter number and both would be wrong the same way, since
an installed cable does not cut diagonally across an open-plan office.

A run reports its **legs**, which is what makes the total checkable. A computed
length is worth having precisely because somebody can see where the metres went.

It also reports **which rooms it crossed**, and that matters more than it
sounds. Ampacity derates against ambient, and a conductor is rated by its
hottest metre — so a run that leaves a 21 °C office and crosses a 34 °C plant
room is rated for the plant room, not for the office it started in.

When two points cannot be connected through the building's own openings — a plan
with no doors in it, which happens honestly — the straight-line distance comes
back with the reason attached, rather than an exception or a silently confident
number.

### Batteries — whether the weather reaches the equipment

The subtle one. A rack in a plant room and the same rack in a yard are the same
design in two different environments, and until now that difference had to be
typed in as an ambient somebody guessed.

A `SystemSpec` gains a `space` field, deliberately the same two-field shape as
`weather`, because it answers the neighbouring question:

```json
{
  "weather": {"type": "open_meteo", "params": {"latitude": 51.45, "longitude": -2.59}},
  "space":   {"type": "gbxml", "params": {"path": "block-a.xml"}, "space_id": "sp-plant"}
}
```

Weather says *what the sky is doing*; the room says *whether the sky reaches the
equipment at all*. And standing indoors is not modelled as a modifier on the
weather — it is the statement that the weather does not reach this pack. The
weather source is **dropped rather than damped**, which is both the truthful
model and the one that needs no new coefficient nobody could justify.

Same rack, same 34 °C day, two rooms:

| Room | Ambient | Sun | Hottest cell after 30 min |
|---|---|---|---|
| Open Plan Office (conditioned) | 21.0 °C | excluded | 22.7 °C |
| Plant Room (unconditioned) | 34.0 °C | reaching the cabinet | 39.7 °C |

The difference is not a number somebody typed. It is what the building said
about each room.

!!! note "A room the model says nothing about is treated as outdoor"
    Defaulting an unclassified room to indoors would be the comfortable choice
    and the wrong one: it hides the weather coupling behind a guess, and a
    battery that quietly stops responding to a heatwave because a BIM field was
    blank is a worse outcome than one that responds to weather it should have
    been shielded from. The unshielded answer is at least visibly wrong — and
    the plan says which case it is.

## The formats

| Type | What it is | Read from it |
|---|---|---|
| `ifc` | IFC STEP (`.ifc`), pure Python | Storeys, spaces, walls, doors, site coordinates, true north, units |
| `ifc_full` | The same, through `ifcopenshell` | Any geometry the kernel can resolve — see below |
| `gbxml` | gbXML energy model | Spaces with types and conditioning, surfaces, openings, location |
| `dxf` | ASCII DXF drawing | Rooms from closed polylines on a room layer, walls from a wall layer |
| `json` | A plan imported once and saved | Everything, instantly — the fast path |
| `rect` | A generated example building | Nothing; it is for tests and for trying the pipeline |

### IFC, without a geometry kernel

IFC is the real interoperability format and it is enormous; a full reader is a
geometry kernel, a schema and a decade. The importer here reads the subset a 2D
layout actually needs — `IfcSpace`, `IfcWall`, `IfcBuildingStorey`, `IfcSite`,
the unit assignment, the placement chain, and `IfcExtrudedAreaSolid` with its
profile.

That last one is why the subset is the right subset: a profile extruded
vertically is how essentially every wall, slab and space in a practical model is
authored. Everything else — B-reps, tessellations, CSG, swept discs — is counted
by type, skipped, and named in the fidelity record.

The **placement chain** is the piece most naive readers get wrong. Every product
in IFC is placed relative to its parent, so a wall's coordinates mean nothing
until the chain above it has been composed. Skipping that gives a building whose
every storey is stacked on the origin — which looks plausible enough on the
ground floor to ship.

Placements are read as a **full axis triad**, not just a rotation about Z. A wall
or a storey only ever turns about Z, but an opening's profile stands up in the
wall's elevation plane, which tips its local Z away from vertical — and a Z-only
rotation cannot express that at all.

**Openings are positioned from their own solid**, which is the footprint a viewer
subtracts from the wall: all eight corners transformed to world coordinates and
projected onto the wall axis, giving the hole's span and its midpoint. The
obvious alternative — project the placement origin and take the width off the
door — is wrong twice, because an IFC profile is positioned *within* its
placement (so the origin is often a corner of the hole) and because a door's
`OverallWidth` is the leaf rather than the structural opening around it. Together
those put a door half its own width into the wall beside it.

When the subset is not enough, `pip install "simura[bim]"` makes the `ifc_full`
provider available: the same job through `ifcopenshell`, behind the same
interface, producing the same floor plan. It is optional in exactly the way
SciPy is optional for reading `.mat` [validation datasets](validation.md).

### DXF: the drawing everybody actually has

DXF has no idea what a building is. It is lines on layers — no `Space`, no room
name, no storey, no wall thickness, no unit half the time. So everything the DXF
importer produces is inferred from **convention** rather than read from
structure, and it says so on every value.

The convention it reads is the one every office in the world follows, and which
the AIA/ISO 13567 layer schemes make formal:

- **Walls** from lines and polylines on a layer with a wall keyword in its name.
- **Rooms** from *closed* polylines on a room/area layer — somebody has already
  drawn the room boundary, and that is what makes a DXF simulable at all.
- **Room names** from text whose insertion point falls *inside* one of those
  loops, which is where a room label is by definition.

A drawing whose layers are called `0` and `Layer1` is not hopeless: pass
`wall_layers` / `room_layers` and name that office's own convention.

`$INSUNITS` is very often `0` — unitless — which leaves a pile of numbers and no
scale. The guess is a building-shaped prior (buildings are tens of metres
across, so a drawing spanning 45,000 units is millimetres) and it is recorded as
an inference with its reasoning, not buried.

## The API

Every route is **pure compute**, like `/api/wires/*` and `/api/lights/*`: no
broker, no database, nothing stored server-side. The client holds the plan and
posts it back. That is deliberate rather than an omission — a floor plan is an
artifact somebody keeps, not a session on a server.

| Route | What it does |
|---|---|
| `GET /api/space/options` | The formats, their parameters, the occupancy vocabulary |
| `POST /api/space/import` | Upload a building file; get a plan and its fidelity record |
| `POST /api/space/summary` | The rollup: rooms, area, where it is, what was assumed |
| `POST /api/space/lighting` | Every room as a lighting problem, optionally designed and totalled |
| `POST /api/space/layout` | An illuminance field over one room's **real outline** |
| `POST /api/space/route` | A cable run through the building, optionally priced as a conductor |
| `POST /api/space/ambient` | What the environment is in one room, and why |
| `POST /api/space/at` | Which room a point falls in |
| `POST /api/space/weather` | The weather source the model's coordinates imply |
| `POST /api/space/grid` | Task-area sample points inside one room |

The only route that cannot be pure compute is the import itself, because it
needs the file. After that, the server is out of the loop.

## In the dashboard, and in the world

The **Building** section imports a model, draws the plan, and shows the fidelity
record beside it — the plan and what could not be read arrive together, because
showing one without the other is showing half the answer. Clicking a room gives
its lighting design; clicking two points traces a cable between them.

The [3D sandbox](dashboard.md) extrudes the *same* plan into walls you can walk
between, and names the room you are standing in as you walk into it. A model
loads with every storey showing, each one able to be hidden on its own, and it
puts you inside the building, because exterior walls are solid and a building you
cannot enter is not one you can inspect. It is not a mesh
import: the world builds from the identical floor-plan document the 2D views
solve against, so the building you walk through and the building the lighting
planner designed for cannot disagree.

## What this does not do

- It does not validate that a model matches the building as built. A plan is as
  right as the file is.
- It reads a **subset** of IFC and names by type whatever it skipped. A model
  whose rooms are B-reps is a model the native reader will decline to guess
  about — install `simura[bim]` for those.
- It is a **2D layout**. No ceiling voids, no structure, no services, and no
  risers other than where two storeys' rooms overlap in plan.
- Wall thickness, ceiling height and room purpose are frequently absent from a
  model. They are then inferred, every inference is recorded with its basis, and
  none of them is a measurement.
- Routing is room-to-room through openings. It does not route around furniture,
  structure, or other services.
