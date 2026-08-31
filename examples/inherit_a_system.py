"""Start project N+1 from project N, instead of from a blank builder.

Three engineers, one library file, no services running. Ana designs an outdoor
rack. Ben inherits it for a site in Phoenix and changes two numbers. Cass
inherits *Ben's* rack six months later, when both of them have moved on, and
reads back the entire argument -- including the thing Ben learned at 3pm on a
hot Tuesday and the option he considered and rejected.

The one thing to watch for: **nobody types what changed.** Every "cooling
conductance 2.5 W/K to 1.2 W/K" in the output below is computed from the two
specs at the moment it is printed, labelled from the same model cards the
dashboard uses. The only thing a human writes is *why*, and the library binds
that reason to exactly the fields that moved. So the record cannot drift from
the system, and a change nobody explained is *reported* rather than assumed
fine -- which the last section shows on purpose.

    python examples/inherit_a_system.py

The same library is browsable from the shell::

    python -m simura.library --library project.json --tree
    python -m simura.library --library project.json --trace <entry-id>
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from simura.builder import ProfileSpec, SystemSpec, WeatherSpec, preview  # noqa: E402
from simura.library import (  # noqa: E402
    Decision,
    Entry,
    JsonFileLibrary,
    Note,
    diff_specs,
    fork,
    new_entry,
)

# Windows consoles default to cp1252; the prose has arrows and degree signs.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


def rule(title: str) -> None:
    print(f"\n{title}\n" + "=" * len(title))


LIBRARY_PATH = Path(tempfile.gettempdir()) / "simura-example-library.json"
LIBRARY_PATH.unlink(missing_ok=True)
library = JsonFileLibrary(LIBRARY_PATH)


# ---------------------------------------------------------------------------
# 1. Ana designs a rack, and records why it is what it is.
# ---------------------------------------------------------------------------
rack = SystemSpec(
    system_id="rack-a",
    name="Outdoor LFP rack",
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
    profile=ProfileSpec("constant_power", {"watts": 5000.0}),
    weather=WeatherSpec("synthetic", {"mean_temp_c": 20.0, "temp_amplitude_c": 9.0,
                                      "solar_peak_w_m2": 750.0, "wind_mean_ms": 3.0}),
)

anas = library.save(
    new_entry(
        rack,
        name="Outdoor LFP rack",
        author="ana",
        summary="20 kWh LFP rack in a sealed cabinet, 5 kW discharge through a day of weather.",
        tags=("site-a", "rack"),
        decisions=(
            Decision(
                question="Fan or no fan?",
                choice="No fan: 2.5 W/K passive per cell",
                because="The cabinet is sealed against dust at this site, and the rack holds "
                "temperature at 5 kW without one. A fan is a moving part in a box nobody visits.",
                params=("cooling_conductance_w_per_k",),
                rejected=("A 60 mm fan on a thermostat, which needs a filter nobody will change",),
                author="ana",
            ),
        ),
        notes=(
            Note(text="Runs 4 hours so the afternoon is included. Shorter and it never gets "
                      "to the part of the day that decides anything.", author="ana"),
        ),
    )
)
rule("1. Ana saves a rack")
print(f"{anas.name}  [{anas.entry_id}]")
print(f"   {len(anas.decisions)} decision, {len(anas.notes)} note")
print(f"   peak cell temperature in preview: {preview(rack).peak_temp_c:.1f} °C")


# ---------------------------------------------------------------------------
# 2. Ben inherits it for a hotter site. He types one sentence; the library
#    computes the rest and files his sentence against the fields that moved.
# ---------------------------------------------------------------------------
hot = replace(
    SystemSpec.from_dict(rack.to_dict()),
    system_id="rack-b",
    name="Phoenix rack",
    ambient_temp_c=35.0,
    cooling_conductance_w_per_k=1.2,
    weather=WeatherSpec("synthetic", {"mean_temp_c": 34.0, "temp_amplitude_c": 11.0,
                                      "solar_peak_w_m2": 980.0, "wind_mean_ms": 1.2}),
)

bens = library.save(
    fork(
        anas,
        hot,
        name="Phoenix rack",
        because="Site B is in Phoenix. The 20 °C ambient flattered it, and the fan Ana "
        "left out was then value-engineered out of *this* build too.",
        author="ben",
        summary="Ana's rack, on a site 15 °C hotter, with half the cooling.",
        rejected=("Raising temp_max_c to 60 °C and calling it in spec",),
    )
)
library.add_note(
    bens.entry_id,
    Note(
        text="It is the two together, not either one: at 20 °C the weaker cooling is "
        "survivable and at 35 °C with Ana's cooling it is fine. Change one at a time and "
        "neither looks like the problem.",
        kind="gotcha",
        author="ben",
    ),
)

rule("2. Ben forks it -- and types only the reason")
print(f"peak cell temperature: Ana {preview(rack).peak_temp_c:.1f} °C  →  "
      f"Ben {preview(hot).peak_temp_c:.1f} °C")
print("\nwhat the library computed from the two specs:")
for change in diff_specs(anas.spec, bens.spec):
    print(f"   · {change.text()}")
print(f"\nwhat Ben actually typed: {len(bens.decisions[0].because)} characters of 'because'")
print(f"the library bound it to:  {', '.join(bens.decisions[0].params)}")


# ---------------------------------------------------------------------------
# 3. Six months later. Cass has never met either of them.
# ---------------------------------------------------------------------------
rule("3. Cass reads it back, six months later")
story = library.trace(bens.entry_id)
print(f"{story['generations']} generation, {story['changes']} changes, "
      f"{story['unexplained']} of them unexplained\n")
for step in story["steps"]:
    print(f"{step['name']}, {step['relation']}ed by {step['author']}:")
    # One reason covers several fields here, so it is printed once under them --
    # which is also exactly how the library stored it.
    for item in step["changes"]:
        print(f"   · {item['change']['text']}")
    reason = next((i["decision"] for i in step["changes"] if i["decision"]), None)
    if reason:
        print(f"\n   because {reason['because']}")

inherited = library.inherited_context(bens.entry_id)
print("\nand what came with it from further up the chain:")
for note in inherited["notes"]:
    print(f"   [{note['kind']}] {note['text']}  — {note['from_name']}")
for decision in inherited["decisions"]:
    print(f"   {decision['question']} → {decision['choice']}")
    print(f"      because {decision['because']}")
    if decision["rejected"]:
        print(f"      rejected: {'; '.join(decision['rejected'])}")


# ---------------------------------------------------------------------------
# 4. The gap the library will not paper over.
# ---------------------------------------------------------------------------
rule("4. What a change with no reason looks like")
# Somebody tunes a field through some other route -- an import, a hand-edited
# row, a script -- so no decision is bound to it.
tuned = replace(SystemSpec.from_dict(bens.spec), system_id="rack-b2", initial_soc=0.95)
orphan = Entry(
    entry_id="hand-edited",
    name="Phoenix rack (someone's copy)",
    spec=tuned.to_dict(),
    parent_id=bens.entry_id,
    relation="fork",
)
library.save(orphan)
coverage = library.coverage(orphan.entry_id)
print(f"{coverage['explained']} of {coverage['total']} changes have a reason on file.")
for change in coverage["unexplained"]:
    print(f"   ! {change['text']} — nobody said why")
    print(f"     ({change['why']})")

print(
    "\nThat line is the whole point. The library cannot make somebody explain a\n"
    "change, but it can refuse to pretend the explanation is there -- which tells\n"
    "the next person exactly which question to go and ask."
)

rule("The library itself")
print(f"file: {LIBRARY_PATH}")
print(library.summary())
print("\n   python -m simura.library --library "
      f"{LIBRARY_PATH.name} --tree")
