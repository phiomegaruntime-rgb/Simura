"""The systems a library starts with, so nobody's first day is a blank builder.

Component 17's premise is that project N+1 inherits project N. On day one there
is no project N, and a library with nothing in it teaches the wrong lesson about
what a library is for. These five entries are a plausible project N: two designs
somebody would actually build, a fork of each, and one of those forks promoted
back into a template -- which is the whole lifecycle this component describes,
already run once, and readable before a newcomer has built anything.

They are also the honest test of the rest of the package. They are built through
the same :func:`~simura.library.record.fork` and
:func:`~simura.library.record.promote` any user goes through, so the suite can
assert that every bundled spec validates, every bundled fork's diff comes out
the way its reason claims, and no bundled change is left unexplained. A starter
set that cheated its way past the rules would be a starter set teaching people
to cheat past them.

Ids and timestamps are fixed rather than generated: these ship in the wheel and
get seeded into whatever database is in front of them, possibly repeatedly, and
an entry that changes identity on every restart is not memory.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..builder import FaultSpec, ProfileSpec, SystemSpec, WeatherSpec
from .record import Decision, Entry, Note, fork, new_entry, promote

# The date this starter set was written. Fixed so a bundled entry has the same
# content -- and therefore the same identity -- in every install.
BUNDLED_AT = "2026-08-24T09:00:00+00:00"
BUNDLED_AUTHOR = "Simura"


def _stamp(entry: Entry) -> Entry:
    """Freeze every timestamp on an entry, including its notes and decisions."""
    return replace(
        entry,
        created_at=BUNDLED_AT,
        source="bundled",
        author=entry.author or BUNDLED_AUTHOR,
        notes=tuple(replace(n, at=BUNDLED_AT) for n in entry.notes),
        decisions=tuple(replace(d, at=BUNDLED_AT) for d in entry.decisions),
    )


# --------------------------------------------------------------------------
# 1. A bench pack -- the smallest thing worth calling a system
# --------------------------------------------------------------------------

_BENCH = SystemSpec(
    system_id="bench-nmc-4s2p",
    name="Bench pack (NMC 4S2P)",
    chemistry="NMC",
    capacity_ah=5.0,
    series=4,
    parallel=2,
    initial_soc=0.8,
    ambient_temp_c=22.0,
    temp_max_c=55.0,
    duration_s=1800.0,
    dt_s=1.0,
    profile=ProfileSpec(
        type="cycle",
        params={
            "discharge_a": 10.0,
            "charge_a": 8.0,
            "discharge_s": 600.0,
            "charge_s": 600.0,
            "rest_s": 120.0,
        },
    ),
)

_BENCH_ENTRY = _stamp(
    new_entry(
        _BENCH,
        entry_id="bundled.bench-nmc-4s2p",
        name="Bench pack (NMC 4S2P)",
        kind="template",
        source="bundled",
        author=BUNDLED_AUTHOR,
        summary="Eight cells on a desk, cycling gently. The system to open first: "
        "small enough to watch every cell, long enough to see charge and heat move.",
        tags=("starter", "bench", "nmc"),
        validated=True,
        decisions=(
            Decision(
                question="How big should the starter pack be?",
                choice="4 series x 2 parallel, 5 Ah cells",
                because="Eight cells fit in one heatmap without scrolling and every "
                "one of them is individually legible. A 16S4P rack is more realistic "
                "and completely unreadable as a first screen.",
                params=("series", "parallel", "capacity_ah"),
                rejected=("16S4P, the smallest realistic rack", "1S1P, a single cell"),
                author=BUNDLED_AUTHOR,
            ),
            Decision(
                question="How hard should it be worked?",
                choice="10 A discharge, 8 A charge, with rests",
                because="About 1C on a 10 Ah string: enough current for warming and "
                "voltage sag to be visible within a minute, well short of anything "
                "that trips a limit. Nothing here should alarm unless somebody breaks it.",
                params=("discharge_a", "charge_a", "rest_s"),
                author=BUNDLED_AUTHOR,
            ),
        ),
        notes=(
            Note(
                text="Watch the imbalance number rather than the pack voltage. The cells "
                "start 1% apart in capacity, and that spread is what the balance figure "
                "is reporting -- it is not a fault, it is manufacturing.",
                kind="gotcha",
                author=BUNDLED_AUTHOR,
            ),
        ),
    )
)


# --------------------------------------------------------------------------
# 2. The same bench pack, broken on purpose -- a fork, with a reason
# --------------------------------------------------------------------------

_BENCH_FAULTED = replace(
    SystemSpec.from_dict(_BENCH.to_dict()),
    system_id="bench-nmc-4s2p-short",
    name="Bench pack with an internal short",
    duration_s=2400.0,
    faults=[
        FaultSpec(
            type="internal_short",
            series=2,
            parallel=0,
            start_s=600.0,
            params={"r_short_ohm": 1.5},
        )
    ],
)

_BENCH_FAULT_ENTRY = _stamp(
    fork(
        _BENCH_ENTRY,
        _BENCH_FAULTED,
        name="Bench pack with an internal short",
        entry_id="bundled.bench-nmc-4s2p-short",
        because="Learning what a healthy pack looks like takes ten minutes; learning "
        "what a sick one looks like takes a fault you can turn on at a known time. "
        "The short starts at t=600 s so there is a clean before to compare against.",
        author=BUNDLED_AUTHOR,
        summary="The starter pack with one cell quietly shorting from ten minutes in. "
        "The system to open second, next to the first one.",
        tags=("starter", "bench", "fault", "teaching"),
        rejected=("thermal_runaway, which is dramatic but over too quickly to study",),
    ).with_note(
        Note(
            text="The shorted cell heats before it sags. If you are watching voltage you "
            "will notice minutes after the heatmap already knew.",
            kind="result",
            author=BUNDLED_AUTHOR,
        )
    )
)


# --------------------------------------------------------------------------
# 3. An outdoor rack -- the shape a real project starts from
# --------------------------------------------------------------------------

_RACK = SystemSpec(
    system_id="rack-lfp-16s4p",
    name="Outdoor LFP rack (16S4P)",
    chemistry="LFP",
    capacity_ah=100.0,
    r0_ohm=0.0008,
    r1_ohm=0.0004,
    c1_farad=20000.0,
    thermal_capacity_j_per_k=1800.0,
    cooling_conductance_w_per_k=2.5,
    v_min=2.5,
    v_max=3.65,
    temp_max_c=55.0,
    series=16,
    parallel=4,
    initial_soc=0.6,
    ambient_temp_c=20.0,
    dt_s=2.0,
    duration_s=14400.0,
    profile=ProfileSpec(type="constant_power", params={"watts": 5000.0}),
    weather=WeatherSpec(
        type="synthetic",
        params={
            "mean_temp_c": 20.0,
            "temp_amplitude_c": 9.0,
            "solar_peak_w_m2": 750.0,
            "wind_mean_ms": 3.0,
            "wind_amplitude_ms": 2.0,
        },
    ),
)

_RACK_ENTRY = _stamp(
    new_entry(
        _RACK,
        entry_id="bundled.rack-lfp-16s4p",
        name="Outdoor LFP rack (16S4P)",
        kind="template",
        source="bundled",
        author=BUNDLED_AUTHOR,
        summary="A 20 kWh LFP rack in a cabinet outdoors, discharging at 5 kW through "
        "a day of real weather. The starting point for anything site-scale.",
        tags=("starter", "rack", "lfp", "outdoor"),
        validated=True,
        decisions=(
            Decision(
                question="LFP or NMC for a stationary rack?",
                choice="LFP",
                because="Stationary storage is not weight-constrained, and LFP's flat "
                "OCV curve and better thermal tolerance are worth more here than NMC's "
                "energy density. The flat curve is also why state of charge has to be "
                "counted rather than read off the voltage on this pack.",
                params=("chemistry", "v_max", "v_min"),
                rejected=("NMC, denser but less forgiving when a cell gets hot",),
                author=BUNDLED_AUTHOR,
            ),
            Decision(
                question="What cooling should a cabinet get?",
                choice="2.5 W/K per cell, passive",
                because="A sealed outdoor cabinet with no fan, sized so the rack holds "
                "temperature at 5 kW on a mild day and starts losing that argument in "
                "the afternoon sun. If it never got warm the weather coupling would be "
                "decoration.",
                params=("cooling_conductance_w_per_k", "thermal_capacity_j_per_k"),
                author=BUNDLED_AUTHOR,
            ),
            Decision(
                question="Where does the ambient temperature come from?",
                choice="A synthetic day rather than a fixed number",
                because="A fixed ambient hides the thing that actually decides whether "
                "an outdoor rack is fine: the afternoon, when solar gain and the day's "
                "peak land on top of the load at the same time. Synthetic rather than "
                "a live feed so the template runs identically on a laptop with no network.",
                params=("weather.type", "mean_temp_c", "solar_peak_w_m2"),
                rejected=("open_meteo, which needs a location and a network",),
                author=BUNDLED_AUTHOR,
            ),
        ),
        notes=(
            Note(
                text="4 hours at dt=2 s. Shorter and the weather never gets to the part "
                "of the day that matters.",
                author=BUNDLED_AUTHOR,
            ),
        ),
    )
)


# --------------------------------------------------------------------------
# 4. The rack somewhere hot -- a fork, and then a template in its own right
# --------------------------------------------------------------------------

_HOT_RACK = replace(
    SystemSpec.from_dict(_RACK.to_dict()),
    system_id="rack-lfp-16s4p-hot",
    name="LFP rack, hot climate, no fan",
    ambient_temp_c=35.0,
    cooling_conductance_w_per_k=1.2,
    temp_max_c=60.0,
    weather=WeatherSpec(
        type="synthetic",
        params={
            "mean_temp_c": 34.0,
            "temp_amplitude_c": 11.0,
            "solar_peak_w_m2": 980.0,
            "wind_mean_ms": 1.2,
            "wind_amplitude_ms": 1.0,
        },
    ),
)

_HOT_RACK_ENTRY = _stamp(
    fork(
        _RACK_ENTRY,
        _HOT_RACK,
        name="LFP rack, hot climate, no fan",
        entry_id="bundled.rack-lfp-16s4p-hot",
        because="The same rack quoted for a site at 35 C with the fan value-engineered "
        "out. Halving the cooling and raising the ambient is the whole difference, and "
        "it is enough to move the pack from comfortable to marginal by mid-afternoon.",
        author=BUNDLED_AUTHOR,
        summary="What the outdoor rack does when the climate and the budget both go "
        "the wrong way. The margin it loses is the argument for the fan.",
        tags=("rack", "lfp", "thermal", "teaching"),
        rejected=("raising temp_max_c and calling it fine",),
    ).with_note(
        Note(
            text="Cooling and ambient move the answer together, not separately: at 20 C "
            "the weaker cooling is survivable and at 35 C with a fan it is fine. Change "
            "one at a time and neither looks like the problem.",
            kind="gotcha",
            author=BUNDLED_AUTHOR,
        )
    )
)

_HOT_RACK_TEMPLATE = _stamp(
    promote(
        _HOT_RACK_ENTRY,
        entry_id="bundled.rack-lfp-16s4p-hot-template",
        name="Hot-climate rack (starting point)",
        because="Every project on a hot site re-derives this pack from the temperate "
        "one and re-argues the same fan. Promoting it means the next one starts from "
        "the argument instead of from the rack.",
        author=BUNDLED_AUTHOR,
        tags=("starter", "rack", "lfp", "hot-climate"),
    )
)


BUNDLED: tuple[Entry, ...] = (
    _BENCH_ENTRY,
    _BENCH_FAULT_ENTRY,
    _RACK_ENTRY,
    _HOT_RACK_ENTRY,
    _HOT_RACK_TEMPLATE,
)
"""The starter set, parents before children so it can be saved in order."""


def bundled_entries() -> list[Entry]:
    """A fresh copy of the starter set, in save order."""
    return list(BUNDLED)


def bundled_dicts() -> list[dict[str, Any]]:
    return [e.to_dict() for e in BUNDLED]


def seed(library) -> list[Entry]:
    """Add any bundled entry the library does not already have.

    Idempotent by identity rather than by flag: bundled ids are fixed, so
    seeding twice adds nothing and never disturbs the notes somebody has since
    written on a starter system. Seeding is the caller's decision, not this
    package's -- a library that re-seeds itself would keep handing back a
    starter system its owner deliberately deleted.
    """
    added: list[Entry] = []
    for entry in BUNDLED:
        if library.get(entry.entry_id) is None:
            added.append(library.save(entry))
    return added
