"""What the import could not read -- recorded, not swallowed.

This is the commitment this component is built on, and it exists because BIM
interoperability fails in a characteristic way. Every importer ever written meets
geometry it does not understand, units it has to guess at, and rooms with no
stated height. The ones that raise are useless -- a 40 MB model with one
unsupported swept solid in it is still a building somebody wants to light. So
every importer in practice *fills in*: it picks 2.7 m, it assumes millimetres, it
skips the entity and moves on.

That is the right behaviour. Doing it **silently** is not, because of what sits
downstream. A room whose ceiling height was assumed produces a room index, which
produces a utilisation factor, which produces a lux figure a person then designs
against -- and nothing anywhere on that chain says the first number was a guess.
The failure is not the guess. The failure is that the guess became indistinguishable
from a measurement one function call after it was made.

So an imported :class:`~simura.space.plan.FloorPlan` carries a :class:`Fidelity`
record, and it is not optional decoration:

* every value that was **inferred** rather than read names the field, the subject
  it belongs to, and the basis it came from;
* every entity that was **skipped** names its type, how many, and why;
* the counts say how much of the file was understood at all.

It is the same commitment the rest of Simura makes in its own vocabulary --
:mod:`simura.explain` attributes an explanation to the equation that produced it,
:mod:`simura.library` computes what changed rather than accepting a claim about
it -- applied to the one place a digital twin meets somebody else's file.

The rule for consumers is short: **a value you did not read is a value you must
label.** :meth:`Fidelity.inferred_fields` and ``Space.inferred`` make that a
lookup rather than an act of diligence.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

#: How a value in a plan came to be. Ordered worst-known to best-known.
PROVENANCE = ("missing", "default", "inferred", "read")


@dataclass(frozen=True)
class Inference:
    """One value the importer supplied because the file did not.

    ``basis`` is the sentence a person needs to decide whether to trust it --
    "storey elevation difference", "IFC default, no IfcUnitAssignment", "typical
    office ceiling". A basis of "default" with no further detail is allowed but
    discouraged: it is exactly the case where the reader most needs the why.
    """

    subject: str  # "space:3vB2..." / "plan" / "level:2" -- what it is about
    field: str  # "height_m", "units", "north_deg"
    value: Any
    basis: str
    provenance: str = "inferred"  # "inferred" (derived) or "default" (constant)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Skipped:
    """A class of thing in the file the importer did not turn into geometry."""

    entity: str  # "IfcAdvancedBrep", "DXF SPLINE"
    count: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Fidelity:
    """How completely a source file was understood.

    Frozen at the end of an import by :meth:`FidelityLog.freeze`. ``source_sha256``
    is what makes a plan traceable back to the exact bytes it came from -- so a
    re-import of a changed model is detectable as a *different* plan rather than
    quietly replacing the old one, and :mod:`simura.library` can diff the two.
    """

    source_format: str = ""
    source_name: str = ""
    source_sha256: str = ""
    entities_seen: int = 0
    entities_used: int = 0
    inferences: list[Inference] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """True when nothing was inferred and nothing was skipped.

        Rare and worth saying out loud when it happens: it means every number in
        the plan came out of the file.
        """
        return not self.inferences and not self.skipped

    @property
    def coverage(self) -> float:
        """Fraction of the entities the importer looked at that it used, 0..1."""
        if self.entities_seen <= 0:
            return 0.0
        return min(1.0, self.entities_used / self.entities_seen)

    def inferred_fields(self, subject: str) -> dict[str, Inference]:
        """Every inferred field for one subject, keyed by field name."""
        return {i.field: i for i in self.inferences if i.subject == subject}

    def summary(self) -> str:
        """One sentence a UI can show without formatting anything itself."""
        if self.complete:
            return (
                f"Read {self.entities_used} of {self.entities_seen} entities "
                f"from {self.source_name or self.source_format}; nothing was assumed."
            )
        parts = [
            f"Read {self.entities_used} of {self.entities_seen} entities "
            f"from {self.source_name or self.source_format}"
        ]
        if self.inferences:
            parts.append(f"{len(self.inferences)} value(s) assumed")
        if self.skipped:
            total = sum(s.count for s in self.skipped)
            parts.append(f"{total} entity(ies) skipped in {len(self.skipped)} class(es)")
        return "; ".join(parts) + "."

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_format": self.source_format,
            "source_name": self.source_name,
            "source_sha256": self.source_sha256,
            "entities_seen": self.entities_seen,
            "entities_used": self.entities_used,
            "coverage": round(self.coverage, 4),
            "complete": self.complete,
            "inferences": [i.to_dict() for i in self.inferences],
            "skipped": [s.to_dict() for s in self.skipped],
            "warnings": list(self.warnings),
            "summary": self.summary(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Fidelity":
        return cls(
            source_format=str(d.get("source_format", "")),
            source_name=str(d.get("source_name", "")),
            source_sha256=str(d.get("source_sha256", "")),
            entities_seen=int(d.get("entities_seen", 0)),
            entities_used=int(d.get("entities_used", 0)),
            inferences=[Inference(**i) for i in d.get("inferences", [])],
            skipped=[Skipped(**s) for s in d.get("skipped", [])],
            warnings=list(d.get("warnings", [])),
        )


class FidelityLog:
    """The mutable builder an importer writes into as it parses.

    Kept separate from :class:`Fidelity` so the finished record is a value: once a
    plan exists, what the import did is history and nothing downstream can quietly
    append to it.
    """

    def __init__(self, source_format: str, source_name: str = "") -> None:
        self.source_format = source_format
        self.source_name = source_name
        self.source_sha256 = ""
        self._seen = 0
        self._used = 0
        self._inferences: list[Inference] = []
        self._skipped: dict[tuple[str, str], int] = {}
        self._warnings: list[str] = []

    # -- counting ---------------------------------------------------------
    def seen(self, n: int = 1) -> None:
        """Count entities the importer looked at."""
        self._seen += n

    def used(self, n: int = 1) -> None:
        """Count entities that became part of the plan."""
        self._used += n

    # -- recording --------------------------------------------------------
    def infer(self, subject: str, field_name: str, value: Any, basis: str) -> Any:
        """Record a value derived from something else in the file, and return it.

        Returning the value is what makes this hard to forget at a call site::

            height = log.infer(sid, "height_m", storey_gap, "storey elevation difference")
        """
        self._inferences.append(
            Inference(subject=subject, field=field_name, value=value, basis=basis)
        )
        return value

    def default(self, subject: str, field_name: str, value: Any, basis: str) -> Any:
        """Record a value that came from a constant, not from the file, and return it."""
        self._inferences.append(
            Inference(
                subject=subject,
                field=field_name,
                value=value,
                basis=basis,
                provenance="default",
            )
        )
        return value

    def skip(self, entity: str, reason: str, count: int = 1) -> None:
        """Record an entity class the importer did not understand."""
        key = (entity, reason)
        self._skipped[key] = self._skipped.get(key, 0) + count

    def warn(self, message: str) -> None:
        """Something the reader should know that is not tied to one entity."""
        if message not in self._warnings:
            self._warnings.append(message)

    def hash_bytes(self, data: bytes) -> str:
        """Fingerprint the source bytes, so a plan can name the file it came from."""
        self.source_sha256 = hashlib.sha256(data).hexdigest()
        return self.source_sha256

    def hash_file(self, path: str | Path) -> str:
        """Fingerprint a source file without holding it all in memory."""
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        self.source_sha256 = digest.hexdigest()
        return self.source_sha256

    def freeze(self) -> Fidelity:
        """The finished, immutable record."""
        return Fidelity(
            source_format=self.source_format,
            source_name=self.source_name,
            source_sha256=self.source_sha256,
            entities_seen=self._seen,
            entities_used=self._used,
            inferences=list(self._inferences),
            skipped=[
                Skipped(entity=k[0], reason=k[1], count=v)
                for k, v in sorted(self._skipped.items())
            ],
            warnings=list(self._warnings),
        )
