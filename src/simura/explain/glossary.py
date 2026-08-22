"""The glossary: every word the dashboard shows that a newcomer would not know.

This is the smallest and most-used part of the "get familiar" layer. A model
card is something you go and read; a glossary entry is something that appears
under your cursor while you are doing something else, and it has to land in one
sentence with no follow-up.

Two rules the entries are written to:

1. **Say the thing, then say why it matters.** "Ampacity is the current a cable
   can carry continuously" is a definition. "…because above it the insulation
   cooks" is the reason anyone asked.
2. **Point at the card.** Every entry names the model card that goes further, so
   a tooltip is a doorway rather than a dead end.

Terms are matched case-insensitively, and the plural and adjective forms people
actually type are carried as aliases — a glossary that only answers to its own
preferred spelling is a glossary nobody hits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GlossaryEntry:
    term: str
    short: str
    """One sentence: what it is and why it matters."""
    card: str | None = None
    aliases: tuple[str, ...] = ()
    unit: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "term": self.term,
            "short": self.short,
            "card": self.card,
            "aliases": list(self.aliases),
            "unit": self.unit,
        }


GLOSSARY: tuple[GlossaryEntry, ...] = (
    # -- batteries ---------------------------------------------------------
    GlossaryEntry(
        term="state of charge",
        short="How full the battery is, from 0 (empty) to 1 (full) — the fuel "
        "gauge, and the thing voltage alone can only sometimes tell you.",
        card="battery.ocv",
        aliases=("soc",),
    ),
    GlossaryEntry(
        term="open-circuit voltage",
        short="The voltage a cell settles at with nothing connected; its "
        "relationship to charge level is the chemistry's fingerprint and the only "
        "route from a voltage you can measure to a charge you cannot.",
        card="battery.ocv",
        aliases=("ocv", "resting voltage"),
        unit="V",
    ),
    GlossaryEntry(
        term="internal resistance",
        short="The cell's own resistance to current — it costs you voltage the "
        "instant you draw current, and it is where most of the heat comes from.",
        card="battery.cell",
        aliases=("r0", "dcir", "ohmic resistance"),
        unit="Ω",
    ),
    GlossaryEntry(
        term="polarisation",
        short="The slow half of a cell's internal loss: voltage that keeps sagging "
        "for seconds after the load is applied and keeps recovering after it "
        "stops.",
        card="battery.cell",
        aliases=("polarization", "v_rc", "rc branch"),
        unit="V",
    ),
    GlossaryEntry(
        term="voltage imbalance",
        short="The gap between the highest and lowest cell voltage — capacity you "
        "own and cannot reach, and usually the first number to move when one cell "
        "starts misbehaving.",
        card="battery.imbalance",
        aliases=("imbalance", "cell spread"),
        unit="V",
    ),
    GlossaryEntry(
        term="state of health",
        short="How much of its original performance a cell still has, measured "
        "here by tracking how much its internal resistance has grown.",
        card="twin.diagnosis",
        aliases=("soh",),
    ),
    GlossaryEntry(
        term="coulomb counting",
        short="Working out how full a battery is by adding up the current going in "
        "and out — reliable in the short term, and prone to drifting over the long "
        "one.",
        card="battery.cell",
    ),
    GlossaryEntry(
        term="thermal runaway",
        short="The failure where a cell's heating feeds itself: past a trigger "
        "temperature it makes heat faster than it can shed it, and there is no "
        "equilibrium left to reach.",
        card="battery.faults",
        aliases=("runaway",),
    ),
    GlossaryEntry(
        term="anomaly score",
        short="How far a cell has drifted from what its neighbours are doing, in "
        "standard deviations — it can be clearly abnormal while every absolute "
        "limit still reads healthy.",
        card="twin.anomaly",
        aliases=("z-score", "sigma"),
        unit="σ",
    ),
    GlossaryEntry(
        term="time to critical",
        short="How long, at the current heating rate, before a cell reaches its "
        "temperature limit. It assumes the next few minutes look like the last "
        "few.",
        card="twin.diagnosis",
        aliases=("rul", "remaining useful life"),
        unit="s",
    ),
    GlossaryEntry(
        term="C-rate",
        short="Current expressed as a multiple of the pack's capacity: 1C empties "
        "it in an hour, 2C in half an hour. It makes loads comparable between "
        "packs of different sizes.",
        card="battery.profile",
    ),
    # -- wires -------------------------------------------------------------
    GlossaryEntry(
        term="ampacity",
        short="The current a conductor can carry continuously — a thermal limit in "
        "disguise, set by the temperature its insulation can survive.",
        card="wires.ampacity",
        aliases=("current rating", "current-carrying capacity"),
        unit="A",
    ),
    GlossaryEntry(
        term="derating",
        short="Reducing a cable's allowed current because the conditions are worse "
        "than the ones it was rated in — most often because the surroundings are "
        "hot, which leaves less headroom before the insulation reaches its limit.",
        card="wires.ampacity",
    ),
    GlossaryEntry(
        term="voltage drop",
        short="Voltage lost in the cable instead of arriving at the load. On "
        "low-voltage systems it, rather than heat, is usually what decides the "
        "gauge.",
        card="wires.drop",
        unit="V",
    ),
    GlossaryEntry(
        term="AWG",
        short="American Wire Gauge, a size number that runs backwards — smaller "
        "number, thicker wire, and three sizes down roughly doubles the metal.",
        card="wires.resistance",
        aliases=("gauge", "wire gauge"),
    ),
    GlossaryEntry(
        term="resistivity",
        short="How strongly a material resists current, independent of its shape — "
        "the property that makes aluminium about 1.6× the resistance of copper for "
        "the same cross-section.",
        card="wires.resistance",
        aliases=("rho",),
        unit="Ω·m",
    ),
    GlossaryEntry(
        term="round trip",
        short="Counting both the outgoing and the returning conductor. Current has "
        "to come back, so a two-wire circuit pays its voltage drop twice.",
        card="wires.drop",
    ),
    # -- lights ------------------------------------------------------------
    GlossaryEntry(
        term="lumen",
        short="How much visible light a source makes in total — power weighted by "
        "how well the eye can actually see each wavelength.",
        card="lights.spectrum",
        aliases=("lumens", "luminous flux"),
        unit="lm",
    ),
    GlossaryEntry(
        term="lux",
        short="How much light lands on a surface — lumens per square metre. Lumens "
        "are what the lamp makes; lux is what reaches your desk.",
        card="lights.lumen_method",
        aliases=("illuminance",),
        unit="lx",
    ),
    GlossaryEntry(
        term="efficacy",
        short="Light per watt. The physical ceiling is 683 lm/W, and every real "
        "lamp is that number times what its spectrum, its radiant efficiency and "
        "its driver each give away.",
        card="lights.spectrum",
        aliases=("luminous efficacy", "lm/w"),
        unit="lm/W",
    ),
    GlossaryEntry(
        term="colour temperature",
        short="How warm or cool a white light looks, quoted as the temperature of "
        "the blackbody that would look the same — confusingly, higher numbers look "
        "colder.",
        card="lights.spectrum",
        aliases=("color temperature", "cct", "kelvin"),
        unit="K",
    ),
    GlossaryEntry(
        term="colour rendering index",
        short="How faithfully a lamp shows colours compared with a reference of the "
        "same colour temperature. A source can be very efficient and still make "
        "everything look wrong.",
        card="lights.spectrum",
        aliases=("cri", "ra", "color rendering index"),
    ),
    GlossaryEntry(
        term="utilisation factor",
        short="The share of a luminaire's light that actually lands on the working "
        "plane rather than the walls — a property of the room, not of the fitting.",
        card="lights.lumen_method",
        aliases=("utilization factor", "uf"),
    ),
    GlossaryEntry(
        term="light loss factor",
        short="What is left after lamps have dimmed with age, dirt has settled on "
        "the fittings, and some lamps have failed. Lighting is designed for the end "
        "of the maintenance cycle, not for day one.",
        card="lights.lumen_method",
        aliases=("llf", "maintenance factor"),
    ),
    GlossaryEntry(
        term="uniformity",
        short="The dimmest point divided by the average. A room can hit its target "
        "on average and still be unpleasant, and this is the number that catches "
        "it.",
        card="lights.field",
        aliases=("u0", "uniformity ratio"),
    ),
    GlossaryEntry(
        term="lumen maintenance",
        short="The fraction of its original light a lamp still produces after a "
        "given number of hours.",
        card="lights.lamp",
        aliases=("lumen depreciation", "l70"),
    ),
    GlossaryEntry(
        term="spectral power distribution",
        short="How a source's radiated power is spread across wavelengths. "
        "Everything else about a light — brightness, colour, rendering — is "
        "computed from it.",
        card="lights.spectrum",
        aliases=("spd", "spectrum"),
    ),
    GlossaryEntry(
        term="candela",
        short="How concentrated a light is in one direction. The same lumens in a "
        "narrower beam are more candela, which is the difference between a "
        "spotlight and a room light.",
        card="lights.field",
        aliases=("luminous intensity", "cd"),
        unit="cd",
    ),
    # -- the twin ----------------------------------------------------------
    GlossaryEntry(
        term="digital twin",
        short="A live model of a real system, running alongside it and fed by its "
        "data, so you can ask questions of the model that you cannot safely ask of "
        "the thing.",
        card="twin.diagnosis",
        aliases=("twin",),
    ),
    GlossaryEntry(
        term="telemetry",
        short="The stream of measurements a system emits. In Simura it is a fixed "
        "contract, so a simulated pack and a real one look identical to everything "
        "downstream.",
        card="twin.anomaly",
    ),
    GlossaryEntry(
        term="fault injection",
        short="Deliberately breaking a simulated system to see what it does. Every "
        "fault here works by changing a term the model already had, so the "
        "consequences come out of the physics rather than being scripted.",
        card="battery.faults",
    ),
    GlossaryEntry(
        term="attribution",
        short="Splitting an outcome into the terms of the equation that produced "
        "it, ranked by how much each one actually contributed. Every explanation "
        "in Simura is one of these.",
        card=None,
    ),
    GlossaryEntry(
        term="validation",
        short="Checking the model against measurements it has never been shown — "
        "published data, a standard, or the live sky. It is what separates a "
        "simulation from an animation.",
        card=None,
    ),
)

_LOOKUP: dict[str, GlossaryEntry] = {}
for _e in GLOSSARY:
    _LOOKUP[_e.term.lower()] = _e
    for _a in _e.aliases:
        _LOOKUP[_a.lower()] = _e


def list_terms() -> list[GlossaryEntry]:
    """Every entry, alphabetically — aliases collapsed into their entry."""
    return sorted(GLOSSARY, key=lambda e: e.term.lower())


def define(term: str) -> GlossaryEntry | None:
    """Look up a term or any of its aliases. ``None`` rather than raising, because
    the caller is usually a tooltip and a missing word is not an error."""
    return _LOOKUP.get(term.strip().lower())
