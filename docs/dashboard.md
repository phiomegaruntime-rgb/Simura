# Dashboard

A live React + TypeScript + Tailwind SPA, charted with Recharts and built with
Vite. In production nginx serves the static bundle and reverse-proxies `/api` and
`/ws` to the twin core, so the browser sees a single origin (no CORS). The
dashboard consumes only the twin core's public API — the same contract real
hardware feeds.

## Landing: choose a component

The dashboard opens on a **landing page of cards**, one per simulation
component — **Batteries** (the BESS twin), **Wires** (the conductor library) and
**Lights** (the lighting designer) — plus three that are not components:
**Building**, the floor plan all three of them stand in, **Learn**, the reading
room for all three, and **Library**, the record of every system built with them.
The header shows no nav here; the cards *are* the nav. Picking a card drills into
that component and the header switches to a sub-nav scoped to just that
component (with a **← Components** link back to the landing). The Simura logo
returns to the landing from anywhere.

- **Batteries** → Fleet, Build, Validation.
- **Wires** → Wiring planner, Validation.
- **Lights** → Lighting planner, Validation.
- **Building** → Floor plan.
- **Learn** → Model cards.
- **Library** → Saved systems.

Optional modules installed under `dashboard/src/modules/` add cards of their own
here; see [Contributing](contributing.md) for the contract.

## Building (Component 20)

Import an IFC, gbXML or DXF model and the view draws the floor plan — and, beside
it, everything the importer could not read. See [The building](space.md).

**That adjacency is the whole information architecture of the screen.** A plan on
its own looks authoritative: clean polygons, round numbers. The one thing a
reader cannot see in it is which of those numbers came out of the file and which
the importer supplied. So the fidelity panel is not behind a tab or a "details"
disclosure — it sits next to the drawing, with each assumed value and the basis
it came from, and rooms resting on an assumption are **hatched in the drawing
itself**.

Below the plan sit the three couplings:

- **Where on Earth this is.** A georeferenced model hands back the
  `simura.weather` source its own coordinates imply, ready to paste into a
  system's spec. Nobody types a latitude.
- **Click a room** for its use, its real extents, its ceiling height, and the
  ambient a system standing in it would be in — with the sentence that explains
  that ambient. A room that is not a rectangle says that the lumen method is
  being applied to a best-fit rectangle, and by how much the two differ.
- **Click two points** to trace a cable between them through the building's own
  doorways. The run shows its legs, because a computed length is only worth
  having if somebody can check where the metres went, and it is derated for the
  hottest room it passes through.
- **Design every room** runs the whole building through the lighting planner and
  totals the installed watts. Rooms that cannot honestly be designed as read are
  listed with the reason rather than quietly omitted.

The view is stateless: the plan lives in the browser and is posted back to each
pure-compute route, so nothing about a building is stored on the server.

## Library (Component 17)

The **Library** section lists every saved system, each row carrying a one-line
diff from whatever it was forked from. Opening one shows what changed with the
reason underneath — grouped, because one reason usually covers several fields —
and where there is no reason, a highlighted line saying so plus a form that binds
a new one to exactly the fields you tick.

The rest of the panel is the context a spec file cannot carry: the decisions and
what they rejected, the notes and gotchas people left, everything inherited from
further up the chain, the lineage itself, and what grew out of this system since.
Actions run it as a live twin, promote it to a template, mark it checked, or open
it in the builder.

