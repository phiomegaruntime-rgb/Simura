# Dashboard

A live React + TypeScript + Tailwind SPA, charted with Recharts and built with
Vite. In production nginx serves the static bundle and reverse-proxies `/api` and
`/ws` to the twin core, so the browser sees a single origin (no CORS). The
dashboard consumes only the twin core's public API — the same contract real
hardware feeds.

## Fleet overview

The dashboard opens on a **fleet overview**: a summary strip (systems, live
count, counts by status, safety alarms) above a grid of system cards, ordered
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

## Design system

The dashboard follows a data-viz design system:

- **Status color is never carried alone** — a reserved status color is always
  paired with an icon and a label. The backend fleet rollup mirrors the same
  thresholds (`celltwin.fleet.levels` ↔ `dashboard/src/lib/status.ts`) so the
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
