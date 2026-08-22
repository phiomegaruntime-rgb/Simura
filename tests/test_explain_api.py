"""Tests for the /api/explain/* routes.

Most of `simura.explain` is a library and is tested as one in `test_explain`.
What is left over — and what this file is for — is the wiring: that the routes
serialize to plain JSON, that a bad lens or an unknown card is a 4xx rather than
a 500, and that the live-twin route takes the *exact* path when the twin core is
running the model and the *inferred* path when it is not, and says which.

The reference and pure-compute routes need no database and no broker, so the
router is mounted on a bare app. The live-twin route needs three things off
``app.state``, and they are stubbed here rather than stood up: the point of the
test is the branch the route takes, not the store.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from simura.builder import FaultSpec, ProfileSpec, SystemSpec, build_simulator
from simura.twincore.api import router


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c


# -- reference routes ------------------------------------------------------


def test_cards_list_and_filter(client):
    every = client.get("/api/explain/cards").json()
    assert len(every) > 10
    assert {c["component"] for c in every} <= {"batteries", "wires", "lights", "twin"}

    lights = client.get("/api/explain/cards", params={"component": "lights"}).json()
    assert lights and all(c["component"] == "lights" for c in lights)
    assert all(c["limits"] for c in lights)


def test_unknown_component_is_a_400_not_a_500(client):
    assert client.get("/api/explain/cards", params={"component": "boats"}).status_code == 400


def test_one_card_by_id_and_a_404_for_a_missing_one(client):
    card = client.get("/api/explain/cards/battery.thermal").json()
    assert card["title"]
    assert card["equation"]
    assert any(p["key"] == "cooling_conductance_w_per_k" for p in
               client.get("/api/explain/cards/battery.cell").json()["params"])
    assert client.get("/api/explain/cards/battery.nope").status_code == 404


def test_glossary_whole_and_by_alias(client):
    everything = client.get("/api/explain/glossary").json()
    assert len(everything) > 20
    one = client.get("/api/explain/glossary", params={"term": "SoC"}).json()
    assert one["term"] == "state of charge"
    assert client.get("/api/explain/glossary", params={"term": "zzz"}).status_code == 404


def test_lenses_serves_both_knobs_in_one_call(client):
    body = client.get("/api/explain/lenses").json()
    assert [lv["key"] for lv in body["levels"]] == ["overview", "working", "physics"]
    assert body["default_domain"] in {d["key"] for d in body["domains"]}
    assert any(d["home_component"] == "lights" for d in body["domains"])


def test_coverage_is_exposed_and_complete(client):
    body = client.get("/api/explain/coverage").json()
    assert body["complete"] is True
    assert body["missing"] == [] and body["orphaned"] == []


# -- pure-compute explaining routes ---------------------------------------


@pytest.fixture(scope="module")
def frame_and_spec():
    spec = SystemSpec(
        series=4, parallel=2, duration_s=600, dt_s=1.0,
        profile=ProfileSpec("constant_current", {"amps": 16.0}),
        faults=[FaultSpec("internal_short", 1, 0, 200.0, {"r_short_ohm": 1.0})],
    )
    sim = build_simulator(spec)
    frames = list(sim.run())
    return frames[-1].to_dict(), spec.to_dict()


def test_explain_battery_frame(client, frame_and_spec):
    frame, spec = frame_and_spec
    body = client.post(
        "/api/explain/battery",
        json={"frame": frame, "spec": spec, "domain": "operations", "level": "working"},
    ).json()
    assert body["domain"] == "operations" and body["level"] == "working"
    keys = {e["key"] for e in body["explanations"]}
    assert {"cell.heat_balance", "cell.voltage_sag", "pack.imbalance"} <= keys
    for e in body["explanations"]:
        assert e["headline"].endswith(".")
        assert e["causes"]
        # A frame-derived answer is inferred, and says so at every depth.
        assert e["caveat"]


def test_explain_battery_rejects_a_frame_with_no_cells(client):
    assert client.post("/api/explain/battery", json={"frame": {}}).status_code == 400


def test_explain_battery_rejects_an_unknown_lens(client, frame_and_spec):
    frame, spec = frame_and_spec
    r = client.post("/api/explain/battery",
                    json={"frame": frame, "spec": spec, "domain": "astrology"})
    assert r.status_code == 400
    r = client.post("/api/explain/battery",
                    json={"frame": frame, "spec": spec, "level": "everything"})
    assert r.status_code == 400


def test_explain_wires_matches_the_wire_route_it_explains(client):
    payload = {"spec": {"awg": 12, "length_m": 40.0, "ambient_temp_c": 35.0},
               "current_a": 18.0, "system_voltage_v": 12.0, "round_trip": True,
               "domain": "electrical", "level": "physics"}
    body = client.post("/api/explain/wires", json=payload).json()
    keys = {a["key"] for a in body["attributions"]}
    assert {"wire.voltage_drop", "wire.ampacity_margin", "wire.heat_balance",
            "wire.resistance"} == keys

    # The number the explanation is built on is the number the planner reports.
    check = client.post("/api/wires/evaluate", json={
        "spec": payload["spec"], "current_a": 18.0,
        "system_voltage_v": 12.0, "round_trip": True,
    }).json()
    drop = next(a for a in body["attributions"] if a["key"] == "wire.voltage_drop")
    assert drop["total"] == pytest.approx(check["voltage_drop_v"], rel=1e-3)


def test_explain_wires_rejects_an_unsizeable_conductor(client):
    r = client.post("/api/explain/wires", json={"spec": {"length_m": 10.0}, "current_a": 5.0})
    assert r.status_code == 400


def test_explain_lights_covers_efficacy_and_illuminance(client):
    body = client.post("/api/explain/lights", json={
        "spec": {"lamp_type": "led-9-e27"}, "n_luminaires": 12,
        "length_m": 10, "width_m": 8, "mounting_height_m": 2.5,
        "task": "office", "maintenance_hours": 20000, "dirt_frac": 0.15,
        "domain": "lighting", "level": "working",
    }).json()
    keys = {a["key"] for a in body["attributions"]}
    assert {"room.illuminance", "lamp.efficacy"} == keys
    eff = next(a for a in body["attributions"] if a["key"] == "lamp.efficacy")
    assert 0 < eff["total"] <= 683.0
    # The lighting lens leads with the room, not the lamp.
    assert body["explanations"][0]["key"] == "room.illuminance"


def test_explain_lights_rejects_an_unknown_lamp(client):
    r = client.post("/api/explain/lights", json={"spec": {"lamp_type": "no-such-lamp"}})
    assert r.status_code == 400


def test_every_route_returns_plain_json(client, frame_and_spec):
    import json

    frame, spec = frame_and_spec
    for r in (
        client.get("/api/explain/cards"),
        client.get("/api/explain/glossary"),
        client.get("/api/explain/lenses"),
        client.get("/api/explain/coverage"),
        client.post("/api/explain/battery", json={"frame": frame, "spec": spec}),
    ):
        assert r.status_code == 200
        json.dumps(r.json())


# -- the live-twin route ---------------------------------------------------


class _FakeSimManager:
    def __init__(self, simulator=None, spec=None):
        self._sim, self._spec = simulator, spec

    def simulator(self, system_id):
        return self._sim

    def spec(self, system_id):
        return self._spec


class _FakeLive:
    def __init__(self, envelopes=None):
        self._e = envelopes or {}

    def get(self, system_id):
        return self._e.get(system_id)


class _FakeStore:
    def __init__(self, systems=None):
        self._s = systems or {}

    async def get_system(self, system_id):
        return self._s.get(system_id)


def _app(sim_manager, live, store):
    app = FastAPI()
    app.include_router(router)
    app.state.sim_manager = sim_manager
    app.state.live = live
    app.state.store = store
    return TestClient(app)


@pytest.fixture(scope="module")
def running():
    spec = SystemSpec(
        system_id="sim-1", series=4, parallel=2, duration_s=600, dt_s=1.0,
        profile=ProfileSpec("constant_current", {"amps": 16.0}),
        faults=[FaultSpec("internal_short", 1, 0, 200.0, {"r_short_ohm": 1.0})],
    )
    sim = build_simulator(spec)
    frames = list(sim.run())
    return sim, spec, frames[-1].to_dict()


def test_a_running_simulation_is_explained_from_the_model_exactly(running):
    sim, spec, frame = running
    c = _app(
        _FakeSimManager(sim, spec),
        _FakeLive({"sim-1": {"telemetry": frame}}),
        _FakeStore(),
    )
    body = c.get("/api/systems/sim-1/explain", params={"level": "physics"}).json()
    assert body["source"] == "model"
    assert body["exact"] is True
    heat = next(a for a in body["attributions"] if a["key"] == "cell.heat_balance")
    # Only the model path can see fault heat -- telemetry does not carry it.
    assert any(t["key"] == "fault_heat" for t in heat["terms"])
    assert all(a["caveat"] is None for a in body["attributions"])
    # Imbalance is exact here too: per-cell resistance spread is invisible in a
    # telemetry frame but is sitting right there in the solver's arrays.
    assert any(a["key"] == "pack.imbalance" for a in body["attributions"])


def test_a_feed_with_no_model_is_explained_from_telemetry_and_says_so(running):
    _sim, spec, frame = running
    c = _app(
        _FakeSimManager(None, None),
        _FakeLive({"sim-1": {"telemetry": frame}}),
        _FakeStore({"sim-1": {"spec": spec.to_dict()}}),
    )
    body = c.get("/api/systems/sim-1/explain").json()
    assert body["source"] == "telemetry"
    assert body["exact"] is False
    assert all(a["caveat"] for a in body["attributions"])


def test_a_system_with_no_telemetry_and_no_model_is_a_404():
    c = _app(_FakeSimManager(None, None), _FakeLive({}), _FakeStore({}))
    assert c.get("/api/systems/ghost/explain").status_code == 404


def test_asking_about_a_cell_that_is_not_in_the_pack_is_a_400(running):
    _sim, spec, frame = running
    c = _app(
        _FakeSimManager(None, None),
        _FakeLive({"sim-1": {"telemetry": frame}}),
        _FakeStore({"sim-1": {"spec": spec.to_dict()}}),
    )
    r = c.get("/api/systems/sim-1/explain", params={"series": 99, "parallel": 99})
    assert r.status_code == 400


# -- the single-luminaire route (what a *site* has, not a room) ------------


def test_explain_lamp_returns_output_and_efficacy(client):
    body = client.post("/api/explain/lamp", json={
        "spec": {"lamp_type": "led-9-e27", "operating_hours_h": 8000},
        "supply_voltage_v": 207.0, "ambient_c": 40.0,
        "domain": "lighting", "level": "working",
    }).json()
    keys = {a["key"] for a in body["attributions"]}
    assert keys == {"lamp.output", "lamp.efficacy"}
    # The lighting lens leads with the question, not the property.
    assert body["explanations"][0]["key"] == "lamp.output"
    out = next(a for a in body["attributions"] if a["key"] == "lamp.output")
    assert 0 < out["operating_point"]["fraction_of_rated"] < 1


def test_explain_lamp_agrees_with_the_operate_route_it_explains(client):
    entry = {"spec": {"lamp_type": "inc-60-e27"}, "supply_voltage_v": 207.0}
    operated = client.post("/api/lights/operate", json={
        "lights": [{"id": "L1", **entry}], "ambient_c": 40.0,
    }).json()["lights"]["L1"]
    body = client.post("/api/explain/lamp", json={**entry, "ambient_c": 40.0}).json()
    out = next(a for a in body["attributions"] if a["key"] == "lamp.output")
    # The explanation must be *of* the number the site solve produced.
    assert out["total"] == pytest.approx(operated["point"]["luminous_flux_lm"], rel=1e-6)


def test_explain_lamp_accepts_faults_and_shows_them_as_a_factor(client):
    body = client.post("/api/explain/lamp", json={
        "spec": {"lamp_type": "led-9-e27"}, "supply_voltage_v": 230.0,
        "faults": [{"type": "heatsink_loss", "severity": 0.8}], "elapsed_s": 3600,
    }).json()
    out = next(a for a in body["attributions"] if a["key"] == "lamp.output")
    fault = next(t for t in out["terms"] if t["key"] == "faults")
    assert fault["value"] < 1.0


def test_explain_lamp_rejects_an_unknown_lamp_and_an_unknown_fault(client):
    assert client.post("/api/explain/lamp",
                       json={"spec": {"lamp_type": "no-such-lamp"}}).status_code == 400
    assert client.post("/api/explain/lamp", json={
        "spec": {"lamp_type": "led-9-e27"},
        "faults": [{"type": "not_a_fault"}],
    }).status_code == 400


def test_explain_wires_honours_a_pinned_conductor_temperature(client):
    payload = {"spec": {"awg": 12, "length_m": 40.0, "ambient_temp_c": 35.0},
               "current_a": 18.0, "level": "physics"}
    pinned = client.post("/api/explain/wires", json={**payload, "at_temp_c": 52.0}).json()
    free = client.post("/api/explain/wires", json=payload).json()

    def temp(b):
        return next(a for a in b["attributions"]
                    if a["key"] == "wire.resistance")["operating_point"]["temp_c"]

    assert temp(pinned) == pytest.approx(52.0)
    assert temp(free) != pytest.approx(52.0)


def test_a_wire_explained_at_a_network_solved_temperature_reproduces_its_drop(client):
    """The contract a caller solving a whole site depends on.

    A network solve owns the conductor temperature: it accounts for the rest of
    the circuit, the weather and any faults. If the explanation re-derived its
    own, it would sit next to a voltage drop it quietly disagreed with, and a
    reader would have no way to tell which of the two to believe. Pinning the
    solved temperature is what closes that gap — here to the precision the API
    serialises at, which is as close as two JSON responses can get.
    """
    wire = {"wire_type": "cu-14-thhn90", "length_m": 18.4, "ambient_temp_c": 31.0}
    # A windy day, which is the sort of thing only the network solve knows about:
    # the wind is in *its* body, not in the conductor spec, so an explanation
    # left to re-derive its own temperature cannot possibly find the same one.
    seg = client.post("/api/wires/network", json={
        "nodes": [{"id": "a", "voltage": 51.2}, {"id": "b", "load_a": 6.0}],
        "segments": [{"id": "s1", "from": "a", "to": "b", "wire": wire}],
        "weather": {"air_temp_c": 31.0, "wind_speed_ms": 9.0, "solar_w_m2": 0.0},
    }).json()["segments"][0]

    def drop_of(body):
        return next(a for a in body["attributions"] if a["key"] == "wire.voltage_drop")["total"]

    pinned = drop_of(client.post("/api/explain/wires", json={
        "spec": wire,
        "current_a": abs(seg["current_a"]),
        "at_temp_c": seg["temp_c"],
        "round_trip": False,
    }).json())
    assert pinned == pytest.approx(seg["voltage_drop_v"], rel=1e-4)

    # Without the pin it lands somewhere else, which is exactly the failure the
    # pin exists to prevent: two panels, one cable, two different answers.
    unpinned = drop_of(client.post("/api/explain/wires", json={
        "spec": wire, "current_a": abs(seg["current_a"]), "round_trip": False,
    }).json())
    assert unpinned != pytest.approx(seg["voltage_drop_v"], rel=1e-4)
