"""What a room is *for*, worked out from what the file called it.

Geometry alone cannot be simulated. A 24 m^2 rectangle is a cell office, a
two-bed ward, a substation or a store cupboard, and the four want wildly
different amounts of light, different ambient assumptions and different power
densities. The difference between an imported polygon and an imported *room* is
this one field.

Building models carry the answer, but never in one place and never in one form.
IFC has ``IfcSpace.PredefinedType`` (usually ``NOTDEFINED``), ``ObjectType``,
``LongName`` and ``Name``; gbXML has a proper ``spaceType`` enumeration from a
fixed list; DXF has a text label on a layer, if you are lucky. And underneath all
of them is a human-typed room name -- "Open Plan Office 2.04", "Buero", "Couloir
Nord", "PLANT RM 3" -- which is the field that is actually filled in.

So the classifier reads all of them, most-structured first, and falls back to
keyword matching on the name. Three commitments make that safe:

**It returns its basis.** Never just ``"office"`` -- always ``"office"`` *because*
``gbXML spaceType=OpenOffice`` or *because* ``name contains 'office'``. That
string goes into the plan's fidelity record, so a room lit to 500 lux on the
strength of a substring match is a room whose reader can see the substring.

**It refuses rather than guesses.** No match means ``unknown``, and the lighting
coupling declines to set a target for an unknown room instead of defaulting it to
an office. Defaulting is how a plant room ends up designed to 500 lux; refusing
is how somebody notices.

**Matching is on whole words.** ``"plant"`` must not match ``"Planting Store"``
and ``"lab"`` must not match ``"Elaborate Suite"``. Substring matching on short
words is exactly the failure the world module's inventory search already learned
about numbers -- so the same discipline applies here, on word boundaries.
"""

from __future__ import annotations

import re
from typing import Iterable

from .plan import OCCUPANCY

# Keyword -> occupancy, checked as whole words against the room's name, in the
# order listed. Order matters where a name can hit two: "drawing office" must be
# tested before "office", and "car park" before "park".
#
# The non-English entries are the ones that show up constantly in models exported
# from European practices; this is not an attempt at coverage, it is an attempt to
# stop the three or four most common ones landing as `unknown`.
NAME_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("drawing office", "drafting", "design office"), "drawing_office"),
    (("car park", "carpark", "parking", "garage", "tiefgarage"), "car_park"),
    (("operating theatre", "surgery", "theatre", "or suite"), "surgery"),
    (("sports hall", "gym", "gymnasium", "sporthalle"), "sports_hall"),
    (("warehouse", "aisle", "racking", "lager"), "warehouse_aisle"),
    (("inspection", "qc", "quality control", "metrology"), "inspection"),
    (("classroom", "lecture", "seminar", "teaching", "klassenzimmer", "salle de classe"), "classroom"),
    (("office", "buero", "büro", "bureau", "oficina", "workstation", "open plan"), "office"),
    (("corridor", "hallway", "passage", "circulation", "flur", "couloir", "lobby corridor"), "corridor"),
    (("lobby", "reception", "foyer", "atrium", "entrance", "empfang"), "lobby"),
    (("kitchen", "kitchenette", "pantry", "canteen", "kueche", "küche", "cuisine"), "kitchen"),
    (
        (
            "store",
            "storage",
            "stores",
            "cupboard",
            "archive",
            "plant",
            "plantroom",
            "plant room",
            "switch room",
            "switchroom",
            "substation",
            "riser",
            "comms",
            "server",
            "battery room",
            "ups",
            "lager",
            # Utility spaces. A laundry or a boiler room is not a store, but it
            # is lit and powered like one, and "storage" is the class this
            # vocabulary has for a room somebody works in briefly rather than
            # occupies. Naming them beats leaving them `unknown`, which is what
            # they were.
            "laundry",
            "utility",
            "boiler",
            "service room",
            "technical room",
            "waschraum",
            "heizraum",
        ),
        "storage",
    ),
    (("workshop", "works", "assembly", "production", "factory", "werkstatt", "atelier"), "workshop"),
    (
        ("apartment", "flat", "bedroom", "living", "dwelling", "lounge", "wohnung", "chambre"),
        "residential_general",
    ),
    (("wc", "toilet", "restroom", "bathroom", "shower", "sanitary"), "corridor"),
    (("stair", "stairwell", "lift", "elevator", "escalator", "treppe"), "corridor"),
)