**Open in builder** is where the two halves meet: the builder then shows a live,
server-computed diff against the entry as you type and offers two saves —
*as v n+1* (this design's next version) or *as a fork* (a second design). Both
require a reason; neither asks you to describe the change. See
[the system library](library.md).

## Fleet overview

The Batteries component opens on a **fleet overview**: a summary strip (systems,
live count, counts by status, safety alarms) above a grid of system cards, ordered
worst-first. Each card shows the system's overall status (icon + label + color),
a one-line reason, and headline metrics (SoC, max temp, anomaly σ, SoH) with a
live/offline indicator. Clicking a card drills into that system's detail view.

### Lifecycle controls (Component 10)

Each card carries a **source badge** — `SIM` (twin-core-run) or `LIVE` (external
feed) — and lifecycle actions:

- **Simulations**: Start / Pause / Resume (contextual on run state) and Delete.
- **Real-time feeds**: Delete only ("external feed · view only" — you can't pause
  a real battery or a foreign process).

**Delete** is a full purge (registry + all history) behind an inline confirm.
**+ New system** opens a dialog to either register a real-time id or jump to the
**Build** tab to design a simulation; the Build tab's **▶ Start in fleet** button
creates and starts a simulation the twin core runs — see
[System builder](builder.md) and [Twin core & API](twin-api.md).

## Per-system detail

The detail view is the single-pack cockpit:

- **Health banner** — overall status and the reason (safety alarm → diagnosis →
  early warning → nominal).
- **Explanation panel** — *above* the numbers, deliberately. A newcomer arriving
  at a live pack should meet a sentence they can read before they meet a DCIR
  figure. It says what the pack is doing and why, decomposed from the model's own
  equations, in whichever domain's vocabulary you pick and at whichever of three
  depths (*overview / working / physics*). Depth adds and never contradicts — the
  headline is identical at all three, so an expert clicking down loses nothing and
  a newcomer staying at the top is not being told a different story. A badge says
  whether the answer was read from the running model (exact) or inferred from
  telemetry. See [Getting familiar](explain.md).
- **Stat tiles** — voltage, power, SoC, max temp, anomaly score.
- **Cell heatmap** — per-cell temperature / voltage / SoC, with an absolute
  thermal colorbar so an overheating cell visibly stands out, plus anomaly
  badges.
- **Diagnosis & prognosis card** — fault, confidence, rationale, SoH,
  time-to-critical.
- **Anomaly panel** and a **fault timeline** (client-derived from the stream).
- **Trend charts** — SoC, max temperature, and anomaly score, seeded from REST
  history and updated over the WebSocket.

A "← Fleet" control returns to the overview; a per-system selector switches packs.

## Wires (Component 12)

The Wires component exposes the conductor library over pure-compute endpoints (no
MQTT, no DB), across two sub-views:

- **Wiring planner** — over `simura.wires`: describe a run and a load and *check*
  it (ampacity / voltage drop / temperature, with the failing constraints listed)
  or *recommend* the smallest adequate gauge, plus the wire catalog as a table.
- **Validation** — check the conductor model against published DC-resistance
  standards (annealed copper at 20 °C / 75 °C, hard-drawn aluminium), or against
  your own measured-resistance CSV. Simura replays each gauge through the same
  `Wire` the twin uses and reports the per-gauge percent error (RMSE / MAE / max /
  mean-bias) with a published-vs-model resistance chart. The parallel to the
  battery **Validation** view.

See [Wires](wires.md).

## Lights (Component 14)

The Lights component exposes the lighting library over pure-compute endpoints (no
broker, no database), in two views.

- **Lighting planner** — over `simura.lights`: describe a space and a task, then
  *check* a chosen lamp against illuminance, colour rendering and installed power,
  let the catalog *recommend* one with every alternative ranked beside it, or
  *solve the field* to see where the light actually lands as a heatmap. Checks can
  run at the end of a maintenance cycle rather than on day one, and an optional
  weather panel moves the answer — in opposite directions depending on the
  technology.
- Under the planner, the selected lamp's **spectrum** is drawn in its own colours,
  alongside its efficacy of radiation and the gap between predicted and published
  flux. This is where a lamp's efficacy comes from, and why two lamps of the same
  wattage differ.
- **Validation** — the five bundled photometric standards as selectable cards,
  reporting absolute *and* relative error; a **live sky** panel that validates the
  daylight model against measured irradiance for a place you search for; and a CSV
  upload for your own measurements.

See [Lights](lights.md).

## Learn (Component 16)

The reading room. Every model in the project as a **model card** — what it is, why
it matters, its equation, its assumptions, its settings, and, given the same
prominence as the rest, **what it cannot tell you**. Each card can be re-read in
another field's words ("reads like, if your field is…"), which is the mission
stated as a UI control.

Beside it, the **glossary**: every term the dashboard shows that a newcomer would
not know, in one sentence each. Those same terms are underlined wherever they turn
up in explanation prose elsewhere, with the definition on hover — a link to a
glossary is a page nobody visits mid-sentence.

The wiring planner and the lighting planner carry the same explanation panel the
per-system view does, decomposing the check that is on screen.

See [Getting familiar](explain.md).

## Design system

The dashboard follows a data-viz design system:

- **Status color is never carried alone** — a reserved status color is always
  paired with an icon and a label. The backend fleet rollup mirrors the same
  thresholds (`simura.fleet.levels` ↔ `dashboard/src/lib/status.ts`) so the
  card and the detail view never disagree.
- **Absolute thermal scale** for the heatmap so red means genuinely hot;
  **relative ramps** for voltage/SoC so imbalance shows.
- **Single-series trend charts** — never a dual axis.

## Running it

```bash
cd dashboard
npm install
npm run dev          # http://localhost:5173, proxied to a running twin core
npm run build        # production bundle (dist/)
npx tsc --noEmit     # type-check
```

In the `docker compose` stack the dashboard is the `dashboard` service on port
8080.
