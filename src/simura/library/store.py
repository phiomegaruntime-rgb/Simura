"""Where entries live.

The store is deliberately dumb: it holds entries and hands them back. Every rule
worth having -- what a fork is, when a reason is required, how a diff reads,
where a lineage goes -- lives in :mod:`~simura.library.record`,
:mod:`~simura.library.diff` and :mod:`~simura.library.lineage`, which are pure
functions over plain data. That is what lets the twin core persist the same
entries in TimescaleDB (:mod:`simura.twincore.store`) without reimplementing a
single one of those rules, and what lets this package be used with no database
at all.

:class:`InMemoryLibrary` is the reference implementation and the one the tests
drive. :class:`JsonFileLibrary` is the same thing with a file behind it, which
is all a person on a laptop needs for their memory to survive their project.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import lineage as _lineage
from .diff import change_coverage, diff_specs
from .record import Entry, LibraryError, Note, Decision


class InMemoryLibrary:
    """A library held in a dict. Ordered by insertion, which is close enough to
    chronological for a store whose entries carry their own timestamps."""

    def __init__(self, entries: Iterable[Entry] = ()) -> None:
        self._entries: dict[str, Entry] = {e.entry_id: e for e in entries}

    # -- persistence hooks (JsonFileLibrary overrides) --------------------
    def _flush(self) -> None:  # pragma: no cover - trivial in the base class
        pass

    # -- writes -----------------------------------------------------------
    def save(self, entry: Entry) -> Entry:
        """Store an entry. Re-saving identical content is a no-op, not a copy.

        Ids are content hashes (:func:`~simura.library.record.entry_id_for`), so
        a duplicate save is the same entry arriving twice -- the notes and
        decisions already on the stored copy are kept rather than overwritten by
        a caller who did not know it was there.
        """
        existing = self._entries.get(entry.entry_id)
        if existing is not None:
            merged = existing
            for note in entry.notes:
                if note not in merged.notes:
                    merged = merged.with_note(note)
            for decision in entry.decisions:
                if decision not in merged.decisions:
                    merged = merged.with_decision(decision)
            self._entries[entry.entry_id] = merged
            self._flush()
            return merged
        if entry.parent_id and entry.parent_id not in self._entries:
            raise LibraryError(f"parent '{entry.parent_id}' is not in this library")
        self._entries[entry.entry_id] = entry
        self._flush()
        return entry

    def add_note(self, entry_id: str, note: Note) -> Entry:
        entry = self.require(entry_id).with_note(note)
        self._entries[entry_id] = entry
        self._flush()
        return entry

    def add_decision(self, entry_id: str, decision: Decision) -> Entry:
        entry = self.require(entry_id).with_decision(decision)
        self._entries[entry_id] = entry
        self._flush()
        return entry

    def set_validated(self, entry_id: str, validated: bool) -> Entry:
        from dataclasses import replace

        entry = replace(self.require(entry_id), validated=bool(validated))
        self._entries[entry_id] = entry
        self._flush()
        return entry

    def delete(self, entry_id: str) -> bool:
        """Remove one entry. Its children keep pointing at the id that is gone.

        Deliberately not a cascade: a fork is somebody else's system, and losing
        it because the design it came from was tidied away is the exact failure
        this component exists to prevent. :func:`~simura.library.lineage.ancestry`
        stops cleanly at the missing link.
        """
        if entry_id not in self._entries:
            return False
        del self._entries[entry_id]
        self._flush()
        return True

    # -- reads ------------------------------------------------------------
    def get(self, entry_id: str) -> Entry | None:
        return self._entries.get(entry_id)

    def require(self, entry_id: str) -> Entry:
        entry = self._entries.get(entry_id)
        if entry is None:
            raise LibraryError(f"no library entry '{entry_id}'")
        return entry

    def all(self) -> list[Entry]:
        return list(self._entries.values())

    def index(self) -> dict[str, Entry]:
        return dict(self._entries)

    def list(
        self,
        *,
        kind: str | None = None,
        tag: str | None = None,
        author: str | None = None,
        query: str = "",
    ) -> list[Entry]:
        out = self.all()
        if kind:
            out = [e for e in out if e.kind == kind]
        if tag:
            out = [e for e in out if tag in e.tags]
        if author:
            out = [e for e in out if e.author == author]
        if query:
            out = [e for e in out if e.matches(query)]
        return out

    # -- lineage (thin delegations, so callers need one object) -----------
    def ancestry(self, entry_id: str) -> list[Entry]:
        return _lineage.ancestry(self._entries, entry_id)

    def children(self, entry_id: str) -> list[Entry]:
        return _lineage.children(self._entries, entry_id)

    def descendants(self, entry_id: str) -> list[Entry]:
        return _lineage.descendants(self._entries, entry_id)

    def tree(self, entry_id: str | None = None) -> list[dict[str, Any]]:
        return _lineage.tree(self._entries, entry_id)

    def trace(self, entry_id: str) -> dict[str, Any]:
        self.require(entry_id)
        return _lineage.trace(self._entries, entry_id)

    def inherited_context(self, entry_id: str) -> dict[str, Any]:
        self.require(entry_id)
        return _lineage.inherited_context(self._entries, entry_id)

    def summary(self) -> dict[str, Any]:
        return _lineage.summarize_library(self.all())

    def coverage(self, entry_id: str) -> dict[str, Any]:
        """How much of this entry's difference from its parent has a reason."""
        entry = self.require(entry_id)
        parent = self.get(entry.parent_id) if entry.parent_id else None
        if parent is None:
            return {"total": 0, "explained": 0, "unexplained": [], "complete": True}
        return change_coverage(diff_specs(parent.spec, entry.spec), entry.decisions)

    # -- portability ------------------------------------------------------
    def to_dicts(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.all()]

    @staticmethod
    def from_dicts(rows: Sequence[dict[str, Any]]) -> "InMemoryLibrary":
        """Rebuild from exported rows, parents before children.

        Placing parents first is what makes an export importable in any order:
        ids are content hashes, so a child names a parent that will exist, but
        not necessarily one that has arrived yet.
        """
        lib = InMemoryLibrary()
        pending = [Entry.from_dict(r) for r in rows]
        placed = True
        while pending and placed:
            placed = False
            for entry in list(pending):
                if entry.parent_id and entry.parent_id not in lib._entries:
                    continue
                lib._entries[entry.entry_id] = entry
                pending.remove(entry)
                placed = True
        # Anything left has a parent that is not in the export at all; keep it,
        # with its dangling link, rather than dropping somebody's system.
        for entry in pending:
            lib._entries[entry.entry_id] = entry
        lib._flush()
        return lib


class JsonFileLibrary(InMemoryLibrary):
    """The same library, written to one JSON file on every change.

    Rewriting the whole file is fine at this size and buys atomic-enough
    behaviour with no dependencies -- and a library you can read, diff and
    commit alongside the project it belongs to, which is most of the point.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        rows: list[dict[str, Any]] = []
        if self.path.exists():
            rows = json.loads(self.path.read_text(encoding="utf-8")).get("entries", [])
        super().__init__()
        loaded = InMemoryLibrary.from_dicts(rows)
        self._entries = loaded._entries

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "entries": self.to_dicts()}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
