"""Domain lenses: the same model, said in your field's words.

The mission is *get familiar with a simulation without becoming an expert in all
of it*. That cannot mean one simplified rendering for everybody — a safety lead
and a lighting designer are not both "non-experts", they are experts in
different things, and each one needs the *other* domain translated, not their
own dumbed down.

So a lens is not a difficulty setting. It is a choice of vocabulary and of
priority:

* **vocabulary** — the words this reader already owns. "State of charge" is
  jargon to an electrician and plain speech to a battery engineer; "ampacity" is
  the reverse. Substitution runs longest-phrase-first so multi-word terms win
  over the single words inside them.
* **priority** — which attributions this reader wants first. Given the same
  running pack, operations wants to know whether it will level off, safety wants
  the margin, and a battery engineer wants the terminal-voltage split. Same
  computation, different order and different headline.

Depth is orthogonal and lives in :mod:`simura.explain.levels`. A domain expert
reading their own field wants *more* depth, not less, which is why the two knobs
have to be separate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Domain:
    """One reader's field, as a vocabulary and a set of priorities."""

    key: str
    label: str
    who: str
    """Who this lens is for, in one line — shown in the picker."""
    cares_about: tuple[str, ...] = ()
    """Attribution keys, most wanted first. Anything not listed still appears,
    after these, in its own natural order."""
    vocabulary: dict[str, str] = field(default_factory=dict)
    """Canonical phrase -> this domain's phrase. Applied to rendered prose."""
    power_unit: str = "W"
    """Domains that think in kW get kW."""
    home_component: str | None = None
    """The component this reader is native to, if any. Used to decide whether to
    offer a translation at all — you do not translate a field into itself."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "who": self.who,
            "cares_about": list(self.cares_about),
            "vocabulary": dict(self.vocabulary),
            "power_unit": self.power_unit,
            "home_component": self.home_component,
        }


DOMAINS: tuple[Domain, ...] = (
    Domain(
        key="newcomer",
        label="Newcomer",
        who="Someone who has never run a simulation and wants to know what is "
        "happening and whether it is fine.",
        cares_about=(
            "cell.heat_balance", "wire.heat_balance", "lamp.output", "room.illuminance",
        ),
        # Plainer *words*, not definitions. A replacement is dropped into the
        # middle of prose that was written with the canonical term in it, so
        # "ampacity" -> "the current this cable can safely carry" reads fine
        # alone and turns "Rated ampacity" into nonsense. The full gloss belongs
        # in the glossary, which is what the tooltip beside the word is for.
        vocabulary={
            "state of charge": "charge level",
            "voltage imbalance": "uneven cell voltages",
            "internal resistance": "built-in resistance",
            "polarisation": "slow internal loss",
            "ohmic heating": "heat from resistance",
            "steady state": "settled state",
            "ampacity": "safe current",
            "voltage drop": "lost voltage",
            "illuminance": "light level",
            "luminous flux": "light output",
            "utilisation factor": "usable share",
            "light loss factor": "surviving share",
            "efficacy": "light per watt",
        },
    ),
    Domain(
        key="battery",
        label="Battery engineer",
        who="Cells, packs, and electro-thermal behaviour.",
        home_component="batteries",
        cares_about=(
            "cell.voltage_sag",
            "cell.heat_balance",
            "pack.imbalance",
            "cell.charge_rate",
        ),
    ),
    Domain(
        key="thermal",
        label="Thermal engineer",
        who="Heat in, heat out, and where it settles — in any of the three "
        "components.",
        cares_about=("cell.heat_balance", "wire.heat_balance", "cell.voltage_sag"),
        vocabulary={
            "cooling conductance": "thermal conductance to ambient",
            "thermal mass": "thermal capacitance",
            "the cell": "the node",
            "ohmic heating": "Joule dissipation",
        },
    ),
    Domain(
        key="safety",
        label="Safety lead",
        who="Margins, alarms, and how long there is before something has to "
        "happen.",
        cares_about=("cell.heat_balance", "pack.imbalance", "wire.ampacity_margin"),
        vocabulary={
            "steady state": "settling temperature",
            "heat balance": "thermal margin",
            "cooling": "heat removal",
        },
    ),
    Domain(
        key="operations",
        label="Operations",
        who="Is it healthy, is it doing its job, and does anyone need to go and "
        "look at it.",
        power_unit="kW",
        cares_about=(
            "cell.heat_balance", "pack.imbalance", "lamp.output", "room.illuminance",
        ),
        vocabulary={
            "state of charge": "charge level",
            "voltage imbalance": "pack balance",
            "cell": "module slot",
            "polarisation": "slow internal loss",
            "ohmic heating": "resistive heating",
            "attribution": "breakdown",
        },
    ),
    Domain(
        key="electrical",
        label="Electrician / electrical",
        who="Conductors, circuits, drop and ampacity.",
        home_component="wires",
        cares_about=(
            "wire.resistance",
            "wire.voltage_drop",
            "wire.ampacity_margin",
            "wire.heat_balance",
        ),
        vocabulary={
            "state of charge": "how full the battery is",
            "polarisation": "slow battery sag",
            "cell": "battery cell",
        },
    ),
    Domain(
        key="lighting",
        label="Lighting designer",
        who="Lux on the task, colour, uniformity and installed power.",
        home_component="lights",
        # Output before efficacy: a fitting that is underperforming is a
        # question ("why is it dim?"), and efficacy is a property.
        cares_about=(
            "lamp.output", "room.illuminance", "room.uniformity", "lamp.efficacy",
        ),
    ),
)

_BY_KEY = {d.key: d for d in DOMAINS}

DEFAULT_DOMAIN = "newcomer"


def list_domains() -> list[Domain]:
    return list(DOMAINS)


def get_domain(key: str | None) -> Domain:
    """Look up a lens, falling back to the newcomer lens for ``None``."""
    if key is None:
        return _BY_KEY[DEFAULT_DOMAIN]
    try:
        return _BY_KEY[key]
    except KeyError:
        raise KeyError(
            f"unknown domain {key!r}; expected one of {sorted(_BY_KEY)}"
        ) from None


def translate(text: str, domain: Domain) -> str:
    """Rewrite canonical prose into ``domain``'s vocabulary.

    Longest phrase first, so "voltage imbalance" is replaced as a phrase rather
    than having "voltage" substituted out from under it. Matching is
    case-insensitive but the replacement keeps the original's leading case, so a
    substitution at the start of a sentence still reads as a sentence.
    """
    if not domain.vocabulary:
        return text
    for canonical in sorted(domain.vocabulary, key=len, reverse=True):
        replacement = domain.vocabulary[canonical]

        def _sub(m: re.Match[str], _r: str = replacement) -> str:
            found = m.group(0)
            return _r[:1].upper() + _r[1:] if found[:1].isupper() else _r

        text = re.sub(re.escape(canonical), _sub, text, flags=re.IGNORECASE)
    return text


def rank_for(domain: Domain, keys: list[str]) -> list[str]:
    """Order attribution keys the way ``domain`` wants to read them.

    Anything the domain named comes first, in the order it named them; the rest
    follow in the order they were computed. Nothing is ever dropped — a lens
    changes what you see first, not what you are allowed to see.
    """
    wanted = [k for k in domain.cares_about if k in keys]
    rest = [k for k in keys if k not in wanted]
    return wanted + rest
