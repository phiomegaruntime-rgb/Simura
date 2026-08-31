# Simura examples

Runnable, dependency-light demos. Everything here needs only `numpy` (the
simulator and the detection/health libraries are pure) unless noted. From a
source checkout you can run them directly — each script adds `src/` to the path,
so you don't even need to `pip install` first.

| Script | What it shows |
|--------|----------------|
| [`run_basic.py`](run_basic.py) | The physics simulator alone: a healthy pack, or `--fault` to inject an internal short + thermal runaway. Prints a telemetry table. |
| [`run_analytics.py`](run_analytics.py) | The full **intelligence pipeline offline** — simulator → anomaly detection → diagnosis / SoH / RUL / safety — naming the fault before any limit is crossed. Try `--scenario healthy\|short\|cooling\|resistance`. |
| [`custom_profile.py`](custom_profile.py) | Plug in your **own load profile** — a simplified daily grid dispatch (solar charge midday, discharge into demand peaks). |
| [`ocv_chemistry.py`](ocv_chemistry.py) | Swap the **cell chemistry** by replacing the OCV–SoC curve (NMC vs LFP), and why LFP's flat plateau makes voltage-only SoC estimation hard. |
| [`validate_demo.py`](validate_demo.py) | **Validate the model against battery data** — replays a sample's measured current through Simura's cell model and reports voltage error (nominal vs best-fit R0). Runs offline on a bundled *synthetic* sample; `python -m simura.validate --list` shows the real open datasets (NASA, Oxford, …). |
| [`build_system.py`](build_system.py) | **Design your own system** — build a custom LFP pack with an injected fault as a `SystemSpec`, preview it offline (SoC/temp/energy/safety), write the spec to JSON, and print the `python -m simura.publisher --spec …` go-live command. |
| [`weather_demo.py`](weather_demo.py) | **Weather coupling** — drive a pack's ambient temperature, wind cooling and solar heat from a weather source; shows a resting pack tracking a diurnal ambient and a builder preview under synthetic weather. Fully offline; `python -m simura.weather --synthetic` samples the model directly. |
| [`wire_planning.py`](wire_planning.py) | The **Wires** component: check a run against ampacity / voltage drop / temperature, size the smallest adequate gauge, then solve a small multi-node network. |
| [`wire_thermal.py`](wire_thermal.py) | Watch an **undersized conductor overheat** — a 14 AWG copper wire at 25 A climbs past its 90 °C insulation rating, while a correctly-sized 10 AWG run stays cool. |
| [`wire_weather.py`](wire_weather.py) | **Weather-coupled conductor** — the same wire and current settle at very different temperatures on a still hot day vs. a windy or sunny one (the basis of dynamic line rating). |
| [`light_planning.py`](light_planning.py) | The **Lights** component: check a lamp against a task, let the catalog pick one with every alternative ranked beside it, then solve the illuminance field — where an average of 500 lux hides bright pools and dark gaps. |
| [`light_spectrum.py`](light_spectrum.py) | **Where efficacy comes from** — every technology's spectrum side by side, what dimming does to a filament (the light goes orange and the efficacy collapses), and the colour-versus-efficacy trade inside one LED. Nothing is looked up; it all falls out of Planck's law and the CIE observer. |
| [`light_weather.py`](light_weather.py) | **Weather-coupled lighting** — the same ambient makes a fluorescent tube dim and an LED bright, a street light follows the real sunset on a photocell, and a daylit office dims against the sky. `--live` points it at a real place via Open-Meteo. |
| [`field_station.py`](field_station.py) | **Every component on one site** — design an off-grid workshop end to end: the sky over it, the lamps that light it, the cable that feeds them, the voltage drop that comes *back* and changes the light, and the battery that carries the night. The one example where the components compose instead of standing alone. `--live` pulls the real sky from Open-Meteo. |
| [`explain_a_fault.py`](explain_a_fault.py) | **An explanation that is computed, not written** — run the same pack healthy and with an internal short, and watch the fault-heat term appear in the ranking. Nothing tells the explainer a fault is present; the term is there because the fault put heat into the model's heat balance. Also shows the same pack read by three different domains, and one quantity at three depths. |
| [`inherit_a_system.py`](inherit_a_system.py) | **Memory that survives the project** — three engineers, one library file, no services. Ana designs a rack, Ben inherits it for a hotter site and types one sentence, and Cass reads the whole argument back six months later. Nobody types *what* changed: every diff line is computed from the two specs as it is printed. Ends by showing what a change with no reason on file looks like. |
| [`import_a_building.py`](import_a_building.py) | **Somebody else's BIM model, and four simulations standing inside it** — a gbXML file tells the weather where the building is, the lighting planner how big every room is and what it is for, the wiring planner how long the cable actually runs, and a battery rack whether the sun reaches it. Ends with the same rack in two rooms on the same 34 °C day: 22.7 °C in the conditioned office, 39.7 °C in the plant room. Every value the importer had to assume is listed, with the basis it came from. |
| [`connectors/`](connectors/) | Config files for the real-hardware connectors (Modbus / OPC-UA / MQTT). See [connectors/README.md](connectors/README.md). |

```bash
python examples/run_basic.py --fault
python examples/run_analytics.py --scenario short
python examples/custom_profile.py
python examples/ocv_chemistry.py
python examples/validate_demo.py
python examples/build_system.py
python examples/weather_demo.py
python examples/wire_planning.py
python examples/wire_thermal.py
python examples/wire_weather.py
python examples/light_planning.py
python examples/light_spectrum.py
python examples/light_weather.py
python examples/field_station.py
python examples/explain_a_fault.py
python examples/inherit_a_system.py
python examples/import_a_building.py
```

These double as the friendliest **good first areas** for contributors: a new
load profile from a real duty cycle, a measured chemistry table, or a new fault
type all slot straight into these scripts. See the
[contributing guide](../CONTRIBUTING.md).