# gbXML's `spaceType` is a closed enumeration, so this is a real mapping rather
# than a guess -- which is why it is consulted before the room's name.
GBXML_SPACE_TYPES: dict[str, str] = {
    "activestorage": "storage",
    "inactivestorage": "storage",
    "atrium": "lobby",
    "audience": "classroom",
    "classroom": "classroom",
    "computerroom": "office",
    "conferenceroom": "office",
    "corridor": "corridor",
    "dining": "kitchen",
    "electricalmechanical": "storage",
    "enclosedoffice": "office",
    "openoffice": "office",
    "exhibit": "lobby",
    "foodpreparation": "kitchen",
    "garage": "car_park",
    "gymnasium": "sports_hall",
    "hospital": "surgery",
    "hotel": "residential_general",
    "laboratory": "inspection",
    "library": "office",
    "lobby": "lobby",
    "lounge": "residential_general",
    "manufacturing": "workshop",
    "mechanical": "storage",
    "office": "office",
    "parking": "car_park",
    "restroom": "corridor",
    "retail": "lobby",
    "stairway": "corridor",
    "storage": "storage",
    "warehouse": "warehouse_aisle",
    "workshop": "workshop",
}

# IFC's `IfcSpace.PredefinedType` is a short enumeration and almost always
# NOTDEFINED, but when a model does set it, it is authoritative.
IFC_PREDEFINED_TYPES: dict[str, str] = {
    "parking": "car_park",
    "gfa": "unknown",  # a gross-floor-area space is a measurement, not a room
    "internal": "unknown",
    "external": "unknown",
    "space": "unknown",
    "notdefined": "unknown",
    "userdefined": "unknown",
}


class Classification(tuple):
    """``(occupancy, basis)`` -- what it is, and why we say so.

    A tuple subclass rather than a dataclass so it unpacks at every call site
    without ceremony, while still having names for readability.
    """

    __slots__ = ()

    def __new__(cls, occupancy: str, basis: str) -> "Classification":
        return super().__new__(cls, (occupancy, basis))

    @property
    def occupancy(self) -> str:
        return self[0]

    @property
    def basis(self) -> str:
        return self[1]

    @property
    def known(self) -> bool:
        return self[0] != "unknown"


def classify(
    name: str = "",
    *,
    gbxml_space_type: str = "",
    ifc_predefined_type: str = "",
    long_name: str = "",
    object_type: str = "",
) -> Classification:
    """Work out a room's occupancy from whatever the file provided.

    Sources are consulted most-structured first: a closed enumeration beats a
    typed name, and a typed name beats nothing. The returned ``basis`` names which
    one won, and it is what the caller records in the plan's fidelity log.
    """
    gb = _norm(gbxml_space_type)
    if gb and gb in GBXML_SPACE_TYPES:
        return Classification(
            GBXML_SPACE_TYPES[gb], f"gbXML spaceType '{gbxml_space_type}'"
        )

    ifc = _norm(ifc_predefined_type)
    if ifc and IFC_PREDEFINED_TYPES.get(ifc, "unknown") != "unknown":
        return Classification(
            IFC_PREDEFINED_TYPES[ifc], f"IfcSpace.PredefinedType '{ifc_predefined_type}'"
        )

    # LongName is the field IFC intends for the human room name and Name is often
    # just a number ("2.04"), so LongName is tried first where both exist.
    for label, source in (
        (long_name, "LongName"),
        (name, "name"),
        (object_type, "ObjectType"),
    ):
        if not label:
            continue
        hit = _match_keywords(label)
        if hit:
            occupancy, keyword = hit
            return Classification(occupancy, f"{source} '{label}' contains '{keyword}'")

    return Classification("unknown", "no space type, and no keyword in the name")


def _match_keywords(label: str) -> tuple[str, str] | None:
    text = _norm(label)
    if not text:
        return None
    for keywords, occupancy in NAME_KEYWORDS:
        for keyword in keywords:
            if _whole_word(keyword, text):
                return (occupancy, keyword)
    return None


def _whole_word(needle: str, haystack: str) -> bool:
    """Whole-word (or whole-phrase) containment, so 'lab' misses 'elaborate'."""
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


def _norm(text: str) -> str:
    """Lower-case, collapse punctuation and runs of whitespace to single spaces."""
    return re.sub(r"[\s_\-/\\.]+", " ", str(text or "").strip().lower()).strip()


def is_valid(occupancy: str) -> bool:
    """True when ``occupancy`` is one of the vocabulary the plan admits."""
    return occupancy in OCCUPANCY


def counts(occupancies: Iterable[str]) -> dict[str, int]:
    """How many rooms of each class -- the rollup a plan summary shows."""
    out: dict[str, int] = {}
    for o in occupancies:
        out[o] = out.get(o, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))
