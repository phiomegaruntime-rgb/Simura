"""Tests for the /api/library/* routes.

Most of `simura.library` is a library and is tested as one in `test_library`.
What is left over -- and what this file is for -- is the wiring: that a fork
without a reason is a 4xx rather than a 500, that the routes serialize to plain
JSON, and that the two places the library meets the twin actually join up --
running a saved system remembers which entry it came from, and capturing that
system back files it as the *next version* of that entry rather than as another
unrelated spec.

The store is stubbed rather than stood up. The point of these tests is the
branch a route takes and the object it hands back, not the SQL: the persistence
methods are six statements with no logic in them, and standing up TimescaleDB to
check that a dict came back out of a dict would test asyncpg, not Simura.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from simura.builder import FaultSpec, SystemSpec
from simura.twincore.api import router


class StubStore:
    """The library half of TimescaleStore, over dicts."""

    def __init__(self) -> None:
        self.entries: dict[str, dict[str, Any]] = {}
        self.systems: dict[str, dict[str, Any]] = {}

    # -- library ---------------------------------------------------------
    async def library_list(self) -> list[dict[str, Any]]:
        return [dict(e) for e in self.entries.values()]

    async def library_save(self, entry: dict[str, Any]) -> bool:
        if entry["entry_id"] in self.entries:
            return False
        self.entries[entry["entry_id"]] = dict(entry)
        return True

    async def library_add_note(self, entry_id: str, note: dict[str, Any]) -> None:
        self.entries[entry_id]["notes"] = list(self.entries[entry_id].get("notes", [])) + [note]

    async def library_add_decision(self, entry_id: str, decision: dict[str, Any]) -> None:
        self.entries[entry_id]["decisions"] = list(
            self.entries[entry_id].get("decisions", [])
        ) + [decision]

    async def library_set_validated(self, entry_id: str, validated: bool) -> None:
        self.entries[entry_id]["validated"] = validated

    async def library_delete(self, entry_id: str) -> bool:
        return self.entries.pop(entry_id, None) is not None

    # -- registry --------------------------------------------------------
    async def get_system(self, system_id: str):
        return self.systems.get(system_id)

    async def create_system(self, system_id, name, source, spec, run_state, library_entry_id=None):
        self.systems[system_id] = {
            "system_id": system_id,
            "name": name,
            "source": source,
            "spec": spec,
            "run_state": run_state,
            "library_entry_id": library_entry_id,
        }


class StubSimManager:
    """Enough SimManager for the routes under test: create, start, break.

    It keeps each system's spec the way the real one does -- in memory, mutated
    by an injected fault -- because that is exactly the seam the capture loop
    depends on: a fault has to reach the *registry* for a rack somebody broke to
    be saveable as the next version of the design it came from.
    """

    def __init__(self) -> None:
        self.created: list[str] = []
        self.specs: dict[str, SystemSpec] = {}

    def create(self, spec, speed=None):
        self.created.append(spec.system_id)
        self.specs[spec.system_id] = spec

    async def start(self, system_id: str) -> str:
        return "running"

    def is_managed(self, system_id: str) -> bool:
        return system_id in self.specs

    def spec(self, system_id: str):
        return self.specs.get(system_id)

    async def inject_fault(self, system_id: str, fault: FaultSpec) -> FaultSpec:
        stamped = FaultSpec(
            type=fault.type,
            series=fault.series,
            parallel=fault.parallel,
            start_s=240.0,
            params=dict(fault.params),
        )
        self.specs[system_id].faults.append(stamped)
        return stamped


class StubSettings:
    sim_default_speed = 1.0


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.state.store = StubStore()
    app.state.sim_manager = StubSimManager()
    app.state.settings = StubSettings()
    with TestClient(app) as c:
        yield c


def _spec(**over) -> dict[str, Any]:
    base = SystemSpec(system_id="rack-1", name="Rack 1", series=8, parallel=2, duration_s=600.0)
    for key, value in over.items():
        setattr(base, key, value)
    return base.to_dict()


def _save(client, **over) -> dict[str, Any]:
    body = {"spec": _spec(), "name": "Rack 1", "author": "ana", "tags": ["site-a"]}
    body.update(over)
    res = client.post("/api/library", json=body)
    assert res.status_code == 200, res.text
    return res.json()


# -- pure compute ----------------------------------------------------------


def test_diff_needs_no_library_and_speaks_the_model_cards_language(client):
    body = client.post(
        "/api/library/diff", json={"before": _spec(), "after": _spec(series=16)}
    ).json()
    assert body["count"] == 1
    change = body["changes"][0]
    assert change["label"] == "Cells in series"
    assert change["before"] == 8 and change["after"] == 16
    assert change["why"] and change["text"]
    assert body["summary"] == "Cells in series 8 → 16"


def test_diff_of_two_partial_specs_reports_only_what_a_person_changed(client):
    body = client.post(
        "/api/library/diff",
        json={"before": {"series": 8}, "after": {"series": 8, "ambient_temp_c": 35.0}},
    ).json()
    assert [c["key"] for c in body["changes"]] == ["ambient_temp_c"]


# -- saving, forking, and the rule about reasons ---------------------------


def test_saving_a_system_returns_it_with_its_context(client):
    body = _save(client)
    assert body["entry"]["name"] == "Rack 1"
    assert body["entry"]["kind"] == "system"
    assert body["parent"] is None and body["changes"] == []
    assert body["coverage"]["complete"] is True  # nothing to explain yet
    assert client.get("/api/library").json()["summary"]["entries"] == 1


def test_a_spec_that_would_not_run_is_a_400_not_a_500(client):
    res = client.post("/api/library", json={"spec": _spec(series=0)})
    assert res.status_code == 400
    assert "series" in str(res.json()["detail"])


def test_a_fork_without_a_reason_is_refused_by_the_route(client):
    parent = _save(client)["entry"]["entry_id"]
    missing = client.post(f"/api/library/{parent}/fork", json={"name": "Rack 2"})
    assert missing.status_code == 422  # the model requires the field at all
    empty = client.post(
        f"/api/library/{parent}/fork", json={"name": "Rack 2", "because": "  "}
    )
    assert empty.status_code == 400
    assert "reason" in str(empty.json()["detail"])


def test_forking_something_that_is_not_there_is_a_404(client):
    res = client.post("/api/library/nope/fork", json={"name": "x", "because": "y"})
    assert res.status_code == 404


def test_a_fork_comes_back_with_its_changes_already_paired_with_the_reason(client):
    parent = _save(client)["entry"]["entry_id"]
    body = client.post(
        f"/api/library/{parent}/fork",
        json={
            "name": "Rack 2 (hot site)",
            "because": "Site B runs at 35 C and has no fan budget",
            "spec": _spec(ambient_temp_c=35.0, cooling_conductance_w_per_k=0.25),
            "author": "ben",
        },
    ).json()
    assert body["entry"]["relation"] == "fork" and body["entry"]["version"] == 1
    assert body["parent"]["entry_id"] == parent
    assert body["coverage"]["complete"] is True
    labels = {c["change"]["label"] for c in body["changes"]}
    assert "Ambient temperature" in labels
    assert all(c["decision"]["because"].startswith("Site B") for c in body["changes"])


def test_a_revision_advances_the_version_and_the_trace_tells_the_story(client):
    parent = _save(client)["entry"]["entry_id"]
    v2 = client.post(
        f"/api/library/{parent}/revise",
        json={"spec": _spec(series=16), "because": "Inverter wants a higher bus voltage"},
    ).json()["entry"]
    assert v2["version"] == 2 and v2["relation"] == "revision"

    story = client.get(f"/api/library/{v2['entry_id']}/trace").json()
    assert story["generations"] == 1 and story["unexplained"] == 0
    assert story["steps"][0]["changes"][0]["decision"]["because"].startswith("Inverter")
    assert client.get("/api/library/nope/trace").status_code == 404


def test_promotion_makes_a_template_and_carries_the_notes_with_it(client):
    entry_id = _save(client)["entry"]["entry_id"]
    client.post(f"/api/library/{entry_id}/notes", json={"text": "Trips at 15:00", "kind": "gotcha"})
    body = client.post(
        f"/api/library/{entry_id}/promote",
        json={"because": "Every project rebuilds this rack from scratch"},
    ).json()
    assert body["entry"]["kind"] == "template"
    assert [n["text"] for n in body["entry"]["notes"]] == ["Trips at 15:00"]
    assert client.get("/api/library", params={"kind": "template"}).json()["summary"]["entries"] == 2
    assert client.get("/api/library", params={"kind": "boats"}).status_code == 400


def test_a_note_needs_text_and_a_decision_needs_a_because(client):
    entry_id = _save(client)["entry"]["entry_id"]
    assert client.post(f"/api/library/{entry_id}/notes", json={"text": " "}).status_code == 400
    assert (
        client.post(
            f"/api/library/{entry_id}/decisions", json={"question": "why?", "because": ""}
        ).status_code
        == 400
    )
    assert client.post("/api/library/nope/notes", json={"text": "hi"}).status_code == 404


def test_a_decision_recorded_later_covers_a_change_that_had_no_reason(client):
    """The join the whole component rests on, exercised over HTTP: bind a reason
    to a spec key and the change stops being reported as unexplained."""
    parent = _save(client)["entry"]["entry_id"]
    child = client.post(
        f"/api/library/{parent}/fork",
        json={"name": "Rack 2", "because": "New site", "spec": _spec(ambient_temp_c=35.0)},
    ).json()["entry"]["entry_id"]

    # Simulate an entry that arrived without the binding: strip the decisions.
    client.app.state.store.entries[child]["decisions"] = []
    before = client.get(f"/api/library/{child}").json()
    assert before["coverage"]["complete"] is False
    assert [c["key"] for c in before["coverage"]["unexplained"]] == ["ambient_temp_c"]

    after = client.post(
        f"/api/library/{child}/decisions",
        json={
            "question": "Why 35 C?",
            "because": "It is the 99th-percentile site temperature",
            "params": ["ambient_temp_c"],
        },
    ).json()
    assert after["coverage"]["complete"] is True


def test_validated_is_set_by_a_person_and_never_inferred(client):
    entry_id = _save(client)["entry"]["entry_id"]
    assert _save(client)["entry"]["validated"] is False
    body = client.post(f"/api/library/{entry_id}/validated", json={"validated": True}).json()
    assert body["entry"]["validated"] is True


def test_deleting_an_entry_leaves_its_fork_standing(client):
    parent = _save(client)["entry"]["entry_id"]
    child = client.post(
        f"/api/library/{parent}/fork", json={"name": "Rack 2", "because": "New site"}
    ).json()["entry"]["entry_id"]

    assert client.delete(f"/api/library/{parent}").json()["deleted"] is True
    assert client.delete(f"/api/library/{parent}").status_code == 404
    still_there = client.get(f"/api/library/{child}").json()
    assert still_there["parent"] is None  # the chain stops where the record does
    assert still_there["entry"]["parent_id"] == parent


def test_the_tree_shows_each_root_with_what_grew_out_of_it(client):
    parent = _save(client)["entry"]["entry_id"]
    client.post(f"/api/library/{parent}/fork", json={"name": "Rack 2", "because": "New site"})
    forest = client.get("/api/library/tree").json()
    assert len(forest) == 1
    assert forest[0]["entry"]["entry_id"] == parent
    assert forest[0]["children"][0]["entry"]["name"] == "Rack 2"


def test_search_covers_the_reasons_not_only_the_names(client):
    parent = _save(client)["entry"]["entry_id"]
    client.post(
        f"/api/library/{parent}/fork",
        json={"name": "Rack 2", "because": "Site B is in Phoenix", "spec": _spec(ambient_temp_c=40.0)},
    )
    hits = client.get("/api/library", params={"q": "phoenix"}).json()["entries"]
    assert [e["name"] for e in hits] == ["Rack 2"]
    assert hits[0]["change_summary"]  # computed on read, not stored


# -- the loop: library -> running twin -> library --------------------------


def test_running_a_saved_system_remembers_which_entry_it_came_from(client):
    entry_id = _save(client)["entry"]["entry_id"]
    started = client.post(f"/api/library/{entry_id}/instantiate", json={}).json()
    assert started["run_state"] == "running"
    assert started["entry_id"] == entry_id
    assert client.app.state.store.systems["rack-1"]["library_entry_id"] == entry_id

    # Running it a second time under the same id would replace the first.
    again = client.post(f"/api/library/{entry_id}/instantiate", json={})
    assert again.status_code == 409
    assert (
        client.post(
            f"/api/library/{entry_id}/instantiate", json={"system_id": "rack-1-b"}
        ).status_code
        == 200
    )
    assert client.post("/api/library/nope/instantiate", json={}).status_code == 404


def test_capturing_a_drifted_system_files_it_as_the_next_version(client):
    entry_id = _save(client)["entry"]["entry_id"]
    client.post(f"/api/library/{entry_id}/instantiate", json={})

    # The system is tuned while running, as the fault and control routes allow.
    client.app.state.store.systems["rack-1"]["spec"] = _spec(ambient_temp_c=33.0)

    refused = client.post("/api/library/capture", json={"system_id": "rack-1"})
    assert refused.status_code == 400  # a new version with no reason

    body = client.post(
        "/api/library/capture",
        json={
            "system_id": "rack-1",
            "because": "Measured the cabinet: it sits 8 C above the weather station",
            "author": "ana",
        },
    ).json()
    assert body["entry"]["version"] == 2 and body["entry"]["relation"] == "revision"
    assert body["parent"]["entry_id"] == entry_id
    assert body["coverage"]["complete"] is True
    # The running system now points at the new version, so the next capture
    # continues the chain instead of restarting it.
    assert client.app.state.store.systems["rack-1"]["library_entry_id"] == body["entry"]["entry_id"]


def test_capturing_an_unchanged_system_adds_nothing(client):
    entry_id = _save(client)["entry"]["entry_id"]
    client.post(f"/api/library/{entry_id}/instantiate", json={})
    body = client.post("/api/library/capture", json={"system_id": "rack-1"}).json()
    assert body["entry"]["entry_id"] == entry_id
    assert client.get("/api/library").json()["summary"]["entries"] == 1


def test_capturing_a_system_the_library_has_never_seen_starts_a_new_record(client):
    client.app.state.store.systems["field-01"] = {
        "system_id": "field-01",
        "name": "Field unit 1",
        "source": "simulation",
        "spec": _spec(system_id="field-01"),
        "run_state": "running",
        "library_entry_id": None,
    }
    body = client.post(
        "/api/library/capture",
        json={"system_id": "field-01", "summary": "Whatever is actually on site"},
    ).json()
    assert body["entry"]["source"] == "twin"
    assert body["entry"]["source_system_id"] == "field-01"
    assert body["entry"]["relation"] == "origin"


def test_capturing_a_real_time_feed_is_a_409_because_a_stream_is_not_a_design(client):
    client.app.state.store.systems["feed"] = {
        "system_id": "feed", "name": "Feed", "source": "realtime",
        "spec": None, "run_state": "running", "library_entry_id": None,
    }
    assert client.post("/api/library/capture", json={"system_id": "feed"}).status_code == 409
    assert client.post("/api/library/capture", json={"system_id": "ghost"}).status_code == 404


# -- the starter set -------------------------------------------------------


def test_seeding_hands_a_new_install_a_library_that_is_not_empty(client):
    added = client.post("/api/library/seed").json()["added"]
    assert len(added) == 5
    summary = client.get("/api/library").json()["summary"]
    assert summary["templates"] == 3 and summary["decisions"] >= 9

    assert client.post("/api/library/seed").json()["added"] == []

    story = client.get("/api/library/bundled.rack-lfp-16s4p-hot-template/trace").json()
    assert story["generations"] == 2 and story["complete"] is True


# -- the caller's own site (the 3D sandbox's case) -------------------------

SITE = {
    "weather": {"type": "synthetic", "params": {"mean_temp_c": 34.0}},
    "profile": {"type": "constant_current", "params": {"amps": 37.0}},
    "duration_s": 86400.0,
}


def test_a_caller_with_a_place_of_its_own_runs_the_design_in_it(client):
    """The sandbox's case: a rack placed in the world stands in the world's
    weather and draws the world's current, and neither is part of the design."""
    entry_id = _save(client)["entry"]["entry_id"]
    started = client.post(
        f"/api/library/{entry_id}/instantiate",
        json={"system_id": "world-abc", "site": SITE},
    ).json()
    assert started["entry_id"] == entry_id
    assert started["site"] == ["duration_s", "profile", "weather"]

    ran = client.app.state.store.systems["world-abc"]["spec"]
    assert ran["weather"]["type"] == "synthetic"
    assert ran["profile"]["params"]["amps"] == 37.0
    assert ran["series"] == 8  # the design came through untouched


