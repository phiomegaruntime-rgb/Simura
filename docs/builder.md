# System builder

Everything else in Simura assumes a system already exists. The **builder** lets
you design your own: describe a battery system as a plain, serializable
`SystemSpec`, preview it **offline** to see how it behaves, then stream it live
into the twin with one command.

## The spec

A `SystemSpec` (`simura.builder.spec`) is a recipe — no runtime state:

- **Chemistry** — `NMC` / `LFP` / `LCO` / `NCA` (selects the OCV curve).
- **Cell** — capacity, R0/R1/C1, efficiency, thermal capacity & cooling, limits.
- **Topology** — `series` × `parallel`, plus manufacturing spread and initial SoC.
- **Load profile** — `constant_current`, `constant_power`, `cycle`, or `sinusoidal`.
- **Faults** — any of internal short / resistance growth / cooling fault / thermal
  runaway / sensor drift, each targeted at a cell on a schedule.
- **Sim** — timestep and duration.

```python
from simura.builder import SystemSpec, ProfileSpec, FaultSpec, preview

spec = SystemSpec(
    name="My LFP rack", chemistry="LFP", series=16, parallel=4, initial_soc=0.9,
    profile=ProfileSpec("cycle", {"discharge_a": 40, "charge_a": 30}),
    faults=[FaultSpec("internal_short", series=5, parallel=0, start_s=900,
                      params={"r_short_ohm": 1.0})],
)
r = preview(spec)
print(r.final_soc, r.peak_temp_c, r.temp_limit_exceeded)
```

## Preview offline

`preview(spec)` validates the spec, runs the whole simulation in-process (no MQTT,
no database), and returns a summary — final/min SoC, voltage window, peak
temperature, energy throughput, peak power, whether the temperature limit was
crossed (and when) — plus downsampled sparklines. It answers *"does my system
behave sanely?"* in well under a second, so you can iterate quickly.

Invalid specs raise `SpecError` carrying the full list of problems (bad topology,
a fault targeting a non-existent cell, too many steps, …) — the same list
`validate_spec(spec)` returns.

## CLI

```bash
python -m simura.builder --example > my-system.json   # a starter spec
python -m simura.builder --validate my-system.json     # check it
python -m simura.builder --preview  my-system.json     # run it offline
```

## Go live

A spec becomes a live system by handing it to the publisher — it builds exactly
the same simulator the preview used and streams its telemetry into the twin:

```bash
python -m simura.publisher --spec my-system.json --speed 10 --loop
```

The system then shows up in the fleet, dashboard, anomaly detection, and
diagnosis like any other — analytics don't care whether a system came from a
built-in scenario, a real BMS connector, or your own spec.

## In the dashboard

The **Build** tab is a form over the same spec: set chemistry/topology/profile,
add faults, and click **Preview offline** to see the summary tiles and SoC /
temperature / voltage sparklines. Then **Export spec JSON** and **Copy go-live
command** to stream it in. The form's options (chemistries, profile and fault
types with their parameters, and a default spec) come from
`GET /api/builder/options`; preview and validation are `POST /api/builder/preview`
and `POST /api/builder/validate`.

## Honest limits

- Preview runs the spec at its own `dt`/`duration`; a runaway spec (tiny `dt`,
  huge `duration`) is rejected above a step cap rather than allowed to hang.
- The OCV curves are illustrative per chemistry (see
  [Validation](validation.md)); supply measured tables for quantitative work.
- Going live is a CLI command by design — the API previews and validates but does
  not spawn publisher processes, keeping the twin core free of process management.
