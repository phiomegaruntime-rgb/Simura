"""Memory that survives the project.

The pain this package exists for is the one that started Simura: every new
project repeats from zero. A spec file solves the smallest part of that -- the
numbers travel -- and loses the part that actually cost somebody a month: *why*
those are the numbers, what was tried and rejected, what broke at 3pm on a hot
Tuesday, and which of the three racks in the folder is the one that was right.

The design decision everything follows from
-------------------------------------------

**What changed is computed; only why it changed is written down.** No entry in
this library stores a human-typed account of how it differs from its parent.
That account is *derived* from the two specs on every read, labelled in the
vocabulary Component 16 already established, so it cannot fall out of step with
the system it describes -- and the reason a person types is bound automatically
to exactly the fields that moved, which is what lets the library report a change
nobody has explained.

It is Component 16's commitment applied to memory: an attributed record rather
than an asserted one. A changelog somebody maintains by hand is wrong within a
month and nobody finds out; a diff cannot be.

Four pieces
-----------

:mod:`~simura.library.record`
    :class:`Entry`, :class:`Note`, :class:`Decision`, and the only supported
    ways to make an entry -- :func:`new_entry`, :func:`revise`, :func:`fork`,
    :func:`promote`. Entries are immutable and forks and revisions refuse to run
    without a reason.
:mod:`~simura.library.diff`
    What changed between two specs, in plain language, joined back to the
    decisions that account for it.
:mod:`~simura.library.lineage`
    How a system got here, walked from ``parent_id`` links rather than stored.
    :func:`trace` is the one to read.
:mod:`~simura.library.templates`
    The starter set, so day one is not a blank builder -- and, because it is
    built through the same constructors, a live test that the rules hold.
:mod:`~simura.library.site`
    The line between what a system *is* and where it is being run, for callers
    that supply a site of their own -- the 3D sandbox, which stands a saved
    design in its own weather and wires it to its own loads.

Usage
-----

Inheriting a system instead of starting from nothing::

    from simura.library import JsonFileLibrary, fork, seed

    lib = JsonFileLibrary("my-project/library.json")
    seed(lib)                                     # the starter set, once

    parent = lib.require("bundled.rack-lfp-16s4p")
    spec = parent.spec | {"ambient_temp_c": 38.0}
    mine = lib.save(fork(parent, spec, name="Site B rack",
                         because="Site B is in Phoenix; 20 C flattered it."))

Reading back why a system looks the way it does::

    from simura.library import trace

    story = lib.trace(mine.entry_id)
    print(story["generations"], "generations,", story["unexplained"], "unexplained")
"""

from .diff import (
    ExplainedChange,
    SpecChange,
    change_coverage,
    diff_specs,
    explain_changes,
    group_by_reason,
    summarize,
)
from .lineage import (
    ancestry,
    children,
    descendants,
    index,
    inherited_context,
    root_of,
    roots,
    step,
    summarize_library,
    trace,
    tree,
)
from .record import (
    KINDS,
    RELATIONS,
    SOURCES,
    Decision,
    Entry,
    LibraryError,
    Note,
    entry_id_for,
    fork,
    new_entry,
    promote,
    revise,
)
from .site import SITE_FIELDS, SiteError, apply_site, check_site, restore_site
from .store import InMemoryLibrary, JsonFileLibrary
from .templates import BUNDLED, bundled_dicts, bundled_entries, seed

__all__ = [
    # the record
    "Entry",
    "Note",
    "Decision",
    "LibraryError",
    "KINDS",
    "RELATIONS",
    "SOURCES",
    "new_entry",
    "revise",
    "fork",
    "promote",
    "entry_id_for",
    # the diff
    "SpecChange",
    "ExplainedChange",
    "diff_specs",
    "summarize",
    "explain_changes",
    "group_by_reason",
    "change_coverage",
    # lineage
    "ancestry",
    "children",
    "descendants",
    "index",
    "inherited_context",
    "root_of",
    "roots",
    "step",
    "summarize_library",
    "trace",
    "tree",
    # the design / site split
    "SITE_FIELDS",
    "SiteError",
    "apply_site",
    "check_site",
    "restore_site",
    # stores
    "InMemoryLibrary",
    "JsonFileLibrary",
    # the starter set
    "BUNDLED",
    "bundled_entries",
    "bundled_dicts",
    "seed",
]
