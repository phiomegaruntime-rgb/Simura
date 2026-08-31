"""The record: what a saved system carries besides its numbers.

An :class:`Entry` is one system in the library -- a spec, plus the context that
made it worth keeping. Entries are **immutable**: tuning a system produces a new
entry that points back at the old one, so the record of how a design got here is
never overwritten by the design it became.

The design decision this file exists to enforce
-----------------------------------------------

**What changed is computed; only why it changed is written down.** Nothing here
lets a caller type "I raised the series count" -- that sentence is derived from
the two specs by :mod:`simura.library.diff`, and it stays true forever because
it is recomputed on read. What a caller *must* supply is the half no spec can
contain: the reason. :func:`fork` and :func:`revise` refuse to run without one,
and the reason they take is bound automatically to exactly the fields that
moved, so "why" and "what" cannot drift apart.

That is the same commitment Component 16 made to explanations, applied to
memory: an attributed record rather than an asserted one.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable

from ..builder import SystemSpec, validate_spec
from .diff import SpecChange, diff_specs, summarize

# What a saved thing is. A "system" is somebody's actual design; a "template" is
# one that has been promoted as a starting point for other people.
KINDS = ("system", "template")

# How an entry relates to its parent. Set by the constructors below, never
# chosen by hand.
RELATIONS = ("origin", "revision", "fork", "promotion")

# Where the spec came from. Provenance in the plain sense: not who owns it, but
# how it got into the library, which is what a reader needs to judge it.
SOURCES = ("builder", "twin", "import", "bundled")


class LibraryError(ValueError):
    """A save the library refuses: an invalid spec, or a change with no reason."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "system").lower()).strip("-")
    return s[:48] or "system"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class Note:
    """Something somebody learned, attached to the system they learned it on.

    The half of a project that normally lives in a chat thread and is gone by
    the next one. ``kind`` separates the three that get read differently: a
    plain ``note``, a ``gotcha`` (the thing that cost someone an afternoon), and
    a ``result`` (what actually happened when it ran).
    """

    text: str
    author: str = ""
    kind: str = "note"  # note | gotcha | result
    at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "author": self.author, "kind": self.kind, "at": self.at}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Note":
        return cls(
            text=str(d.get("text", "")),
            author=str(d.get("author", "")),
            kind=str(d.get("kind", "note")),
            at=str(d.get("at") or _now()),
        )


@dataclass(frozen=True)
class Decision:
    """Why a number is the number it is.

    The most valuable row in the library and the one no export format has: a
    spec records that ``cooling_conductance_w_per_k`` is 0.35; only a decision
    records that it is 0.35 because the enclosure has no fan and the 0.5 default
    flattered the design.

    ``params`` binds the decision to the spec fields it justifies. It is what
    lets :func:`simura.library.diff.change_coverage` report a change nobody has
    explained, and it is filled in *by the diff* wherever a constructor here can
    compute it, rather than by hand.
    """

    question: str
    choice: str
    because: str
    params: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()
    """Options considered and turned down. Absent from every spec format there
    is, and the first thing the next person re-derives from scratch."""
    author: str = ""
    at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "choice": self.choice,
            "because": self.because,
            "params": list(self.params),
            "rejected": list(self.rejected),
            "author": self.author,
            "at": self.at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Decision":
        return cls(
            question=str(d.get("question", "")),
            choice=str(d.get("choice", "")),
            because=str(d.get("because", "")),
            params=tuple(str(p) for p in d.get("params", ())),
            rejected=tuple(str(r) for r in d.get("rejected", ())),
            author=str(d.get("author", "")),
            at=str(d.get("at") or _now()),
        )


