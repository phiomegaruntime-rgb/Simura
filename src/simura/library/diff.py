"""The diff: what changed between two systems, computed rather than remembered.

This is the half of the record nobody should have to type. Given two specs it
walks them field by field and reports the changes in the vocabulary Component 16
already established -- ``series`` is "Cells in series", and it comes with the
reason that parameter matters, straight off the model card. A change is a
sentence somebody can read without knowing the field names, and it is recomputed
on every read, so it cannot go stale the way a hand-written changelog does.

The join back to the reasons
----------------------------

:class:`~simura.library.record.Decision` carries the spec keys it justifies, so
:func:`explain_changes` can put each change next to the reason for it, and
:func:`change_coverage` can report the ones with no reason at all. That is the
same trick :func:`simura.explain.cards.coverage` plays on the model cards: the
gap between the record and the thing it describes is *reported*, not left for
somebody to notice six months later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from ..builder.spec import SystemSpec
from ..explain.cards import ParamCard, get_card

# Which model cards document which part of a spec. Scoped rather than searched,
# because a fault's ``series`` (which cell broke) and a pack's ``series`` (how
# many cells in a string) are different things with the same field name.
_CARDS_FOR_SCOPE: dict[str, tuple[str, ...]] = {
    "spec": ("battery.cell", "battery.pack", "battery.run"),
    "profile": ("battery.profile",),
    "fault": ("battery.faults",),
}

# Fields that are structure rather than settable numbers, so they carry no
# ParamCard of their own. Labelled here, in the one place a reader meets them.
# The model cards still supply the *why* for the two that select a sub-model:
# a profile's card is keyed by profile type, and a fault's by fault type, so the
# reason a switch matters comes from the card for the value switched *to*.
_STRUCTURAL_LABELS: dict[str, str] = {
    "profile.type": "Load profile",
    "weather.type": "Weather source",
    "fault.type": "Fault type",
    "fault.series": "Faulted module (series index)",
    "fault.parallel": "Faulted slot (parallel index)",
    "fault.start_s": "Fault starts at",
}

_STRUCTURAL_UNITS: dict[str, str] = {"fault.start_s": "s"}

# Unit read off a field name, for the parameters that live inside a profile's or
# a fault's ``params`` dict -- those are documented per *type* rather than per
# field, so there is no card to ask. Longest suffix wins.
_UNIT_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("_w_per_k", "W/K"),
    ("_j_per_k", "J/K"),
    ("_per_s", "/s"),
    ("_w_m2", "W/m²"),
    ("_ohm", "Ω"),
    ("_farad", "F"),
    ("_ah", "Ah"),
    ("_ms", "m/s"),
    ("_frac", ""),
    ("_c", "°C"),
    ("_s", "s"),
    ("_a", "A"),
    ("_v", "V"),
    ("_w", "W"),
)


@dataclass(frozen=True)
class SpecChange:
    """One field that differs between two specs."""

    path: str
    """Where it lives: ``series``, ``profile.params.charge_a``, ``faults[0].type``."""
    key: str
    """The leaf name, scoped for lookup: ``series``, ``charge_a``, ``fault.type``.
    This is what a :class:`~simura.library.record.Decision` binds to."""
    scope: str  # spec | profile | weather | fault
    label: str
    unit: str
    before: Any
    after: Any
    kind: str  # changed | added | removed
    why: str = ""
    """Why this parameter matters at all, taken from its model card. A diff that
    only says what moved leaves the reader to guess whether it mattered."""
    card: str = ""
    ratio: float | None = None
    """``after / before`` where both are non-zero numbers -- the size of the move,
    which is the part a reader judges rather than the absolute values."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "key": self.key,
            "scope": self.scope,
            "label": self.label,
            "unit": self.unit,
            "before": self.before,
            "after": self.after,
            "kind": self.kind,
            "why": self.why,
            "card": self.card,
            "ratio": self.ratio,
            "text": self.text(),
        }

    def short(self) -> str:
        """``Cells in series 12 → 16`` -- for a one-line summary."""
        if self.key == "fault":  # a whole fault, not one of its fields
            which = self.after if self.kind != "removed" else self.before
            return f"Fault {self.kind}: {_fault_text(which)}"
        if self.kind == "added":
            return f"{self.label} {_fmt(self.after, self.unit)} added"
        if self.kind == "removed":
            return f"{self.label} removed"
        return f"{self.label} {_fmt(self.before, self.unit)} → {_fmt(self.after, self.unit)}"

    def text(self) -> str:
        """The one-line rendering, with the size of the move where it applies."""
        base = self.short()
        if self.ratio is not None and self.ratio > 0 and abs(self.ratio - 1.0) > 1e-9:
            base += f" ({_pct(self.ratio)})"
        return base


# Card "units" that are really a note about the quantity's type. Printing them
# gives "12 count → 16 count", which reads worse than the bare number.
_UNPRINTABLE_UNITS = frozenset({"count", "fraction"})