def test_a_caller_cannot_launder_a_design_change_through_the_site(client):
    entry_id = _save(client)["entry"]["entry_id"]
    res = client.post(
        f"/api/library/{entry_id}/instantiate",
        json={"system_id": "world-x", "site": {"series": 64}},
    )
    assert res.status_code == 400
    assert "design" in str(res.json()["detail"])


def test_capturing_back_from_a_sandbox_ignores_where_it_was_standing(client):
    entry_id = _save(client)["entry"]["entry_id"]
    client.post(
        f"/api/library/{entry_id}/instantiate",
        json={"system_id": "world-abc", "site": SITE},
    )
    body = client.post(
        "/api/library/capture",
        json={"system_id": "world-abc", "site": list(SITE)},
    ).json()
    # Nothing about the design changed, so there is no new version to record.
    assert body["entry"]["entry_id"] == entry_id
    assert client.get("/api/library").json()["summary"]["entries"] == 1


def test_capturing_a_rack_somebody_broke_records_the_fault_and_nothing_else(client):
    """The payoff: what comes back from the world is what was *done* to the
    rack, with the weather and the load it happened to be under left out."""
    entry_id = _save(client)["entry"]["entry_id"]
    client.post(
        f"/api/library/{entry_id}/instantiate",
        json={"system_id": "world-abc", "site": SITE},
    )
    ran = client.app.state.store.systems["world-abc"]["spec"]
    ran["faults"] = [
        {"type": "internal_short", "series": 3, "parallel": 1, "start_s": 240.0,
         "params": {"r_short_ohm": 1.0}}
    ]
    body = client.post(
        "/api/library/capture",
        json={
            "system_id": "world-abc",
            "site": list(SITE),
            "name": "Rack 1 with the shorted cell",
            "because": "Found this in the world: module 3 shorts under load.",
        },
    ).json()
    assert body["entry"]["version"] == 2
    keys = [c["change"]["key"] for c in body["changes"]]
    assert "fault" in keys
    assert "weather.type" not in keys and "amps" not in keys
    assert body["coverage"]["complete"] is True