@dataclass(frozen=True)
class Entry:
    """One saved system: the spec, its provenance, and the context around it."""

    entry_id: str
    name: str
    spec: dict[str, Any]
    kind: str = "system"
    version: int = 1
    """Position in this entry's own revision chain. A fork starts a new chain at
    1; it does not inherit its parent's number, because it is not the next
    version of that design, it is a different design."""
    parent_id: str | None = None
    relation: str = "origin"
    source: str = "builder"
    source_system_id: str | None = None
    """The running system this was captured from, if it was captured rather than
    built -- so a reader can tell a design from a recording of one."""
    author: str = ""
    summary: str = ""
    tags: tuple[str, ...] = ()
    validated: bool = False
    """Set by a human who has checked this against something real. The library
    does not infer it; a spec that runs is not a spec that is right."""
    created_at: str = field(default_factory=_now)
    notes: tuple[Note, ...] = ()
    decisions: tuple[Decision, ...] = ()

    def system_spec(self) -> SystemSpec:
        """The spec as the builder's own object, ready to run."""
        return SystemSpec.from_dict(self.spec)

    def with_note(self, note: Note) -> "Entry":
        return replace(self, notes=self.notes + (note,))

    def with_decision(self, decision: Decision) -> "Entry":
        return replace(self, decisions=self.decisions + (decision,))

    def matches(self, query: str) -> bool:
        """Free-text search over the things a person would actually remember.

        Notes and decisions are searched too, which is the point: six months on,
        what you remember is "the one where the fan died", not the entry id.
        """
        q = query.strip().lower()
        if not q:
            return True
        hay = " ".join(
            [self.entry_id, self.name, self.summary, self.author, " ".join(self.tags)]
            + [n.text for n in self.notes]
            + [f"{d.question} {d.choice} {d.because}" for d in self.decisions]
        ).lower()
        return q in hay

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "name": self.name,
            "spec": self.spec,
            "kind": self.kind,
            "version": self.version,
            "parent_id": self.parent_id,
            "relation": self.relation,
            "source": self.source,
            "source_system_id": self.source_system_id,
            "author": self.author,
            "summary": self.summary,
            "tags": list(self.tags),
            "validated": self.validated,
            "created_at": self.created_at,
            "notes": [n.to_dict() for n in self.notes],
            "decisions": [d.to_dict() for d in self.decisions],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Entry":
        return cls(
            entry_id=str(d["entry_id"]),
            name=str(d.get("name") or d["entry_id"]),
            spec=dict(d.get("spec") or {}),
            kind=str(d.get("kind", "system")),
            version=int(d.get("version", 1)),
            parent_id=d.get("parent_id") or None,
            relation=str(d.get("relation", "origin")),
            source=str(d.get("source", "builder")),
            source_system_id=d.get("source_system_id") or None,
            author=str(d.get("author", "")),
            summary=str(d.get("summary", "")),
            tags=tuple(str(t) for t in d.get("tags", ())),
            validated=bool(d.get("validated", False)),
            created_at=str(d.get("created_at") or _now()),
            notes=tuple(Note.from_dict(n) for n in d.get("notes", ())),
            decisions=tuple(Decision.from_dict(x) for x in d.get("decisions", ())),
        )


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


def entry_id_for(
    name: str, spec: dict[str, Any], parent_id: str | None, kind: str, version: int
) -> str:
    """A readable slug plus a content hash -- the id *is* the content.

    Saving byte-identical content twice yields the same id, which is the right
    answer: that is not two entries, it is one. It also means an entry keeps its
    identity across an export and an import, so lineage survives leaving the
    database it was written in.
    """
    digest = hashlib.sha1(
        _canonical([name, spec, parent_id, kind, version]).encode("utf-8")
    ).hexdigest()[:8]
    return f"{_slug(name)}-{digest}"


# --------------------------------------------------------------------------
# Constructors -- the only supported ways to make an Entry
# --------------------------------------------------------------------------


def _check_spec(spec: dict[str, Any] | SystemSpec) -> dict[str, Any]:
    """Refuse to save a system that would not run.

    A library of specs that fail on load is worse than no library: the next
    person inherits a debugging session instead of a starting point.
    """
    obj = spec if isinstance(spec, SystemSpec) else SystemSpec.from_dict(spec)
    errors = validate_spec(obj)
    if errors:
        raise LibraryError("; ".join(errors))
    return obj.to_dict()


def new_entry(
    spec: dict[str, Any] | SystemSpec,
    *,
    name: str | None = None,
    entry_id: str | None = None,
    kind: str = "system",
    source: str = "builder",
    source_system_id: str | None = None,
    author: str = "",
    summary: str = "",
    tags: Iterable[str] = (),
    notes: Iterable[Note] = (),
    decisions: Iterable[Decision] = (),
    validated: bool = False,
    created_at: str | None = None,
) -> Entry:
    """A first entry: a system with no parent in the library."""
    if kind not in KINDS:
        raise LibraryError(f"kind must be one of {KINDS}")
    if source not in SOURCES:
        raise LibraryError(f"source must be one of {SOURCES}")
    body = _check_spec(spec)
    label = name or body.get("name") or body.get("system_id") or "system"
    return Entry(
        entry_id=entry_id or entry_id_for(label, body, None, kind, 1),
        name=label,
        spec=body,
        kind=kind,
        version=1,
        parent_id=None,
        relation="origin",
        source=source,
        source_system_id=source_system_id,
        author=author,
        summary=summary,
        tags=tuple(tags),
        validated=validated,
        created_at=created_at or _now(),
        notes=tuple(notes),
        decisions=tuple(decisions),
    )


