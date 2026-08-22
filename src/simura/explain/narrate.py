"""Turning an attribution into something a person reads.

The division of labour here is strict, and it is what keeps the layer honest:

* **The physics decides what is said.** Which term leads, whether the outcome is
  rising or falling, whether it has settled, how much each cause is worth — all
  of that comes from the :class:`~simura.explain.attribution.Attribution`, which
  came from the model's own equation evaluated at the operating point.
* **This module only decides how to say it.** Which verb, which unit prefix,
  which of three depths, and which domain's vocabulary. Grammar, not claims.

That line matters because it is the only defence against the failure mode this
whole component exists to avoid: a plausible sentence that no longer matches the
model. There is no branch anywhere below on *what kind of situation this is*.
The nearest thing is :data:`PHRASING`, which supplies a subject noun and a pair
of direction verbs per quantity — and even there, which verb gets used is
decided by the sign of a computed number.

**Depth adds, never contradicts.** Every figure quoted at ``overview`` appears
again, unrounded, at ``physics``. A reader who clicks deeper finds more of the
same answer, never a different one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from .attribution import Attribution
from .cards import ModelCard, get_card
from .domains import Domain, get_domain, rank_for, translate
from .levels import at_least, deeper, get_level


@dataclass(frozen=True)
class Phrasing:
    """The grammar for one quantity: what to call it, and how it moves."""

    subject: str
    up: str
    down: str
    steady: str = "holding steady"
    signed: bool = True
    """False for quantities where the sign carries no meaning worth a verb."""
    settles_key: str = ""
    """An operating-point key naming *where* a balanced quantity settled. A heat
    balance at equilibrium nets to zero, which is true and useless on its own —
    the temperature it settled at is the answer the reader came for."""
    settles_unit: str = ""
    plural: bool = False
    """True when the subject is plural, so the copula agrees with it."""
    balance_note: bool = True
    """False for quantities where a near-zero total is simply a state, not two
    terms holding each other off. A heat balance at equilibrium is worth saying
    that way; a current margin of zero is just "at its rating"."""


PHRASING: dict[str, Phrasing] = {
    "cell.heat_balance": Phrasing(
        subject="this cell", up="warming up", down="cooling down",
        steady="holding its temperature",
        settles_key="temp_c", settles_unit="°C",
    ),
    "wire.heat_balance": Phrasing(
        subject="this cable run", up="warming up", down="cooling down",
        steady="holding its temperature",
        settles_key="temp_c", settles_unit="°C",
    ),
    "wire.resistance": Phrasing(
        subject="this run's resistance", up="", down="", signed=False,
    ),
    "wire.voltage_drop": Phrasing(
        subject="the voltage lost in this run", up="", down="", signed=False,
    ),
    "lamp.output": Phrasing(
        subject="this fitting's light output", up="", down="", signed=False,
    ),
    "lamp.efficacy": Phrasing(
        subject="this lamp's light per watt", up="", down="", signed=False,
    ),
    "room.illuminance": Phrasing(
        subject="the light reaching the working plane", up="", down="",
        signed=False,
    ),
    "cell.charge_rate": Phrasing(
        subject="this cell", up="charging", down="discharging", steady="at rest",
    ),
    "cell.voltage_sag": Phrasing(
        subject="this cell's voltage under load", up="sagging", down="lifted",
        steady="unloaded", signed=False,
    ),
    "pack.imbalance": Phrasing(
        subject="the pack's cells", up="drifting apart", down="drifting apart",
        steady="matched", signed=False, plural=True,
    ),
    "wire.ampacity_margin": Phrasing(
        subject="this cable run", up="within its rating", down="over its rating",
        steady="exactly at its rating", balance_note=False,
    ),
    "room.field_split": Phrasing(
        subject="this working plane", up="lit", down="lit", steady="lit",
        signed=False,
    ),
    "room.uniformity": Phrasing(
        subject="the dimmest part of this room", up="falling short of the average",
        down="falling short of the average", steady="as bright as the average",
        signed=False,
    ),
}

_GENERIC = Phrasing(subject="this quantity", up="rising", down="falling", signed=False)


@dataclass(frozen=True)
class Explanation:
    """One attribution, rendered for one reader at one depth."""

    key: str
    label: str
    headline: str
    """One sentence. True on its own, with nothing else on screen."""
    summary: str
    causes: tuple[str, ...] = ()
    """One sentence per significant cause. Empty at ``overview``."""
    value: str = ""
    equation: str = ""
    terms: tuple[dict[str, Any], ...] = ()
    operating_point: dict[str, float] = field(default_factory=dict)
    assumptions: tuple[str, ...] = ()
    limits: tuple[str, ...] = ()
    caveat: str | None = None
    card: str | None = None
    card_title: str = ""
    follow_ups: tuple[dict[str, str], ...] = ()
    """Where to go next: a question, and the card that answers it."""
    level: str = "overview"
    domain: str = "newcomer"
    next_level: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "headline": self.headline,
            "summary": self.summary,
            "causes": list(self.causes),
            "value": self.value,
            "equation": self.equation,
            "terms": [dict(t) for t in self.terms],
            "operating_point": dict(self.operating_point),
            "assumptions": list(self.assumptions),
            "limits": list(self.limits),
            "caveat": self.caveat,
            "card": self.card,
            "card_title": self.card_title,
            "follow_ups": [dict(f) for f in self.follow_ups],
            "level": self.level,
            "domain": self.domain,
            "next_level": self.next_level,
        }


# -- number formatting -----------------------------------------------------

_PREFIXES = ((1e6, "M"), (1e3, "k"), (1.0, ""), (1e-3, "m"), (1e-6, "µ"))

# Units that take an SI prefix. Photometric units are deliberately absent:
# lighting is quoted in plain lux and plain lumens at every magnitude, and
# neither "1.26 klux" nor "2.21 klm" is a thing anybody writes. Multiples,
# counts, temperatures and percent-per-hour take no prefix either.
_SCALABLE = {"W", "V", "A", "Ω", "J"}


def _fixed(value: float) -> str:
    """Three significant figures, never in scientific notation."""
    mag = abs(value)
    if mag >= 100:
        return f"{value:,.0f}"
    if mag >= 10:
        return f"{value:,.1f}"
    if mag >= 1:
        return f"{value:,.2f}"
    return f"{value:.3g}"


def quantity(value: float, unit: str, power_unit: str = "W") -> str:
    """Format a number the way a person would write it.

    Picks an SI prefix where the unit takes one so the mantissa lands in a
    readable range, honours a domain that thinks in kilowatts, and never prints
    more precision than the magnitude justifies.
    """
    if value != value or math.isinf(value):  # NaN / inf
        return "—"
    if unit == "×":
        return f"×{value:.3g}"

    mag = abs(value)
    if unit not in _SCALABLE:
        if mag and mag < 1e-6:
            return f"~0 {unit}".strip()
        return f"{_fixed(value)} {unit}".strip()

    # A domain that thinks in kilowatts still wants watts for a 15 W cell. The
    # preference is about the scale the reader works at, not a blanket rescale.
    if unit == "W" and power_unit == "kW" and mag >= 1000.0:
        return f"{_fixed(value / 1000.0)} kW"

    if mag == 0:
        return f"0 {unit}"
    if mag < 1e-6:
        return f"~0 {unit}"
    for scale, prefix in _PREFIXES:
        if mag >= scale:
            return f"{_fixed(value / scale)} {prefix}{unit}"
    return f"{_fixed(value)} {unit}"


def _mid_sentence(label: str) -> str:
    """A term label as it reads mid-sentence.

    Only the first character is lowered. Lowercasing the whole label turns
    "Supply voltage (207.0 V of 230 V)" into "...207.0 v of 230 v", which is not
    a unit anybody writes — and units routinely appear in a label, because a
    label that names its own operating point is more use than one that does not.
    """
    return label[:1].lower() + label[1:] if label else label


def _pct(share: float) -> str:
    if share >= 0.995:
        return "essentially all"
    if share < 0.005:
        return "under 1%"
    return f"{share * 100:.0f}%"


# -- rendering -------------------------------------------------------------


def _headline(a: Attribution, domain: Domain) -> str:
    ph = PHRASING.get(a.key, _GENERIC)
    dom = a.dominant
    # When the verb already carries the direction ("cooling down"), quoting a
    # signed number alongside it says the same thing twice and reads as a
    # contradiction: "discharging at −176 %/h". The magnitude is what belongs
    # next to a directional verb; the sign is still in `total` for anyone
    # reading the numbers.
    value = quantity(abs(a.total) if ph.signed else a.total, a.unit, domain.power_unit)
    # A single-cause outcome does not need "mostly because of" — there is no
    # "mostly" about it, and naming the only term adds nothing. This counts
    # *terms*, not significant ones: a decomposition whose other factors all came
    # out inert still has a cause worth naming, and a burnt-out lamp emphatically
    # does.
    lone = len(a.terms) < 2
    be = "are" if ph.plural else "is"

    if a.kind == "multiplicative":
        if dom is None or lone:
            return f"{ph.subject.capitalize()} comes out at {value}."
        return (
            f"{ph.subject.capitalize()} comes out at {value}, and "
            f"{_mid_sentence(dom.label)} is the biggest single factor in that."
        )

    if a.balanced and ph.signed:
        settled = a.operating_point.get(ph.settles_key) if ph.settles_key else None
        where = (
            f" at {quantity(settled, ph.settles_unit, domain.power_unit)}"
            if settled is not None
            else ""
        )
        lead = f"{ph.subject.capitalize()} {be} {ph.steady}{where}"
        if dom is not None and ph.balance_note:
            return (
                f"{lead} — {_mid_sentence(dom.label)} and the terms against it have "
                f"reached a balance."
            )
        return f"{lead}."

    if ph.signed:
        verb = ph.up if a.total >= 0 else ph.down
        lead = f"{ph.subject.capitalize()} {be} {verb} at {value} net"
    else:
        lead = f"{ph.subject.capitalize()} {be} {ph.up} by {value}"

    if dom is None or lone:
        return f"{lead}."
    return f"{lead}, mostly because of {_mid_sentence(dom.label)}."


def _summary(a: Attribution, domain: Domain) -> str:
    dom = a.dominant
    if dom is None:
        return ""
    unit_note = "of the total effect" if a.kind == "multiplicative" else "of what is going on"
    parts = [
        f"{dom.label} accounts for {_pct(dom.share)} {unit_note}"
        f" ({quantity(dom.value, dom.unit, domain.power_unit)}). {dom.why}"
    ]
    opposing = a.opposing
    if opposing:
        names = ", ".join(_mid_sentence(t.label) for t in opposing)
        parts.append(
            f"Pushing the other way: {names}, worth "
            f"{quantity(sum(t.value for t in opposing), a.unit, domain.power_unit)}."
        )
    return " ".join(parts)


def _causes(a: Attribution, domain: Domain) -> tuple[str, ...]:
    out = []
    for t in a.significant:
        out.append(
            f"{t.label} — {quantity(t.value, t.unit, domain.power_unit)}, "
            f"{_pct(t.share)}. {t.why}"
        )
    return tuple(out)


def _follow_ups(a: Attribution, card: ModelCard | None) -> tuple[dict[str, str], ...]:
    """Questions a reader is likely to have next, each with somewhere to go.

    Built from the attribution's own dominant term and the card's declared
    neighbours, so the trail through the docs follows the physics rather than a
    hand-drawn sitemap.
    """
    out: list[dict[str, str]] = []
    if card is not None:
        dom = a.dominant
        if dom is not None:
            out.append({"question": f"What is {_mid_sentence(dom.label)}?", "card": card.id})
        out.append({"question": f"How does {card.title.lower()} work?", "card": card.id})
        for other in card.see_also:
            try:
                out.append(
                    {"question": f"What about {get_card(other).title.lower()}?",
                     "card": other}
                )
            except KeyError:  # a see_also pointing nowhere is a docs bug, not a crash
                continue
    return tuple(out[:4])


def render(
    attribution: Attribution,
    domain: str | Domain | None = None,
    level: str | None = None,
) -> Explanation:
    """Render one attribution for one reader at one depth."""
    dom = domain if isinstance(domain, Domain) else get_domain(domain)
    lv = get_level(level)
    card = None
    if attribution.card:
        try:
            card = get_card(attribution.card)
        except KeyError:
            card = None

    headline = translate(_headline(attribution, dom), dom)
    summary = translate(_summary(attribution, dom), dom) if at_least(lv, "working") else ""
    causes = (
        tuple(translate(c, dom) for c in _causes(attribution, dom))
        if at_least(lv, "working")
        else ()
    )

    if at_least(lv, "physics"):
        # Everything, including the terms the ranking called negligible: at this
        # depth "too small to mention" is the reader's call, not the renderer's.
        terms = tuple(t.to_dict() for t in attribution.terms)
        equation = attribution.equation
        op = dict(attribution.operating_point)
        assumptions = card.assumptions if card else ()
        limits = card.limits if card else ()
    elif at_least(lv, "working"):
        terms = tuple(t.to_dict() for t in attribution.significant)
        equation = ""
        op = {}
        assumptions = ()
        limits = ()
    else:
        terms, equation, op, assumptions, limits = (), "", {}, (), ()

    # The caveat is not hidden at shallow levels — an inexact answer says so
    # wherever it is shown. Depth changes detail, never trustworthiness.
    return Explanation(
        key=attribution.key,
        label=translate(attribution.label, dom),
        headline=headline,
        summary=summary,
        causes=causes,
        value=quantity(attribution.total, attribution.unit, dom.power_unit),
        equation=equation,
        terms=terms,
        operating_point=op,
        assumptions=assumptions,
        limits=limits,
        caveat=attribution.caveat,
        card=card.id if card else None,
        card_title=card.title if card else "",
        follow_ups=_follow_ups(attribution, card) if at_least(lv, "working") else (),
        level=lv,
        domain=dom.key,
        next_level=deeper(lv),
    )


def render_all(
    attributions: Sequence[Attribution],
    domain: str | Domain | None = None,
    level: str | None = None,
) -> list[Explanation]:
    """Render several attributions, ordered the way this reader wants them.

    Nothing is dropped. A domain lens decides what comes first, never what is
    allowed to be seen — a reader who has been handed a partial picture cannot
    tell that they have.
    """
    dom = domain if isinstance(domain, Domain) else get_domain(domain)
    by_key = {a.key: a for a in attributions}
    order = rank_for(dom, [a.key for a in attributions])
    return [render(by_key[k], dom, level) for k in order]


def brief(attributions: Sequence[Attribution], domain: str | Domain | None = None) -> str:
    """The whole picture in one paragraph, at overview depth.

    What a landing page or a tooltip shows: every headline, in the reader's
    order, and nothing else.
    """
    return " ".join(e.headline for e in render_all(attributions, domain, "overview"))
