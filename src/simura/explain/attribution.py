"""The attribution core: what an explanation *is* in Simura.

An explanation here is never a stored sentence about what usually happens. It is
a **decomposition of the model's own governing equation, evaluated at the
operating point in front of you**, with the terms ranked by how much they
actually contributed. The prose that a reader eventually sees
(:mod:`simura.explain.narrate`) is assembled from that ranking, so it cannot
disagree with the physics: change a coefficient and the sentence changes with it.

**Physics comes in exactly two shapes, so this module has exactly two
decompositions.**

*Things that add.* A heat balance (``Q_ohmic + Q_polarisation + Q_fault -
Q_cooling``), a split-flux illuminance field (``E_direct + E_interreflected``),
a terminal-voltage law (``OCV - I*R0 - V_rc``). The terms carry the quantity's
own unit, they sum to the outcome, and the interesting cases are the ones where
they *cancel* -- a pack that is holding steady is not a pack with nothing
happening. Handled by :func:`additive`.

*Things that multiply.* A conductor's resistance (``rho(T) * L / A``), a
lumen-method illuminance (``N * flux * UF * LLF / A``). No term has the
outcome's unit; each is a factor that scales it. Shares come from the logarithm,
which is the only measure of "how much did this factor move the answer" that
does not depend on the order the factors are written in. Handled by
:func:`multiplicative`.

Everything downstream -- the battery, wire and lighting explainers, the domain
lenses, the three disclosure levels, the API -- consumes one of these two
shapes and nothing else.

Share convention
----------------
For an additive decomposition, ``share`` is ``|value| / sum(|value|)``: a term's
part of the **gross traffic**, not of the net result. This is deliberate. Net
shares are undefined when the outcome is near zero (the equilibrium case) and
explode either side of it; gross shares stay meaningful and say the true thing,
which is "cooling is 96% of what is going on here, and it is very nearly
winning". :attr:`Attribution.opposing` recovers the direction information that
the absolute value throws away.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Iterable, Sequence

# Terms below this fraction of the gross flow are real but not worth a sentence.
NEGLIGIBLE_SHARE = 0.01


@dataclass(frozen=True)
class Term:
    """One term of a decomposed equation, evaluated at the operating point."""

    key: str
    label: str
    """Plain-language name -- what a non-specialist would call this term."""
    value: float
    """Additive: the signed contribution, in the outcome's unit.
    Multiplicative: the factor itself (``1.0`` means "this changed nothing")."""
    unit: str
    symbol: str
    """The term as it appears in the model's equation, e.g. ``I^2*R0``."""
    why: str
    """One line: what this term physically is, for someone from another domain."""
    share: float = 0.0
    """Filled in by :func:`additive` / :func:`multiplicative`. 0..1."""

    @property
    def negligible(self) -> bool:
        return self.share < NEGLIGIBLE_SHARE

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "symbol": self.symbol,
            "why": self.why,
            "share": self.share,
            "negligible": self.negligible,
        }


@dataclass(frozen=True)
class Attribution:
    """A decomposed observable: the outcome, and the terms that produced it."""

    key: str
    label: str
    kind: str
    """``"additive"`` or ``"multiplicative"`` -- which of the two shapes this is."""
    total: float
    unit: str
    equation: str
    """The governing equation this decomposition came from, verbatim."""
    terms: tuple[Term, ...]
    """Ranked by contribution, largest first."""
    card: str | None = None
    """Id of the :mod:`~simura.explain.cards` entry documenting the model."""
    operating_point: dict[str, float] = None  # type: ignore[assignment]
    """The inputs this was evaluated at -- an explanation is only true *here*."""
    exact: bool = True
    """False when an input had to be inferred rather than read from the model
    (see :func:`simura.explain.battery.operating_point_from_frame`)."""
    caveat: str | None = None
    """Why it is not exact, when it isn't."""

    def __post_init__(self) -> None:
        if self.operating_point is None:
            object.__setattr__(self, "operating_point", {})

    @property
    def dominant(self) -> Term | None:
        """The term doing the most work. This is what a headline is built from."""
        return self.terms[0] if self.terms else None

    @property
    def significant(self) -> tuple[Term, ...]:
        """Terms worth a sentence -- always at least the dominant one."""
        keep = tuple(t for t in self.terms if not t.negligible)
        return keep or self.terms[:1]

    @property
    def opposing(self) -> tuple[Term, ...]:
        """Additive terms pushing against the net outcome.

        This is where the direction information lost to ``|value|`` comes back:
        it is what makes "warming, but cooling is nearly keeping up" sayable.
        """
        if self.kind != "additive" or not self.terms:
            return ()
        sign = 1.0 if self.total >= 0 else -1.0
        return tuple(t for t in self.terms if t.value * sign < 0 and t.value != 0.0)

    @property
    def balanced(self) -> bool:
        """True when the terms very nearly cancel -- an equilibrium, not a calm."""
        gross = sum(abs(t.value) for t in self.terms)
        return gross > 0 and abs(self.total) / gross < 0.05

    def term(self, key: str) -> Term | None:
        return next((t for t in self.terms if t.key == key), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "total": self.total,
            "unit": self.unit,
            "equation": self.equation,
            "card": self.card,
            "operating_point": dict(self.operating_point),
            "exact": self.exact,
            "caveat": self.caveat,
            "balanced": self.balanced,
            "dominant": self.dominant.key if self.dominant else None,
            "opposing": [t.key for t in self.opposing],
            "terms": [t.to_dict() for t in self.terms],
        }


