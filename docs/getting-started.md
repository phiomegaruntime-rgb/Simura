# Getting started

## The simulator alone

The physics simulator needs only NumPy. From a source checkout:

```bash
pip install -e .
python examples/run_basic.py            # healthy pack, daily charge/discharge cycle
python examples/run_basic.py --fault    # inject an internal short + thermal runaway
```

Want to see the intelligence without any infrastructure? The detection and
health libraries are pure too:

```bash
python examples/run_analytics.py --scenario short
```

It prints a timeline and a final assessment that *names the fault* while the pack
is still well below its temperature limit. More demos in the
[examples README](https://github.com/simura/simura/tree/main/examples).

## The full twin

Bring up the broker, TimescaleDB, twin core, analytics, a couple of simulated
assets, a Modbus device + connector, and the dashboard — all together:

```bash
docker compose -f deploy/docker-compose.yml up --build
```

Then open:

- **Dashboard** — <http://localhost:8080> — opens on a fleet overview; click a
  card to drill into a pack's live heatmap, trends, and diagnosis.
- **API docs** — <http://localhost:8000/docs>

```bash
curl localhost:8000/api/fleet                     # whole-fleet rollup
curl localhost:8000/api/systems                   # twin registry
curl localhost:8000/api/systems/bess-01/state     # latest frame
# live stream:  ws://localhost:8000/ws/systems/bess-01
```

The stack runs three systems: `bess-01` (a faulted simulator), `bess-02` (a
healthy simulator), and `bess-modbus-01` (fed from a simulated Modbus BMS).

## Develop the dashboard

Against a running twin core, with hot reload:

```bash
cd dashboard
npm install
npm run dev          # http://localhost:5173
```

## Connect real hardware

Point a connector at a device with a config file — no code. To try it without
hardware, run a simulated Modbus BMS first:

```bash
python -m simura.connect.devsim --protocol modbus --port 5020
python -m simura.connect --config examples/connectors/modbus.yaml
```

See [Hardware connectors](connectors.md) for the full recipe list.

## Optional API key

Auth is off by default. Set `SIMURA_API_KEY` on the twin core and every
`/api/*` route and the WebSocket require it (`/health` stays open for probes):

```bash
curl -H "X-API-Key: $SIMURA_API_KEY" localhost:8000/api/fleet
```

For the full stack, set it once — nginx injects the key so the dashboard keeps
working while direct access to `:8000` requires it:

```bash
SIMURA_API_KEY=your-secret docker compose -f deploy/docker-compose.yml up --build
```

Details in [Twin core & API](twin-api.md#authentication).

## Install extras

Simura's dependencies are grouped so you install only what you need:

```bash
pip install -e ".[dev]"               # simulator + pytest
pip install -e ".[server,connect]"    # twin core + hardware connectors
pip install -e ".[docs]"              # build this docs site
```