def _reason_decision(
    changes: list[SpecChange],
    because: str,
    author: str,
    question: str,
    rejected: Iterable[str],
) -> Decision:
    """Turn a typed reason into a decision bound to the fields that moved.

    The binding is computed from the diff, so the reason is filed against
    exactly what changed rather than against whatever the author remembered to
    name. This join is what makes an unexplained change detectable at all.
    """
    return Decision(
        question=question,
        choice=summarize(changes) or "no change to the spec",
        because=because,
        params=tuple(dict.fromkeys(c.key for c in changes)),
        rejected=tuple(rejected),
        author=author,
    )


def revise(
    parent: Entry,
    spec: dict[str, Any] | SystemSpec,
    *,
    because: str,
    author: str = "",
    name: str | None = None,
    summary: str | None = None,
    tags: Iterable[str] | None = None,
    rejected: Iterable[str] = (),
    entry_id: str | None = None,
) -> Entry:
    """The next version of the same design. ``because`` is not optional.

    Use this when the system is still the same system; use :func:`fork` when it
    has become a different one. The distinction is the reader's, not the
    database's: a revision chain is a story about one design, and a fork is
    where a second story starts.
    """
    if not because.strip():
        raise LibraryError("a revision needs a reason: 'because' cannot be empty")
    body = _check_spec(spec)
    changes = diff_specs(parent.spec, body)
    label = name or parent.name
    version = parent.version + 1
    return Entry(
        entry_id=entry_id or entry_id_for(label, body, parent.entry_id, parent.kind, version),
        name=label,
        spec=body,
        kind=parent.kind,
        version=version,
        parent_id=parent.entry_id,
        relation="revision",
        source=parent.source,
        source_system_id=parent.source_system_id,
        author=author or parent.author,
        summary=parent.summary if summary is None else summary,
        tags=parent.tags if tags is None else tuple(tags),
        # A new version has not been checked yet, whatever the old one was.
        validated=False,
        notes=(),
        decisions=(
            _reason_decision(
                changes, because, author, f"Why v{version} of {label} differs", rejected
            ),
        ),
    )


def fork(
    parent: Entry,
    spec: dict[str, Any] | SystemSpec | None = None,
    *,
    name: str,
    because: str,
    author: str = "",
    summary: str = "",
    tags: Iterable[str] | None = None,
    rejected: Iterable[str] = (),
    entry_id: str | None = None,
) -> Entry:
    """Start project N+1 from project N. ``because`` is not optional.

    A fork with no spec change is allowed and is not a mistake: taking someone
    else's rack unchanged into a new project is exactly the reuse this component
    exists for, and a record of *that* is worth as much as a record of a change.
    """
    if not name.strip():
        raise LibraryError("a fork needs a name of its own")
    if not because.strip():
        raise LibraryError("a fork needs a reason: 'because' cannot be empty")
    body = _check_spec(spec if spec is not None else parent.spec)
    changes = diff_specs(parent.spec, body)
    return Entry(
        entry_id=entry_id or entry_id_for(name, body, parent.entry_id, "system", 1),
        name=name,
        spec=body,
        # A fork of a template is somebody's system, not a second template.
        kind="system",
        version=1,
        parent_id=parent.entry_id,
        relation="fork",
        source=parent.source if parent.source != "bundled" else "builder",
        author=author,
        summary=summary,
        tags=parent.tags if tags is None else tuple(tags),
        validated=False,
        decisions=(
            _reason_decision(
                changes, because, author, f"Why {name} was forked from {parent.name}", rejected
            ),
        ),
    )


def promote(
    entry: Entry,
    *,
    because: str,
    name: str | None = None,
    author: str = "",
    summary: str | None = None,
    tags: Iterable[str] | None = None,
    entry_id: str | None = None,
) -> Entry:
    """Promote a system into a template others start from.

    Promotion copies the notes and decisions forward, unlike a fork or a
    revision: a template's whole value is the accumulated context, and a
    starting point stripped of the reasons behind it is just a spec file again.
    """
    if not because.strip():
        raise LibraryError("promoting needs a reason: what makes this worth starting from?")
    label = name or entry.name
    return Entry(
        entry_id=entry_id or entry_id_for(label, entry.spec, entry.entry_id, "template", 1),
        name=label,
        spec=dict(entry.spec),
        kind="template",
        version=1,
        parent_id=entry.entry_id,
        relation="promotion",
        source=entry.source,
        source_system_id=entry.source_system_id,
        author=author or entry.author,
        summary=entry.summary if summary is None else summary,
        tags=entry.tags if tags is None else tuple(tags),
        validated=entry.validated,
        notes=entry.notes,
        decisions=entry.decisions
        + (
            Decision(
                question=f"Why {label} is a template",
                choice="promoted as a starting point",
                because=because,
                author=author,
            ),
        ),
    )