def test_a_sandbox_system_the_library_never_saw_does_not_bring_the_sandbox_with_it(client):
    """A rack built in the world and saved for the first time is a design, so
    the world's weather and load must not arrive as part of it."""
    client.app.state.store.systems["world-new"] = {
        "system_id": "world-new", "name": "World NMC 12S2P", "source": "simulation",
        "spec": {**_spec(system_id="world-new"), **SITE}, "run_state": "running",
        "library_entry_id": None,
    }
    body = client.post(
        "/api/library/capture",
        json={"system_id": "world-new", "site": list(SITE)},
    ).json()
    assert body["entry"]["relation"] == "origin"
    assert body["entry"]["spec"]["weather"]["type"] == "none"
    assert body["entry"]["spec"]["profile"]["type"] == "cycle"


def test_breaking_a_rack_reaches_the_registry_so_it_can_be_saved(client):
    """The whole sandbox loop in one test: place a saved design, break it where
    you are standing, and save what you found as the next version of it.

    The seam this guards is the one that was actually wrong: an injected fault
    changed the running simulation's spec and nothing else, so the registry went
    on describing a rack nobody had ever broken — and a capture found nothing to
    record.
    """
    entry_id = _save(client)["entry"]["entry_id"]
    client.post(
        f"/api/library/{entry_id}/instantiate",
        json={"system_id": "world-abc", "site": SITE},
    )

    injected = client.post(
        "/api/systems/world-abc/faults",
        json={"type": "internal_short", "series": 3, "parallel": 1,
              "params": {"r_short_ohm": 1.0}},
    )
    assert injected.status_code == 200
    assert client.app.state.store.systems["world-abc"]["spec"]["faults"]

    saved = client.post(
        "/api/library/capture",
        json={
            "system_id": "world-abc",
            "site": list(SITE),
            "because": "Module 3 shorts once the yard lights are on it.",
        },
    ).json()
    assert saved["entry"]["version"] == 2
    assert [c["change"]["key"] for c in saved["changes"]] == ["fault"]
    assert "internal short" in saved["changes"][0]["change"]["text"]
    # And the running rack now points at what it became, so the next capture
    # continues the chain instead of forking off the version before it.
    assert (
        client.app.state.store.systems["world-abc"]["library_entry_id"]
        == saved["entry"]["entry_id"]
    )
