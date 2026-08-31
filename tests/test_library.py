"""Tests for the system library (simura.library).

The library's claim is narrow and checkable: *what changed is computed, only why
it changed is written down.* So these tests are built around the two halves of
that.

**Fidelity** -- the diff reports what the specs actually differ in, in the
vocabulary the model cards already own, and nothing else: a partial spec differs
from a complete one in nothing, a fault that appears reads as one change rather
than four columns, and the entry id is a function of content.

**Honesty** -- a change with no reason behind it is *reported* as one. That is
the mechanism the whole component rests on, so it is tested from both ends:
a fork made through the constructors starts complete, and an entry that arrived
some other way is shown incomplete rather than quietly assumed fine.

The bundled starter set is treated as a fixture with teeth: it is built through
the same constructors a user goes through, so asserting it validates, builds and
comes out fully explained is a test of the rules and not just of the data.
"""

from __future__ import annotations

import json

import pytest

from simura.builder import SystemSpec, build_simulator, validate_spec
from simura.library import (
    BUNDLED,
    SITE_FIELDS,
    Entry,
    InMemoryLibrary,
    JsonFileLibrary,
    LibraryError,
    Note,
    bundled_entries,
    change_coverage,
    descendants,
    diff_specs,
    fork,
    index,
    new_entry,
    promote,
    SiteError,
    apply_site,
    restore_site,
    revise,
    seed,
    summarize,
)


def _spec(**over) -> SystemSpec:
    base = dict(
        system_id="test-pack",
        name="Test pack",
        chemistry="NMC",
        series=8,
        parallel=2,
        capacity_ah=5.0,
        duration_s=600.0,
    )
    base.update(over)
    return SystemSpec(**base)


@pytest.fixture
def library() -> InMemoryLibrary:
    lib = InMemoryLibrary()
    seed(lib)
    return lib


# --------------------------------------------------------------------------
# The diff: computed, and in the model cards' words
# --------------------------------------------------------------------------


def test_a_spec_does_not_differ_from_itself():
    assert diff_specs(_spec().to_dict(), _spec().to_dict()) == []


def test_an_omitted_field_is_its_default_not_a_difference():
    """A partial body from an API and a complete row from the library are the
    same system when they are -- otherwise every diff is drowned in defaults."""
    partial = {"system_id": "test-pack", "name": "Test pack", "series": 8, "parallel": 2,
               "capacity_ah": 5.0, "duration_s": 600.0}
    assert diff_specs(partial, _spec().to_dict()) == []


def test_a_changed_field_is_labelled_and_explained_from_its_model_card():
    changes = diff_specs(_spec(), _spec(series=16))
    assert len(changes) == 1
    change = changes[0]
    assert change.path == "series" and change.key == "series"
    assert change.label == "Cells in series"        # from battery.pack, not the field name
    assert change.card == "battery.pack"
    assert change.why                                # the card's reason travels with the change
    assert change.before == 8 and change.after == 16
    assert change.ratio == pytest.approx(2.0)
    assert "8" in change.text() and "16" in change.text()


def test_units_come_from_the_card_and_the_size_of_the_move_is_reported():
    change = diff_specs(_spec(), _spec(ambient_temp_c=40.0))[0]
    assert change.unit == "°C"
    assert "°C" in change.text()
    assert "+60%" in change.text()


def test_a_parameter_with_no_card_still_gets_a_readable_label_and_unit():
    """Profile and fault params are documented per *type*, so there is no card to
    ask; the field name still has to arrive readable."""
    before = _spec()
    after = _spec()
    after.profile.params = {"discharge_a": 10.0}
    before.profile.params = {"discharge_a": 5.0}
    change = diff_specs(before, after)[0]
    assert change.label == "Discharge" and change.unit == "A"
    assert change.text() == "Discharge 5 A → 10 A (2×)"


def test_the_system_id_is_ignored_because_two_entries_always_differ_in_it():
    assert diff_specs(_spec(), _spec(system_id="something-else")) == []
    named = diff_specs(_spec(), _spec(name="Something else"))
    assert [c.key for c in named] == ["name"]


def test_a_fault_that_appears_reads_as_one_change_not_four_columns():
    after = _spec()
    after.faults = [SystemSpec.from_dict(
        {"faults": [{"type": "internal_short", "series": 3, "parallel": 1,
                     "start_s": 120.0, "params": {"r_short_ohm": 2.0}}]}
    ).faults[0]]
    changes = diff_specs(_spec(), after)
    assert len(changes) == 1
    text = changes[0].text()
    assert changes[0].kind == "added"
    assert "internal short" in text and "module 3" in text and "120 s" in text


