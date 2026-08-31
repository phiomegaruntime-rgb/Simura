"""The line between what a system *is* and where it is being run.

A :class:`~simura.builder.spec.SystemSpec` mixes two different things. Most of it
is the design -- chemistry, topology, cell parameters, the numbers somebody
argued about. A few fields are not: they describe *this run of it*, and they
belong to whoever is running it rather than to whoever designed it.

    weather      what the sky over it is doing
    space        which building, and which room in it, it is standing in
    profile      what is being drawn out of it
    duration_s   how long this particular run lasts

The 3D sandbox is the caller that makes this unavoidable. A rack placed in the
world sits in the world's weather and powers the world's cables, so running a
saved design there *must* override those three. Without a rule, one of two bad
things happens: either the library refuses to be used from the world at all, or
every rack captured back out of it reports "weather source none → synthetic" as
a design change somebody has to justify -- which buries the changes that matter
under noise from where the thing happened to be standing.

So the rule is stated once, here, and both directions read it:

**The library records the design; the caller supplies the site.** A caller
declares which site fields it owns, :func:`apply_site` puts its values on top of
the design when the system starts, and :func:`restore_site` takes them back off
before the diff when the system is saved. A field the caller owns is one the
library will not record as a change, because the caller changing it says nothing
about the design.

The allowlist is deliberately short and closed. "Everything is site" would let a
caller launder an arbitrary rewrite of somebody's design through provenance that
claims it came from them.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..builder.spec import SystemSpec

SITE_FIELDS: tuple[str, ...] = ("weather", "space", "profile", "duration_s")
"""The only spec fields a caller may claim as its own. See the module docstring.

``space`` was added when floor plans arrived, and it belongs here for exactly the
reason the list exists. A room is *where a system is standing* in the most literal
sense the word has: the same rack design, put in a plant room and then in a yard,
is one design in two places. If ``space`` were part of the design, importing a
building and dropping a saved rack into one of its rooms would report "space:
none -> gbxml #412" as a change somebody has to justify -- burying whatever they
actually changed under a note about which room they walked into.

Adding to this list is not routine, and the bar is the one the docstring above
sets: a field belongs here only if a caller changing it says **nothing** about the
design. Ambient temperature, for instance, does *not* qualify and stays part of
the design, even though a room implies one -- which is why a room shields the
pack at build time rather than rewriting the spec's ``ambient_temp_c``.
"""


class SiteError(ValueError):
    """A caller claimed a field that is part of the design, not of the site."""


def check_site(fields: Iterable[str]) -> tuple[str, ...]:
    """Validate a caller's declared site fields, preserving their order."""
    declared = tuple(str(f) for f in fields)
    unknown = [f for f in declared if f not in SITE_FIELDS]
    if unknown:
        raise SiteError(
            f"{', '.join(unknown)} describe(s) the design, not the site; "
            f"only {', '.join(SITE_FIELDS)} can be supplied by a caller"
        )
    return declared


def apply_site(spec: dict[str, Any], site: dict[str, Any] | None) -> dict[str, Any]:
    """The design, standing where the caller put it.

    Returns a new dict; the stored entry is never mutated. Keys with a ``None``
    value are ignored, so a caller can send the same body whether or not it has
    a weather source to declare.
    """
    out = dict(spec)
    if not site:
        return out
    supplied = {k: v for k, v in site.items() if v is not None}
    check_site(supplied)
    out.update(supplied)
    return out


def restore_site(
    spec: dict[str, Any], parent: dict[str, Any] | None, fields: Iterable[str]
) -> dict[str, Any]:
    """Take the caller's site back off a spec before it is recorded as a design.

    The values come from the ``parent`` entry when there is one -- so a system
    captured back out of the world differs from the design it came from by what
    somebody *did* to it, never by where it was standing. With no parent there
    is nothing to restore *to*, so the fields fall back to the builder's own
    defaults: a design captured out of a sandbox should not arrive claiming that
    sandbox's weather is part of what it is.
    """
    declared = check_site(fields)
    if not declared:
        return dict(spec)
    source = parent if parent is not None else SystemSpec().to_dict()
    out = dict(spec)
    for field in declared:
        if field in source:
            out[field] = source[field]
    return out
