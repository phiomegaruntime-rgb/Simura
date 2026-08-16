# Dashboard

A live React + TypeScript + Tailwind SPA, charted with Recharts and built with
Vite. In production nginx serves the static bundle and reverse-proxies `/api` and
`/ws` to the twin core, so the browser sees a single origin (no CORS). The
dashboard consumes only the twin core's public API — the same contract real
hardware feeds.

## Landing: choose a component

The dashboard opens on a **landing page of cards**, one per simulation
component — **Batteries** (the BESS twin), **Wires** (the conductor library) and
**Lights** (the lighting designer).
The header shows no nav here; the cards *are* the nav. Picking a card drills into
that component and the header switches to a sub-nav scoped to just that
component (with a **← Components** link back to the landing). The Simura logo
returns to the landing from anywhere.

- **Batteries** → Fleet, Build, Validation.
- **Wires** → Wiring planner, Validation.
- **Lights** → Lighting planner, Validation.

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
