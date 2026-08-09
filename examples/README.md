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
| [`connectors/`](connectors/) | Config files for the real-hardware connectors (Modbus / OPC-UA / MQTT). See [connectors/README.md](connectors/README.md). |

```bash
python examples/run_basic.py --fault
python examples/run_analytics.py --scenario short
python examples/custom_profile.py
python examples/ocv_chemistry.py
python examples/validate_demo.py
python examples/build_system.py
python examples/weather_demo.py
```

These double as the friendliest **good first areas** for contributors: a new
load profile from a real duty cycle, a measured chemistry table, or a new fault
type all slot straight into these scripts. See the
[contributing guide](../CONTRIBUTING.md).