def test_a_fault_that_is_tuned_reads_as_the_fields_that_moved():
    before = _spec()
    before.faults = SystemSpec.from_dict(
        {"faults": [{"type": "internal_short", "series": 3, "parallel": 1,
                     "start_s": 120.0, "params": {"r_short_ohm": 2.0}}]}
    ).faults
    after = SystemSpec.from_dict(before.to_dict())
    after.faults[0].params["r_short_ohm"] = 0.5
    keys = {c.key for c in diff_specs(before, after)}
    assert keys == {"r_short_ohm"}


def test_switching_the_load_profile_borrows_the_reasoning_of_the_type_chosen():
    before = _spec()
    after = _spec()
    after.profile.type = "constant_power"
    after.profile.params = {"watts": 1000.0}
    change = next(c for c in diff_specs(before, after) if c.path == "profile.type")
    assert change.label == "Load profile"
    assert change.card == "battery.profile"
    assert change.why  # the card entry for constant_power explains why it matters


def test_summarize_is_a_line_not_a_list():
    changes = diff_specs(_spec(), _spec(series=16, parallel=4, capacity_ah=8.0, dt_s=0.5))
    line = summarize(changes, limit=2)
    assert line.count("→") == 2 and line.endswith("more")


# --------------------------------------------------------------------------
# The rule: a change without a reason is refused, or reported
# --------------------------------------------------------------------------


def test_a_fork_without_a_reason_is_refused():
    parent = new_entry(_spec())
    with pytest.raises(LibraryError, match="reason"):
        fork(parent, _spec(series=16), name="Bigger", because="   ")


def test_a_revision_without_a_reason_is_refused():
    parent = new_entry(_spec())
    with pytest.raises(LibraryError, match="reason"):
        revise(parent, _spec(series=16), because="")


def test_a_fork_binds_its_reason_to_exactly_the_fields_that_moved():
    """The join nobody has to maintain: the reason is filed against the diff, so
    it names what changed even though the author only typed why."""
    parent = new_entry(_spec())
    child = fork(parent, _spec(series=16, ambient_temp_c=35.0),
                 name="Hot bigger pack", because="Site is hotter and needs the voltage")
    decision = child.decisions[0]
    assert set(decision.params) == {"series", "ambient_temp_c"}
    assert "Cells in series" in decision.choice
    coverage = change_coverage(diff_specs(parent.spec, child.spec), child.decisions)
    assert coverage["complete"] and coverage["explained"] == 2


def test_a_change_nobody_explained_is_reported_rather_than_assumed_fine():
    """An entry that arrived some other way -- an import, a hand-written row --
    has no decision bound to its diff, and the library says so."""
    parent = new_entry(_spec())
    orphan = Entry(
        entry_id="hand-written",
        name="Hand-written child",
        spec=_spec(series=16, cooling_conductance_w_per_k=0.2).to_dict(),
        parent_id=parent.entry_id,
        relation="fork",
    )
    coverage = change_coverage(diff_specs(parent.spec, orphan.spec), orphan.decisions)
    assert not coverage["complete"]
    assert {c["key"] for c in coverage["unexplained"]} == {
        "series", "cooling_conductance_w_per_k"
    }


def test_a_reason_covers_only_what_it_was_bound_to():
    parent = new_entry(_spec())
    child = fork(parent, _spec(series=16), name="Bigger", because="More voltage")
    # Someone tunes cooling afterwards and says nothing about it.
    tuned = Entry(**{**child.__dict__, "spec": _spec(series=16, cooling_conductance_w_per_k=0.2).to_dict()})
    coverage = change_coverage(diff_specs(parent.spec, tuned.spec), tuned.decisions)
    assert coverage["explained"] == 1
    assert [c["key"] for c in coverage["unexplained"]] == ["cooling_conductance_w_per_k"]


def test_a_fork_that_changes_nothing_is_allowed_and_still_records_why():
    """Taking somebody's rack unchanged into a new project is the reuse this
    component is for; the record of that is worth as much as a record of a change."""
    parent = new_entry(_spec())
    child = fork(parent, name="Same rack, new project", because="Site C is identical to site A")
    assert diff_specs(parent.spec, child.spec) == []
    assert child.decisions[0].because.startswith("Site C")
    assert child.decisions[0].choice == "no change to the spec"


def test_a_spec_that_would_not_run_is_refused():
    """A library of specs that fail on load hands the next person a debugging
    session instead of a starting point."""
    with pytest.raises(LibraryError, match="series"):
        new_entry(_spec(series=0))
    parent = new_entry(_spec())
    with pytest.raises(LibraryError):
        fork(parent, _spec(v_min=4.5, v_max=3.0), name="Broken", because="testing")