def _fmt(value: Any, unit: str = "") -> str:
    if value is None:
        return "unset"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        text = f"{value:.6g}"
    elif isinstance(value, int):
        text = str(value)
    else:
        return str(value)
    return f"{text} {unit}".strip() if unit not in _UNPRINTABLE_UNITS else text


def _fault_text(fault: Any) -> str:
    """A whole fault as one phrase: what breaks, where, and when.

    Added and removed faults are reported as a unit rather than as four separate
    field changes, because "a short appeared at module 2" is the change somebody
    made and "start_s 600 added" is debris from how it is stored.
    """
    if not isinstance(fault, dict):
        return str(fault)
    kind = str(fault.get("type", "fault")).replace("_", " ")
    where = f"module {fault.get('series', 0)} · slot {fault.get('parallel', 0)}"
    when = f"from {_fmt(fault.get('start_s'), 's')}"
    params = ", ".join(
        f"{_humanize(k)[0].lower()} {_fmt(v, _humanize(k)[1])}"
        for k, v in (fault.get("params") or {}).items()
    )
    return f"{kind} at {where}, {when}" + (f" ({params})" if params else "")


def _pct(ratio: float) -> str:
    delta = (ratio - 1.0) * 100.0
    sign = "+" if delta >= 0 else ""
    if abs(delta) >= 100.0:
        return f"{ratio:.3g}×"
    return f"{sign}{delta:.0f}%"


def _param_card(scope: str, key: str) -> ParamCard | None:
    for card_id in _CARDS_FOR_SCOPE.get(scope, ()):  # scoped, see above
        found = get_card(card_id).param(key)
        if found is not None:
            return found
    return None


def _humanize(key: str) -> tuple[str, str]:
    """A readable label and a guessed unit for a field with no card."""
    for suffix, unit in _UNIT_SUFFIXES:
        if key.endswith(suffix) and len(key) > len(suffix):
            return key[: -len(suffix)].replace("_", " ").capitalize(), unit
    return key.replace("_", " ").strip().capitalize(), ""


def _card_id_for(scope: str, key: str) -> str:
    return next(
        (c for c in _CARDS_FOR_SCOPE.get(scope, ()) if get_card(c).param(key) is not None), ""
    )


def _describe(scope: str, key: str, path: str, value: Any) -> tuple[str, str, str, str]:
    """(label, unit, why, card) for a field, from its model card where it has one."""
    param = _param_card(scope, key)
    if param is not None:
        return param.label, param.unit, param.why, _card_id_for(scope, key)

    structural = _STRUCTURAL_LABELS.get(key) or _STRUCTURAL_LABELS.get(path)
    if structural:
        # A profile or fault *type* is documented by the card entry for the type
        # itself, so switching to "cycle" borrows the cycle card's reasoning.
        chosen = _param_card(scope, value) if isinstance(value, str) else None
        return (
            structural,
            _STRUCTURAL_UNITS.get(key, ""),
            chosen.why if chosen else "",
            _card_id_for(scope, value) if chosen else "",
        )

    label, unit = _humanize(key)
    return label, unit, "", ""


# --------------------------------------------------------------------------
# Flattening
# --------------------------------------------------------------------------

# (path, scope, lookup key) for every leaf of a spec, in spec field order.
_Leaf = tuple[str, str, str, Any]


def _leaves(spec: dict[str, Any]) -> list[_Leaf]:
    out: list[_Leaf] = []
    for name, value in spec.items():
        if name == "profile" and isinstance(value, dict):
            out.append(("profile.type", "profile", "profile.type", value.get("type")))
            for k, v in (value.get("params") or {}).items():
                out.append((f"profile.params.{k}", "profile", k, v))
        elif name == "weather" and isinstance(value, dict):
            out.append(("weather.type", "weather", "weather.type", value.get("type")))
            for k, v in (value.get("params") or {}).items():
                out.append((f"weather.params.{k}", "weather", k, v))
        elif name == "faults" and isinstance(value, list):
            for i, fault in enumerate(value):
                if not isinstance(fault, dict):
                    continue
                # The fault as a whole, so adding or removing one reads as a
                # single change; its fields follow for the case where a fault
                # was tuned rather than added.
                out.append((f"faults[{i}]", "fault", "fault", fault))
                for k in ("type", "series", "parallel", "start_s"):
                    out.append((f"faults[{i}].{k}", "fault", f"fault.{k}", fault.get(k)))
                for k, v in (fault.get("params") or {}).items():
                    out.append((f"faults[{i}].params.{k}", "fault", k, v))
        else:
            out.append((name, "spec", name, value))
    return out


def _normalize(spec: dict[str, Any] | SystemSpec) -> dict[str, Any]:
    """Fill in the defaults before comparing.

    An omitted field *is* its default, so a partial spec from an API body and a
    complete one from the library compare as the same system when they are.
    """
    obj = spec if isinstance(spec, SystemSpec) else SystemSpec.from_dict(spec)
    return obj.to_dict()


# --------------------------------------------------------------------------
# The diff
# --------------------------------------------------------------------------


