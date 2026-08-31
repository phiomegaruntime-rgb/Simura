"""Lineage: how a system got here, reconstructed rather than recorded.

Every entry stores exactly one link -- its ``parent_id``. Ancestry, descendants
and the whole tree are walked from those links on read; nothing stores a
denormalised list of ancestors, because a denormalised list is a second copy of
the truth and the second copy is the one that goes wrong.

The function worth reading is :func:`trace`. It answers the question Component
17 exists for -- *why does project N+1 look like this?* -- by walking from the
root to an entry and, at each step, diffing the two specs and attaching the
reason somebody gave for the difference. The steps are computed; only the
reasons were typed.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .diff import change_coverage, diff_specs, explain_changes
from .record import Entry


def index(entries: Iterable[Entry]) -> dict[str, Entry]:
    """entry_id -> entry, the shape every function here takes."""
    return {e.entry_id: e for e in entries}


def ancestry(entries: Mapping[str, Entry], entry_id: str) -> list[Entry]:
    """Root first, the entry itself last.

    A parent that is missing from ``entries`` ends the walk rather than raising:
    a library that has had an entry deleted out from under a fork should still
    show the fork, with the chain honestly stopping where the record does.
    """
    chain: list[Entry] = []
    seen: set[str] = set()
    cursor: str | None = entry_id
    while cursor and cursor in entries and cursor not in seen:
        seen.add(cursor)
        entry = entries[cursor]
        chain.append(entry)
        cursor = entry.parent_id
    chain.reverse()
    return chain


def root_of(entries: Mapping[str, Entry], entry_id: str) -> Entry | None:
    chain = ancestry(entries, entry_id)
    return chain[0] if chain else None


def children(entries: Mapping[str, Entry], entry_id: str) -> list[Entry]:
    return sorted(
        (e for e in entries.values() if e.parent_id == entry_id),
        key=lambda e: (e.created_at, e.entry_id),
    )


def descendants(entries: Mapping[str, Entry], entry_id: str) -> list[Entry]:
    """Everything downstream, breadth-first. What a change here would affect."""
    out: list[Entry] = []
    queue = [entry_id]
    seen = {entry_id}
    while queue:
        for child in children(entries, queue.pop(0)):
            if child.entry_id in seen:
                continue
            seen.add(child.entry_id)
            out.append(child)
            queue.append(child.entry_id)
    return out


def roots(entries: Mapping[str, Entry]) -> list[Entry]:
    """Entries with no parent *in this library* -- where each story starts."""
    return sorted(
        (e for e in entries.values() if not e.parent_id or e.parent_id not in entries),
        key=lambda e: (e.created_at, e.entry_id),
    )


def tree(entries: Mapping[str, Entry], entry_id: str | None = None) -> list[dict[str, Any]]:
    """Nested ``{entry, children}`` from one root, or from every root."""
    tops = [entries[entry_id]] if entry_id and entry_id in entries else roots(entries)

    def node(entry: Entry) -> dict[str, Any]:
        return {
            "entry": entry.to_dict(),
            "children": [node(c) for c in children(entries, entry.entry_id)],
        }

    return [node(t) for t in tops]


def step(parent: Entry, child: Entry) -> dict[str, Any]:
    """One hop of a lineage: what changed, and whether anybody said why.

    The reasons are looked for on the *child*, because that is where the person
    who made the change was standing when they explained it.
    """
    changes = diff_specs(parent.spec, child.spec)
    paired = explain_changes(changes, child.decisions)
    return {
        "from": parent.entry_id,
        "to": child.entry_id,
        "relation": child.relation,
        "name": child.name,
        "version": child.version,
        "author": child.author,
        "at": child.created_at,
        "changes": [p.to_dict() for p in paired],
        "coverage": change_coverage(changes, child.decisions),
    }


def trace(entries: Mapping[str, Entry], entry_id: str) -> dict[str, Any]:
    """The whole story of one entry: the chain, every step, and what is missing.

    ``unexplained`` totals the changes along the chain that no decision accounts
    for. It is deliberately a number a reader sees rather than a warning the
    library keeps to itself: a lineage with gaps is still worth inheriting, and
    knowing where the gaps are is what tells the next person which question to
    go and ask.
    """
    chain = ancestry(entries, entry_id)
    steps = [step(chain[i - 1], chain[i]) for i in range(1, len(chain))]
    unexplained = sum(len(s["coverage"]["unexplained"]) for s in steps)
    changed = sum(s["coverage"]["total"] for s in steps)
    return {
        "entry_id": entry_id,
        "chain": [e.to_dict() for e in chain],
        "steps": steps,
        "generations": max(len(chain) - 1, 0),
        "changes": changed,
        "unexplained": unexplained,
        "complete": unexplained == 0,
    }


def inherited_context(entries: Mapping[str, Entry], entry_id: str) -> dict[str, Any]:
    """Every note and decision on the chain above an entry, nearest first.

    This is what "starting from project N" actually hands you: not the spec --
    a file could do that -- but the gotchas and the reasoning that came with it,
    including the ones recorded two forks ago by somebody who has left.
    """
    chain = ancestry(entries, entry_id)[:-1]  # the ancestors, not the entry itself
    notes: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for ancestor in reversed(chain):
        for note in ancestor.notes:
            notes.append({"from": ancestor.entry_id, "from_name": ancestor.name, **note.to_dict()})
        for decision in ancestor.decisions:
            decisions.append(
                {"from": ancestor.entry_id, "from_name": ancestor.name, **decision.to_dict()}
            )
    return {"notes": notes, "decisions": decisions}


def summarize_library(entries: Sequence[Entry]) -> dict[str, Any]:
    """Counts a landing page can show: how much memory this library holds."""
    idx = index(entries)
    templates = [e for e in entries if e.kind == "template"]
    forks = [e for e in entries if e.relation == "fork"]
    notes = sum(len(e.notes) for e in entries)
    decisions = sum(len(e.decisions) for e in entries)
    return {
        "entries": len(entries),
        "templates": len(templates),
        "forks": len(forks),
        "roots": len(roots(idx)),
        "notes": notes,
        "decisions": decisions,
        "validated": sum(1 for e in entries if e.validated),
    }