# --------------------------------------------------------------------------
# Identity and versioning
# --------------------------------------------------------------------------


def test_the_id_is_the_content_so_saving_the_same_thing_twice_is_one_entry():
    a = new_entry(_spec(), name="Rack")
    b = new_entry(_spec(), name="Rack")
    assert a.entry_id == b.entry_id
    assert new_entry(_spec(series=16), name="Rack").entry_id != a.entry_id
    assert a.entry_id.startswith("rack-")


def test_a_revision_advances_the_version_and_a_fork_starts_a_new_line():
    v1 = new_entry(_spec(), name="Rack")
    v2 = revise(v1, _spec(series=16), because="Higher bus voltage")
    v3 = revise(v2, _spec(series=16, parallel=4), because="More energy")
    assert [e.version for e in (v1, v2, v3)] == [1, 2, 3]
    assert v3.relation == "revision" and v3.parent_id == v2.entry_id

    branch = fork(v3, _spec(series=16, parallel=4, chemistry="LFP"),
                  name="LFP variant", because="Customer wants LFP")
    assert branch.version == 1 and branch.relation == "fork"


def test_a_revision_drops_the_validated_flag_because_it_has_not_been_checked():
    v1 = new_entry(_spec(), name="Rack", validated=True)
    assert revise(v1, _spec(series=16), because="Higher bus voltage").validated is False


def test_promotion_carries_the_context_forward_where_a_fork_does_not():
    origin = new_entry(_spec(), name="Rack").with_note(Note(text="Trips at 15:00", kind="gotcha"))
    template = promote(origin, because="Every project rebuilds this rack")
    assert template.kind == "template"
    assert [n.text for n in template.notes] == ["Trips at 15:00"]
    assert template.decisions[-1].because.startswith("Every project")

    child = fork(origin, name="Someone else's rack", because="New site")
    assert child.notes == ()  # a fork inherits by lineage, not by copy
    assert child.kind == "system"


# --------------------------------------------------------------------------
# Lineage: walked, not stored
# --------------------------------------------------------------------------


def test_ancestry_runs_root_first_and_trace_pairs_every_step_with_its_reason(library):
    story = library.trace("bundled.rack-lfp-16s4p-hot-template")
    assert [e["entry_id"] for e in story["chain"]] == [
        "bundled.rack-lfp-16s4p",
        "bundled.rack-lfp-16s4p-hot",
        "bundled.rack-lfp-16s4p-hot-template",
    ]
    assert story["generations"] == 2
    assert story["complete"] and story["unexplained"] == 0
    relations = [s["relation"] for s in story["steps"]]
    assert relations == ["fork", "promotion"]
    reasons = [
        item["decision"]["because"]
        for step in story["steps"]
        for item in step["changes"]
        if item["decision"]
    ]
    assert reasons and all(reasons)


def test_a_deleted_parent_ends_the_chain_instead_of_breaking_the_fork(library):
    """Losing somebody's system because the design it came from was tidied away
    is the exact failure this component exists to prevent."""
    assert library.delete("bundled.rack-lfp-16s4p")
    story = library.trace("bundled.rack-lfp-16s4p-hot")
    assert [e["entry_id"] for e in story["chain"]] == ["bundled.rack-lfp-16s4p-hot"]
    assert story["generations"] == 0
    assert library.get("bundled.rack-lfp-16s4p-hot") is not None


def test_descendants_and_tree_show_what_a_design_became(library):
    kids = descendants(library.index(), "bundled.rack-lfp-16s4p")
    assert {e.entry_id for e in kids} == {
        "bundled.rack-lfp-16s4p-hot",
        "bundled.rack-lfp-16s4p-hot-template",
    }
    forest = library.tree()
    assert len(forest) == 2  # two roots in the starter set
    rack = next(n for n in forest if n["entry"]["entry_id"] == "bundled.rack-lfp-16s4p")
    assert rack["children"][0]["children"][0]["entry"]["kind"] == "template"


def test_inherited_context_is_what_starting_from_project_n_actually_hands_you(library):
    inherited = library.inherited_context("bundled.rack-lfp-16s4p-hot-template")
    texts = [n["text"] for n in inherited["notes"]]
    assert any("Cooling and ambient move the answer together" in t for t in texts)
    assert any("4 hours at dt=2 s" in t for t in texts)
    # Nearest ancestor first: the fork's own gotcha before the root's note.
    assert texts.index([t for t in texts if "Cooling and ambient" in t][0]) < texts.index(
        [t for t in texts if "4 hours" in t][0]
    )
    froms = {d["from"] for d in inherited["decisions"]}
    assert "bundled.rack-lfp-16s4p" in froms  # the root's reasoning is still reachable


