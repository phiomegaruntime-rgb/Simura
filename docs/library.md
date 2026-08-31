# The system library

The pain that started Simura is that every new project repeats from zero. Phase 1
can export a spec file, which solves the smallest part of it — the numbers
travel — and loses the part that actually cost somebody a month: *why* those are
the numbers, what was tried and rejected, what broke at 3pm on a hot Tuesday,
and which of the three racks in the folder is the one that was right.

`simura.library` is the record that survives the project. It is a standalone
package with no new dependencies; the twin core persists it in the TimescaleDB
it already runs, and the CLI keeps it in a single JSON file you can commit
alongside the project it belongs to.

## The design decision everything follows from

**What changed is computed; only why it changed is written down.**

No entry in the library stores a human-typed account of how it differs from its
parent. That account is *derived* from the two specs on every read, labelled in
the vocabulary [the model cards](explain.md) already own, and the reason a
person types is bound automatically to exactly the fields that moved.

```
Cooling conductance 2.5 W/K → 1.2 W/K (-52%)
Ambient temperature 20 °C → 35 °C (+75%)
  because Site B is in Phoenix, and the fan was value-engineered out.
```

Nobody typed the first two lines. They are recomputed every time anybody looks,
so they are still true in a year — which a hand-maintained changelog is not,
and, worse, nobody ever finds out.

