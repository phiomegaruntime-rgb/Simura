# Analytics

Simura's analytics turn telemetry into *insight*: not just that something is
wrong, but **what**, **how healthy**, **how long**, and **how dangerous**. Both
engines are pure libraries, unit-tested against the simulator's fault scenarios,
and run together in the `analytics` service on the same frame.

Run the whole pipeline offline with
[`examples/run_analytics.py`](https://github.com/simura/simura/blob/main/examples/run_analytics.py).

## Anomaly detection (`simura.detect`)

Every cell in a pack sees the same load, so its siblings are a free, always-valid
baseline. For each metric the engine takes the pack **median** as consensus and
the **MAD** as robust spread (a single bad cell can't skew either), scores each
cell by a robust z in the *bad* direction (hot / drained / off-voltage), and
smooths with an EWMA so only *sustained* deviation flags.

- No training data, no per-asset tuning.
- Per-metric deviation **floors** are the main false-positive defense: they set
  the scale of a meaningful deviation, calibrated in `AnomalyConfig`.
- The internal-short cell trips "critical" while still ~9 °C below its
  temperature limit; a healthy pack stays under score 1.2.

The detector publishes an `AnomalyReport` (per-cell scores + the worst offender)
on `simura/anomaly/{id}`.

## Diagnosis, SoH, RUL & safety (`simura.health`)

The assessment engine consumes the anomaly z-scores and health features aligned
to the same frame:

| Piece | What it does |
|-------|--------------|
| **Diagnosis** | Fault-fingerprint matching over the anomaly z-scores + health features, checked in **priority (safety) order**, with a confidence and a plain-English rationale. |
| **State of health** | Online DCIR estimation, `(OCV(SoC) − V) / I` vs nominal — so resistance growth shows up and a short/sensor fault correctly does not. |
| **RUL** | Acute time-to-critical from the smoothed heating rate. |
| **Safety state** | `nominal` / `warning` / `alarm`, with a thermal-runaway alarm. |

### Why fingerprints, not a black box

With no labeled field data — only what the simulator produces — an operator needs
to trust the call. So each fault is a legible rule over features that already mean
something:

- *hot AND draining* → internal short
- *hot WITHOUT drain* → cooling loss
- *DCIR above peers* → resistance growth
- *one signal off with no physical corroboration* → sensor fault
- *fast, accelerating heat* → thermal runaway

The short-vs-cooling discriminator is the mere *presence* of extra
self-discharge (small in a cycling pack, but real and one-directional), gated by
"hot" so a healthy cell is never called a short.

!!! note "Honest degradation"
    A coarser sensor set changes the answer. A Modbus system reporting only
    per-module temperature and pack SoC diagnoses the same internal short as a
    *cooling fault* — the diagnosis reflects what can and cannot be observed.

## On the wire

Anomaly and assessment frames are distinct envelopes
(`{system_id, timestamp, anomaly|assessment}`) sharing the per-system WebSocket;
clients tell them apart by shape. Only compact **summaries** are persisted to
TimescaleDB (score/flagged/worst cell; SoH/fault/confidence/safety/time-to-crit);
the full per-cell reports live in the live cache and are served from
`/anomaly` and `/assessment`. See [Twin core & API](twin-api.md).