# --------------------------------------------------------------------------
# The store
# --------------------------------------------------------------------------


def test_saving_the_same_entry_twice_keeps_the_notes_already_on_it():
    lib = InMemoryLibrary()
    entry = lib.save(new_entry(_spec(), name="Rack"))
    lib.add_note(entry.entry_id, Note(text="Ran it overnight", kind="result"))
    again = lib.save(new_entry(_spec(), name="Rack"))
    assert len(lib.all()) == 1
    assert [n.text for n in again.notes] == ["Ran it overnight"]


def test_an_entry_whose_parent_is_not_here_is_refused():
    lib = InMemoryLibrary()
    orphan = fork(new_entry(_spec(), name="Rack"), name="Child", because="testing")
    with pytest.raises(LibraryError, match="parent"):
        lib.save(orphan)


def test_search_finds_an_entry_by_something_somebody_would_remember(library):
    hits = library.list(query="phoenix")
    assert hits == []
    hits = library.list(query="value-engineered")
    assert {e.entry_id for e in hits} == {
        "bundled.rack-lfp-16s4p-hot",
        "bundled.rack-lfp-16s4p-hot-template",
    }
    assert {e.kind for e in library.list(kind="template")} == {"template"}
    assert all("starter" in e.tags for e in library.list(tag="starter"))


def test_a_library_survives_a_round_trip_through_a_file(tmp_path):
    path = tmp_path / "library.json"
    lib = JsonFileLibrary(path)
    seed(lib)
    parent = lib.require("bundled.bench-nmc-4s2p")
    child = lib.save(fork(parent, _spec(), name="My bench", because="Starting from the starter"))
    lib.add_note(child.entry_id, Note(text="Ran clean", kind="result"))

    reopened = JsonFileLibrary(path)
    assert len(reopened.all()) == 6
    assert [n.text for n in reopened.require(child.entry_id).notes] == ["Ran clean"]
    assert reopened.trace(child.entry_id)["generations"] == 1
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_an_export_imports_in_any_order_because_ids_are_content(library):
    rows = library.to_dicts()
    rebuilt = InMemoryLibrary.from_dicts(list(reversed(rows)))
    assert len(rebuilt.all()) == len(rows)
    assert rebuilt.trace("bundled.rack-lfp-16s4p-hot-template")["generations"] == 2


# --------------------------------------------------------------------------
# The starter set, held to the same rules as everything else
# --------------------------------------------------------------------------


def test_every_bundled_system_validates_and_actually_runs():
    for entry in bundled_entries():
        spec = entry.system_spec()
        assert validate_spec(spec) == [], entry.entry_id
        sim = build_simulator(spec)
        frames = []
        for frame in sim.run():
            frames.append(frame)
            if len(frames) >= 20:
                break
        # It integrated rather than diverging: forward Euler on too large a
        # timestep does not crash, it produces absurd numbers.
        assert len(frames) == 20
        assert -40.0 < frames[-1].max_temp_c < 200.0


def test_no_bundled_change_is_left_unexplained():
    """The starter set goes through the same constructors a user does, so this
    is a test of the rule and not of the data."""
    lib = InMemoryLibrary()
    seed(lib)
    for entry in lib.all():
        assert lib.coverage(entry.entry_id)["complete"], entry.entry_id


def test_the_starter_set_demonstrates_the_whole_lifecycle():
    relations = {e.entry_id: e.relation for e in BUNDLED}
    assert set(relations.values()) == {"origin", "fork", "promotion"}
    assert sum(1 for e in BUNDLED if e.kind == "template") == 3


def test_seeding_twice_adds_nothing_and_disturbs_nothing(library):
    library.add_note("bundled.bench-nmc-4s2p", Note(text="mine", kind="note"))
    before = len(library.all())
    assert seed(library) == []
    assert len(library.all()) == before
    assert any(n.text == "mine" for n in library.require("bundled.bench-nmc-4s2p").notes)


def test_bundled_ids_and_timestamps_are_fixed_so_identity_survives_a_restart():
    first = bundled_entries()
    second = bundled_entries()
    assert [e.entry_id for e in first] == [e.entry_id for e in second]
    assert all(e.created_at == first[0].created_at for e in first)
    for entry in first:
        assert all(n.at == entry.created_at for n in entry.notes)
        assert all(d.at == entry.created_at for d in entry.decisions)
        if entry.parent_id:
            # Content-addressed ids would drift if a bundled spec were edited
            # without re-fixing the id; assert the readable ids are the fixed ones.
            assert entry.entry_id.startswith("bundled.")


