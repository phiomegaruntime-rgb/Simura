"""Tests for the ``/api/space/*`` routes.

Most of :mod:`simura.space` is a library and is tested as one in
``test_space``. What is left over -- and what this file is for -- is the wiring:
that an upload of each format comes back as a plan, that a bad file is a 4xx
rather than a 500, that the responses are plain JSON, and that the three
couplings actually join up over HTTP.

There is no store to stub, because these routes have none. Every one of them is
pure compute: the client holds the plan and posts it back, exactly as it does
for ``/api/wires/network``. That is a deliberate property rather than an
omission -- a floor plan is an artifact somebody keeps, not a session on a
server, and these tests are where that stays true.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from simura.space import RectangleProvider
from simura.twincore.api import router
from tests.test_space import DXF, GBXML, IFC


class StubSettings:
    validation_max_upload_mb = 8.0


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.state.settings = StubSettings()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def plan_doc() -> dict:
    """The generated example building, as the document a client would hold."""
    return RectangleProvider().plan().to_dict()


@pytest.fixture
def gbxml_doc(client) -> dict:
    response = client.post(
        "/api/space/import",
        files={"file": ("block-a.xml", GBXML.encode(), "application/xml")},
    )
    assert response.status_code == 200
    return response.json()["plan"]


# ---------------------------------------------------------------------------
# options and import
# ---------------------------------------------------------------------------

def test_the_import_form_is_described_by_the_server(client):
    body = client.get("/api/space/options").json()
    assert "ifc" in body["types"] and "gbxml" in body["types"] and "dxf" in body["types"]
    assert body["params"]["dxf"]["wall_layers"] == ""
    assert "office" in body["occupancies"]
    assert body["routing_defaults"]["tray_height_m"] > 0
    assert isinstance(body["ifc_full_available"], bool)


@pytest.mark.parametrize(
    "filename,payload,rooms",
    [
        ("block-a.xml", GBXML, 2),
        ("harbour.ifc", IFC, 1),
        ("floor.dxf", DXF, 2),
    ],
)
def test_each_format_uploads_to_a_plan(client, filename, payload, rooms):
    response = client.post(
        "/api/space/import", files={"file": (filename, payload.encode(), "text/plain")}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["plan"]["spaces"]) == rooms
    assert body["plan"]["id"]
    # The plan and what the import could not read arrive together. Showing one
    # without the other is showing half the answer.
    assert "fidelity" in body["plan"]
    assert body["summary"]["fidelity"]["summary"]


def test_an_upload_says_what_it_assumed(client):
    body = client.post(
        "/api/space/import", files={"file": ("floor.dxf", DXF.encode(), "text/plain")}
    ).json()
    fidelity = body["plan"]["fidelity"]
    assert fidelity["complete"] is False
    assert any(i["field"] == "height_m" for i in fidelity["inferences"])
    assert fidelity["skipped"]


def test_a_file_that_is_not_a_building_is_a_4xx(client):
    response = client.post(
        "/api/space/import", files={"file": ("notes.rvt", b"\x00\x01\x02", "text/plain")}
    )
    assert response.status_code == 400
    assert "Supported" in response.json()["detail"]


def test_an_empty_upload_is_refused(client):
    response = client.post(
        "/api/space/import", files={"file": ("empty.ifc", b"", "text/plain")}
    )
    assert response.status_code == 400


def test_a_dxf_layer_convention_can_be_declared_at_upload(client):
    drawing = (
        "0\nSECTION\n2\nHEADER\n9\n$INSUNITS\n70\n6\n0\nENDSEC\n"
        "0\nSECTION\n2\nENTITIES\n"
        # A layer name no convention would recognise -- "MyWalls" would in fact
        # be matched, since the keyword list looks for "wall" anywhere in the name.
        "0\nLINE\n8\nL01-CONSTR\n10\n0.0\n20\n0.0\n11\n5.0\n21\n0.0\n"
        "0\nENDSEC\n0\nEOF\n"
    )
    refused = client.post(
        "/api/space/import", files={"file": ("odd.dxf", drawing.encode(), "text/plain")}
    )
    assert refused.status_code == 400

    accepted = client.post(
        "/api/space/import",
        files={"file": ("odd.dxf", drawing.encode(), "text/plain")},
        data={"wall_layers": "l01-constr"},
    )
    assert accepted.status_code == 200
    assert len(accepted.json()["plan"]["walls"]) == 1


# ---------------------------------------------------------------------------
# the plan travels in the body
# ---------------------------------------------------------------------------

def test_a_route_takes_the_plan_the_client_is_holding(client, plan_doc):
    body = client.post("/api/space/summary", json={"plan": plan_doc}).json()
    assert body["spaces"] == 5
    assert body["floor_area_m2"] > 0


def test_a_route_can_also_be_given_a_source_to_build_from(client):
    body = client.post(
        "/api/space/summary", json={"space": {"type": "rect", "params": {"rooms": 2}}}
    ).json()
    assert body["spaces"] == 3


def test_a_request_with_neither_says_which_two_it_accepts(client):
    response = client.post("/api/space/summary", json={})
    assert response.status_code == 400
    assert "plan" in response.json()["detail"]


def test_a_malformed_plan_is_a_4xx_not_a_500(client):
    response = client.post(
        "/api/space/summary", json={"plan": {"spaces": [{"no_id": True}]}}
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# the couplings, over HTTP
# ---------------------------------------------------------------------------

def test_a_georeferenced_model_hands_back_a_weather_spec(client, gbxml_doc):
    body = client.post("/api/space/weather", json={"plan": gbxml_doc}).json()
    assert body["located"] is True
    assert body["weather"]["type"] == "open_meteo"
    assert body["weather"]["params"]["latitude"] == pytest.approx(51.4545)
    assert body["north_deg"] == pytest.approx(17.0)


def test_a_model_with_no_coordinates_says_so_rather_than_returning_zero(
    client, plan_doc
):
    body = client.post("/api/space/weather", json={"plan": plan_doc}).json()
    assert body["located"] is False
    assert body["weather"] is None


def test_every_room_comes_back_as_a_lighting_problem(client, gbxml_doc):
    body = client.post("/api/space/lighting", json={"plan": gbxml_doc}).json()
    assert len(body["targets"]) == 2
    office = next(t for t in body["targets"] if t["task"] == "office")
    assert office["length_m"] == pytest.approx(6.0)
    assert office["mounting_height_m"] == pytest.approx(2.0)
    # The irregular room is returned, and returned as undesignable-as-read.
    assert body["undesignable"] >= 1


def test_a_whole_building_can_be_designed_and_totalled(client, plan_doc):
    body = client.post(
        "/api/space/lighting", json={"plan": plan_doc, "recommend": True}
    ).json()
    assert body["building"]["designed"] == len(body["targets"])
    assert body["building"]["power_w"] > 0
    assert body["building"]["power_density_w_per_m2"] > 0
    assert all(r["recommendation"]["n_luminaires"] >= 0 for r in body["rooms"])


def test_a_room_is_lit_over_its_own_outline_not_its_bounding_box(client, gbxml_doc):
    body = client.post(
        "/api/space/layout",
        json={
            "plan": gbxml_doc,
            "space_id": "sp-plant",
            "grid_n": 9,
            "luminaires": [
                {"x_m": 8.0, "y_m": 2.0, "height_m": 2.6},
                {"x_m": 12.0, "y_m": 1.0, "height_m": 2.6},
            ],
        },
    ).json()
    assert body["rectangular"] is False
    grid = body["layout"]["grid"]
    # Points outside the L come back null: not floor, rather than dark floor.
    assert any(v is None for row in grid for v in row)
    assert body["layout"]["outline"]
    assert body["layout"]["area_m2"] == pytest.approx(24.0)


def test_lighting_a_room_that_is_not_in_the_plan_is_a_404(client, plan_doc):
    response = client.post(
        "/api/space/layout", json={"plan": plan_doc, "space_id": "nope"}
    )
    assert response.status_code == 404


def test_a_conditioned_room_shields_the_equipment_over_http(client, gbxml_doc):
    hot = {"air_temp_c": 38.0, "solar_w_m2": 900.0}
    office = client.post(
        "/api/space/ambient",
        json={"plan": gbxml_doc, "space_id": "sp-office", "weather": hot},
    ).json()["space"]
    assert office["indoor"] is True
    assert office["ambient_c"] == pytest.approx(21.0)
    assert office["shading_frac"] == 1.0
    assert "conditioned" in office["basis"]

    plant = client.post(
        "/api/space/ambient",
        json={"plan": gbxml_doc, "space_id": "sp-plant", "weather": hot},
    ).json()["space"]
    assert plant["indoor"] is False
    assert plant["ambient_c"] == pytest.approx(38.0)


def test_a_point_reports_the_room_it_is_standing_in(client, plan_doc):
    inside = client.post(
        "/api/space/at", json={"plan": plan_doc, "x_m": 3.0, "y_m": 3.8}
    ).json()
    assert inside["space"]["occupancy"] == "office"

    outside = client.post(
        "/api/space/at", json={"plan": plan_doc, "x_m": -50.0, "y_m": -50.0}
    ).json()
    # Not an error: standing outside the building is a real place to stand.
    assert outside["space"] is None


def test_a_cable_run_is_traced_and_its_legs_are_visible(client, plan_doc):
    body = client.post(
        "/api/space/route",
        json={"plan": plan_doc, "start": [3.0, 3.8], "end": [21.0, 3.8]},
    ).json()
    run = body["route"]
    assert run["ok"] is True
    assert run["length_m"] > 22.0
    kinds = [leg["kind"] for leg in run["legs"]]
    assert kinds.count("drop") == 2
    assert any(leg["space_name"].startswith("Corridor") for leg in run["legs"])


def test_a_routed_run_can_be_priced_as_a_conductor_in_one_call(client, plan_doc):
    body = client.post(
        "/api/space/route",
        json={
            "plan": plan_doc,
            "start": [3.0, 3.8],
            "end": [21.0, 3.8],
            "wire_type": "cu-10-thhn90",
            "current_a": 25.0,
            "system_voltage_v": 48.0,
        },
    ).json()
    assert body["wire"]["voltage_drop_v"] > 0
    # The conductor is solved at the length the building says, not a typed guess.
    assert body["wire_spec"]["length_m"] == pytest.approx(body["route"]["length_m"])


def test_an_unroutable_run_is_a_stated_estimate_rather_than_an_error(client):
    plan = {
        "spaces": [
            {"id": "a", "polygon": [[0, 0], [4, 0], [4, 4], [0, 4]]},
            {"id": "b", "polygon": [[10, 0], [14, 0], [14, 4], [10, 4]]},
        ]
    }
    body = client.post(
        "/api/space/route",
        json={"plan": plan, "start": [2, 2], "end": [12, 2], "slack_frac": 0},
    ).json()
    assert body["route"]["ok"] is False
    assert any("no path" in p for p in body["route"]["problems"])


def test_the_task_grid_covers_only_the_room(client, gbxml_doc):
    body = client.post(
        "/api/space/grid",
        json={"plan": gbxml_doc, "space_id": "sp-plant", "spacing_m": 0.5, "inset_m": 0},
    ).json()
    assert body["points"]
    # Nothing in the notch of the L.
    assert not any(x > 10.0 and y > 2.0 for x, y in body["points"])


def test_the_builder_form_offers_a_building_alongside_the_weather(client):
    body = client.get("/api/builder/options").json()
    assert "space_types" in body and "none" in body["space_types"]
    assert body["default_spec"]["space"]["type"] == "none"