def diff_specs(
    before: dict[str, Any] | SystemSpec,
    after: dict[str, Any] | SystemSpec,
    *,
    ignore: Iterable[str] = ("system_id",),
) -> list[SpecChange]:
    """Every field that differs, in spec order, labelled from the model cards.

    ``system_id`` is ignored by default: two entries in a library necessarily
    carry different ids, and reporting that as a design change would bury the
    ones that are.
    """
    skip = set(ignore)
    left = {p: (s, k, v) for p, s, k, v in _leaves(_normalize(before))}
    right = {p: (s, k, v) for p, s, k, v in _leaves(_normalize(after))}

    # A fault present on one side only is reported once, as a fault; its fields
    # are suppressed so the diff says "a short appeared" rather than listing the
    # four columns that store one.
    whole = {p for p in set(left) ^ set(right) if p.startswith("faults[") and "." not in p}
    covered = tuple(f"{p}." for p in whole)

    changes: list[SpecChange] = []
    for path, (scope, key, new) in right.items():
        if path in skip or key in skip or path.startswith(covered):
            continue
        if path in left:
            old = left[path][2]
            if _same(old, new):
                continue
            if key == "fault":
                continue  # both sides have it; its fields carry the detail
            changes.append(_change(path, scope, key, old, new, "changed"))
        else:
            changes.append(_change(path, scope, key, None, new, "added"))

    for path, (scope, key, old) in left.items():
        if path in skip or key in skip or path in right or path.startswith(covered):
            continue
        changes.append(_change(path, scope, key, old, None, "removed"))

    return changes


def _same(old: Any, new: Any) -> bool:
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        if isinstance(old, bool) or isinstance(new, bool):
            return old is new
        return abs(float(old) - float(new)) <= 1e-12 * max(1.0, abs(float(old)))
    return old == new


def _change(path: str, scope: str, key: str, old: Any, new: Any, kind: str) -> SpecChange:
    label, unit, why, card = _describe(scope, key, path, new if new is not None else old)
    ratio = None
    if (
        isinstance(old, (int, float))
        and isinstance(new, (int, float))
        and not isinstance(old, bool)
        and not isinstance(new, bool)
        and old
    ):
        ratio = float(new) / float(old)
    return SpecChange(
        path=path,
        key=key,
        scope=scope,
        label=label,
        unit=unit,
        before=old,
        after=new,
        kind=kind,
        why=why,
        card=card,
        ratio=ratio,
    )


def summarize(changes: Sequence[SpecChange], limit: int = 3) -> str:
    """A one-line reading of a diff, for a list row or a decision's ``choice``."""
    if not changes:
        return ""
    head = ", ".join(c.short() for c in changes[:limit])
    extra = len(changes) - limit
    return f"{head}, and {extra} more" if extra > 0 else head


# --------------------------------------------------------------------------
# The join back to the reasons
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExplainedChange:
    """A change, and the decision that accounts for it -- or nothing."""

    change: SpecChange
    decision: Any = None  # record.Decision; untyped here to keep the import one-way

    def to_dict(self) -> dict[str, Any]:
        return {
            "change": self.change.to_dict(),
            "decision": self.decision.to_dict() if self.decision is not None else None,
        }


def explain_changes(changes: Sequence[SpecChange], decisions: Sequence[Any]) -> list[ExplainedChange]:
    """Pair each change with the most recent decision that binds to its field."""
    out: list[ExplainedChange] = []
    for change in changes:
        match = None
        for decision in decisions:
            params = set(getattr(decision, "params", ()) or ())
            if change.key in params or change.path in params:
                match = decision  # later decisions win: the newest reason is the live one
        out.append(ExplainedChange(change=change, decision=match))
    return out


def group_by_reason(paired: Sequence[ExplainedChange]) -> list[dict[str, Any]]:
    """Collect changes under the reason they share, in first-seen order.

    One decision usually covers several fields -- somebody moves the ambient and
    the cooling in the same breath, for the same reason -- and repeating that
    reason once per field turns a paragraph into a wall. Everything with no
    reason at all lands in one final group, which is the group worth reading.
    """
    groups: list[dict[str, Any]] = []
    seen: dict[int, dict[str, Any]] = {}
    for item in paired:
        marker = id(item.decision) if item.decision is not None else 0
        group = seen.get(marker)
        if group is None:
            group = {"decision": item.decision, "changes": []}
            seen[marker] = group
            groups.append(group)
        group["changes"].append(item.change)
    return groups


def change_coverage(changes: Sequence[SpecChange], decisions: Sequence[Any]) -> dict[str, Any]:
    """How much of this diff anybody actually wrote a reason for.

    The number that makes the record's own gaps visible. A fork made through
    :func:`~simura.library.record.fork` starts at complete, because the reason is
    bound to the diff at the moment it is typed; it stops being complete the
    moment somebody tunes a field afterwards and says nothing about it.
    """
    paired = explain_changes(changes, decisions)
    unexplained = [p.change for p in paired if p.decision is None]
    return {
        "total": len(changes),
        "explained": len(changes) - len(unexplained),
        "unexplained": [c.to_dict() for c in unexplained],
        "complete": not unexplained,
    }