def test_the_bundled_fork_changes_what_its_reason_claims_it_changes():
    """The reason on the hot-climate rack says cooling and ambient; the diff has
    to agree, or the starter set is teaching the thing this component forbids."""
    idx = index(bundled_entries())
    child = idx["bundled.rack-lfp-16s4p-hot"]
    changes = diff_specs(idx["bundled.rack-lfp-16s4p"].spec, child.spec)
    keys = {c.key for c in changes}
    assert {"cooling_conductance_w_per_k", "ambient_temp_c"} <= keys
    assert child.decisions[0].because.lower().count("cooling") >= 1


def test_the_library_summary_counts_what_a_landing_page_shows(library):
    summary = library.summary()
    assert summary == {
        "entries": 5,
        "templates": 3,
        "forks": 2,
        "roots": 2,
        "notes": 5,
        "decisions": 9,
        "validated": 2,
    }


# --------------------------------------------------------------------------
# The design / site split
# --------------------------------------------------------------------------


def test_a_caller_can_supply_the_site_but_not_the_design():
    """A rack in a sandbox stands in that sandbox's weather; that says nothing
    about the design, so it is the caller's to supply -- and only that much is."""
    design = _spec().to_dict()
    running = apply_site(
        design,
        {"weather": {"type": "synthetic", "params": {"mean_temp_c": 34.0}},
         "duration_s": 86400.0},
    )
    assert running["weather"]["type"] == "synthetic"
    assert running["duration_s"] == 86400.0
    assert running["series"] == design["series"]
    assert design["weather"]["type"] == "none"  # the stored entry is untouched

    with pytest.raises(SiteError, match="design"):
        apply_site(design, {"series": 99})
    assert set(SITE_FIELDS) == {"weather", "space", "profile", "duration_s"}


def test_the_room_a_rack_is_standing_in_is_site_not_design():
    """Which room a rack was put in says nothing about the rack.

    Without this, importing a building and dropping a saved design into one of
    its rooms would report "space: none -> gbxml #412" as a change somebody has
    to justify -- burying whatever they actually changed under a note about which
    room they walked into.
    """
    design = _spec().to_dict()
    running = apply_site(
        design,
        {"space": {"type": "gbxml", "params": {"path": "block-a.xml"}, "space_id": "sp-plant"}},
    )
    assert running["space"]["space_id"] == "sp-plant"
    assert design["space"]["type"] == "none"  # the stored entry is untouched

    # And it comes back off before the run is recorded as a design.
    restored = restore_site(running, design, ("space",))
    assert restored["space"]["type"] == "none"


def test_a_none_in_the_site_is_a_field_the_caller_is_not_claiming():
    running = apply_site(_spec().to_dict(), {"weather": None, "duration_s": 7200.0})
    assert running["weather"]["type"] == "none"
    assert running["duration_s"] == 7200.0


def test_the_site_comes_back_off_before_a_run_is_recorded_as_a_design():
    """The point of the split: a system captured out of a sandbox differs from
    its parent by what somebody did to it, never by where it was standing."""
    parent = new_entry(_spec(), name="Rack")
    ran = apply_site(
        parent.spec,
        {"weather": {"type": "synthetic", "params": {}},
         "profile": {"type": "constant_current", "params": {"amps": 37.0}},
         "duration_s": 86400.0},
    )
    assert diff_specs(parent.spec, ran)  # as it stands, three changes

    recorded = restore_site(ran, parent.spec, ["weather", "profile", "duration_s"])
    assert diff_specs(parent.spec, recorded) == []


def test_a_change_that_is_not_the_site_survives_the_restore():
    parent = new_entry(_spec(), name="Rack")
    ran = apply_site(parent.spec, {"duration_s": 86400.0})
    ran["faults"] = [{"type": "internal_short", "series": 1, "parallel": 0,
                      "start_s": 0.0, "params": {"r_short_ohm": 1.0}}]
    recorded = restore_site(ran, parent.spec, ["weather", "profile", "duration_s"])
    changes = diff_specs(parent.spec, recorded)
    assert [c.key for c in changes] == ["fault"]


def test_with_no_parent_the_site_falls_back_to_the_defaults_not_the_sandbox():
    """A design captured out of a sandbox must not arrive claiming that
    sandbox's weather is part of what it is."""
    ran = apply_site(_spec().to_dict(), {"weather": {"type": "synthetic", "params": {}}})
    recorded = restore_site(ran, None, ["weather"])
    assert recorded["weather"]["type"] == "none"