It is [Component 16's commitment](explain.md) applied to memory: an *attributed*
record rather than an asserted one.

### The consequence: a gap is reported, not assumed away

Because the reason is bound to the spec keys it justifies, the library can
answer a question no spec folder can: **which changes has nobody explained?**

```python
lib.coverage(entry_id)
# {'total': 3, 'explained': 2, 'unexplained': [...], 'complete': False}
```

A fork made through `fork()` starts complete, because the reason is bound to the
diff at the moment it is typed. It stops being complete the moment somebody
tunes a field afterwards and says nothing about it. The library cannot make
anybody explain a change — but it can refuse to pretend the explanation is
there, which tells the next person exactly which question to go and ask.

## What an entry holds

| Field | What it is for |
| --- | --- |
| `spec` | The system itself — a Component 9 `SystemSpec`, validated on save |
| `decisions` | Why a number is the number it is, **bound to the spec keys it covers**, with the options considered and rejected |
| `notes` | What running it taught somebody: a `note`, a `gotcha`, or a `result` |
| `parent_id` + `relation` | Where it came from: `origin`, `revision`, `fork`, `promotion` |
| `source` | How it got here: `builder`, `twin` (captured from a running system), `import`, `bundled` |
| `validated` | That a person has checked it against something real. Never inferred |
| `tags`, `summary`, `author`, `created_at` | The ordinary provenance |

Entries are **immutable**. Tuning a system produces a new entry pointing back at
the old one, so the record of how a design got here is never overwritten by the
design it became.

### Identity is content

An entry's id is a readable slug plus a hash of its content, so saving
byte-identical content twice yields the same id — which is the right answer:
that is not two entries, it is one. It also means an entry keeps its identity
across an export and an import, so lineage survives leaving the database it was
written in.

### A spec that would not run is refused

`new_entry`, `fork` and `revise` validate through `simura.builder.validate_spec`
and raise `LibraryError` if it fails. A library of specs that die on load hands
the next person a debugging session instead of a starting point.

## Revision, fork, promotion

Three relations, and the difference between the first two is the reader's
judgement rather than a threshold on the size of a diff:

- **`revise`** — the next version of the *same* design. `version` advances; the
  `validated` flag is dropped, because a new version has not been checked
  whatever the old one was.
- **`fork`** — a *different* design that started from this one. Version restarts
  at 1: it is not the next version of the parent, it is a second story. A fork
  that changes nothing is allowed and is not a mistake — taking somebody's rack
  unchanged into a new project is exactly the reuse this component is for, and
  the record of *that* is worth as much as a record of a change.
- **`promote`** — make a system a template others start from. Promotion copies
  notes and decisions forward, unlike the other two, because a starting point
  stripped of the reasons behind it is just a spec file again.

`fork` and `revise` **refuse to run without a reason**. That is the only place
the library is opinionated, and it is the point of the whole component.

## Lineage is walked, not stored

Every entry stores exactly one link — its `parent_id`. Ancestry, descendants and
the whole tree are walked from those links on read. Nothing stores a
denormalised ancestor list, because a denormalised list is a second copy of the
truth and the second copy is the one that goes wrong.

```python
story = lib.trace(entry_id)
story["generations"]   # how far back it goes
story["steps"]         # each hop: the computed diff, paired with the typed reason
story["unexplained"]   # how many changes along the chain nobody accounted for
```

Deleting an entry does **not** cascade to its forks. A fork is somebody else's
system, and losing it because the design it came from was tidied away is the
exact failure this component exists to prevent; `ancestry` simply stops where
the record does.

`inherited_context(entry_id)` is what "starting from project N" actually hands
you: every note and decision on the chain above, nearest first — including the
ones recorded two forks ago by somebody who has left.

## The starter set

A library with nothing in it teaches the wrong lesson about what a library is
for, so five entries ship in the package: two designs, a fork of each, and one
of those forks promoted back into a template — the whole lifecycle, already run
once, readable before a newcomer has built anything.

| Entry | What it is |
| --- | --- |
| `bundled.bench-nmc-4s2p` | Eight cells on a desk, cycling gently. The one to open first |
| `bundled.bench-nmc-4s2p-short` | The same pack with a cell shorting from ten minutes in |
| `bundled.rack-lfp-16s4p` | A 20 kWh outdoor LFP rack through a day of synthetic weather |
| `bundled.rack-lfp-16s4p-hot` | That rack on a 35 °C site with half the cooling |
| `bundled.rack-lfp-16s4p-hot-template` | …promoted, so the next hot site starts from the argument |

They are built through the same constructors any user goes through, so the test
suite asserts that every bundled spec validates and runs, that each fork's diff
matches what its reason claims, and that no bundled change is left unexplained.
A starter set that cheated past the rules would teach people to cheat past them.

The twin core seeds them into an **empty** library on startup and never again:
a library that keeps handing back a starter system its owner deleted is not
memory.

## The loop back from a running twin

Running a saved system records which entry it came from
(`POST /api/library/{id}/instantiate`). When that system has been tuned — a
fault injected, a parameter changed — `POST /api/library/capture` files it as
the **next version** of the entry it came from, with a reason, rather than as
another unrelated spec in the folder.

That loop is what makes the library accumulate instead of collecting snapshots.
See [A caller with a place of its own](#a-caller-with-a-place-of-its-own) for what
a caller running the design somewhere of its own is allowed to change.

## A caller with a place of its own

Most of a `SystemSpec` is the design — chemistry, topology, cell parameters, the
numbers somebody argued about. Three fields are not:

| Field | What it actually describes |
| --- | --- |
| `weather` | Where the system is standing |
| `profile` | What is being drawn out of it |
| `duration_s` | How long *this* run lasts |

A caller that has a place of its own has to supply those. The 3D sandbox
(Component 13, developed separately) is the case that makes it unavoidable: a
rack placed in the world stands in the world's weather and powers the world's
cables, so running a saved design there **must** override all three.

`simura.library.site` states the rule once and both directions read it:

- `POST /api/library/{id}/instantiate` takes a `site` object and applies it on
  top of the entry's spec. Only those three fields are accepted — anything else
  is a 400, because what runs has to be the design the entry records, not an
  arbitrary rewrite laundered through somebody else's provenance.
- `POST /api/library/capture` takes a `site` list naming the same fields, and
  takes them back *off* before the entry is recorded — from the parent entry
  when there is one, and from the builder's defaults when there is not.

So a rack captured back out of a sandbox differs from the design it came from by
what somebody **did** to it — a cell they shorted — and never by where it was
standing. Without the rule, one of two bad things happens: either the library
cannot be used from the world at all, or every capture reports "weather source
none → synthetic" as a design change needing a reason, burying the change that
matters under a note about the sky.

## API

Everything is under `/api/library`. `POST /api/library/diff` is pure compute —
no library, no database — so the builder can show what an edit would change
before anything is saved.

| Route | Does |
| --- | --- |
| `GET /api/library` | List entries (`kind`, `tag`, `q`), each row carrying a computed one-line diff from its parent |
| `GET /api/library/{id}` | One entry with its diff, coverage, ancestry, children and inherited context |
| `GET /api/library/{id}/trace` | The whole story: every step from the root, with reasons |
| `GET /api/library/tree` | Lineage trees, one per root |
| `POST /api/library` | Save a system as a new root entry |
| `POST /api/library/diff` | Diff two specs (pure compute) |
| `POST /api/library/{id}/fork` | Fork it — 400 without a `because` |
| `POST /api/library/{id}/revise` | Next version — 400 without a `because` |
| `POST /api/library/{id}/promote` | Make it a template |
| `POST /api/library/{id}/notes` | Leave what you learned |
| `POST /api/library/{id}/decisions` | Record why, bound to the spec keys it covers |
| `POST /api/library/{id}/validated` | Mark that a person has checked it |
| `POST /api/library/{id}/instantiate` | Run it, remembering where it came from; `site` for a caller with a place of its own |
| `POST /api/library/capture` | Save a running system back into the library, minus the caller's `site` |
| `POST /api/library/seed` | Add the starter systems that are missing |
| `DELETE /api/library/{id}` | Delete one entry; its forks survive |

## Without a database

The whole package works on a laptop with nothing running:

```bash
python -m simura.library --seed --list
python -m simura.library --show bundled.rack-lfp-16s4p
python -m simura.library --trace bundled.rack-lfp-16s4p-hot
python -m simura.library --tree

python -m simura.library --fork bundled.rack-lfp-16s4p --name "Site B rack" \
    --set ambient_temp_c=38 --set cooling_conductance_w_per_k=1.5 \
    --because "Site B is in Phoenix and has no fan budget"

python -m simura.library --diff before.json after.json
```

`--library path.json` picks the file. A library you can only read while a
database is up is not memory that survives the project; it is memory that
survives the container.

```python
from simura.library import JsonFileLibrary, fork, seed

lib = JsonFileLibrary("my-project/library.json")
seed(lib)

parent = lib.require("bundled.rack-lfp-16s4p")
mine = lib.save(
    fork(parent, parent.spec | {"ambient_temp_c": 38.0}, name="Site B rack",
         because="Site B is in Phoenix; 20 °C flattered it.")
)
print(lib.trace(mine.entry_id)["unexplained"], "changes with no reason")
```

## In the dashboard

The **Library** section lists every saved system with its computed one-line diff,
and opening one shows what changed from its parent with the reason under it —
or, where there is none, a highlighted line saying so and a form to fill the gap
that binds the reason to the fields you tick.

"Open in builder" loads the entry into the [system builder](builder.md), which
then shows the live diff against it as you type and offers two saves: **as
v*n*+1** (this design's next version) or **as a fork** (a second design). Both
require the reason; neither asks you to describe the change.

## Worked example

```bash
python examples/inherit_a_system.py
```

Three engineers, one library file, no services: Ana designs a rack, Ben inherits
it for Phoenix and types one sentence, and Cass reads the whole argument back six
months later when both of them have moved on. The last section shows, on
purpose, what a change with no reason looks like.