def _ranked(terms: Iterable[Term], weights: Sequence[float]) -> tuple[Term, ...]:
    gross = sum(weights)
    scored = [
        replace(t, share=(w / gross) if gross > 0 else 0.0)
        for t, w in zip(terms, weights)
    ]
    scored.sort(key=lambda t: t.share, reverse=True)
    return tuple(scored)


def additive(
    key: str,
    label: str,
    unit: str,
    equation: str,
    terms: Sequence[Term],
    *,
    card: str | None = None,
    operating_point: dict[str, float] | None = None,
    exact: bool = True,
    caveat: str | None = None,
) -> Attribution:
    """Decompose an outcome that is the **sum** of its terms.

    ``total`` is computed from the terms rather than passed in, so an
    attribution that does not add up is a bug that shows immediately instead of
    a sentence that quietly disagrees with the number beside it.
    """
    weights = [abs(t.value) for t in terms]
    return Attribution(
        key=key,
        label=label,
        kind="additive",
        total=float(sum(t.value for t in terms)),
        unit=unit,
        equation=equation,
        terms=_ranked(terms, weights),
        card=card,
        operating_point=operating_point or {},
        exact=exact,
        caveat=caveat,
    )


def multiplicative(
    key: str,
    label: str,
    unit: str,
    equation: str,
    base: float,
    terms: Sequence[Term],
    *,
    card: str | None = None,
    operating_point: dict[str, float] | None = None,
    exact: bool = True,
    caveat: str | None = None,
) -> Attribution:
    """Decompose an outcome that is a **product** of factors times ``base``.

    Shares come from ``|ln factor|``. A factor of exactly 1.0 scores zero, a
    factor of 2 and a factor of 0.5 score the same (they move the answer equally
    far, in opposite directions), and the ranking does not change if the factors
    are multiplied in a different order -- none of which is true of any share
    measure taken in linear space.

    **A factor of zero takes the whole share.** The logarithm does not reach it,
    but the physics does: a zero factor annihilates the outcome, so it is not
    merely the largest contribution, it is the only one that matters. Reporting
    it by its (absent) logarithm would rank a burnt-out lamp's supply voltage
    above the fact that the lamp is burnt out. When several factors are zero
    they share it equally, since any one of them alone would have been enough.
    """
    total = float(base)
    for t in terms:
        total *= t.value

    annihilating = [i for i, t in enumerate(terms) if t.value <= 0]
    if annihilating:
        weights = [1.0 if i in annihilating else 0.0 for i in range(len(terms))]
        return Attribution(
            key=key,
            label=label,
            kind="multiplicative",
            total=total,
            unit=unit,
            equation=equation,
            terms=_ranked(terms, weights),
            card=card,
            operating_point=operating_point or {},
            exact=exact,
            caveat=caveat,
        )

    weights = [abs(math.log(t.value)) for t in terms]
    return Attribution(
        key=key,
        label=label,
        kind="multiplicative",
        total=total,
        unit=unit,
        equation=equation,
        terms=_ranked(terms, weights),
        card=card,
        operating_point=operating_point or {},
        exact=exact,
        caveat=caveat,
    )
