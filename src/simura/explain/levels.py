"""Disclosure levels: one attribution, three depths.

Progressive disclosure fails when it is implemented as three separately written
texts, because they drift and then two of them are wrong. Here the three depths
are three *renderings of one computation* — same terms, same numbers, different
amount of the machinery shown:

* **overview** — what is happening and whether it is fine. One sentence, the
  dominant term named in plain words, no symbols and no equation. This is what a
  newcomer meets on arrival.
* **working** — what is happening, what is causing it, and by how much. The
  significant terms with their values and shares. Enough to act on, and enough
  to argue with.
* **physics** — the governing equation, every term including the negligible
  ones, the operating point it was evaluated at, and the model card's
  assumptions and limits. Nothing is hidden at this level, including how much
  the model does not know.

The rule the levels enforce is that **depth adds, never contradicts**: every
number visible at ``overview`` is still there at ``physics``, unrounded. A
reader who clicks deeper must never discover that the simple version was a
different claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

LEVELS: tuple[str, ...] = ("overview", "working", "physics")

DEFAULT_LEVEL = "overview"


@dataclass(frozen=True)
class Level:
    key: str
    label: str
    who: str
    shows: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "who": self.who,
            "shows": list(self.shows),
        }


LEVEL_INFO: tuple[Level, ...] = (
    Level(
        key="overview",
        label="Overview",
        who="Anyone, on arrival.",
        shows=("what is happening", "whether it is fine", "the one cause that matters"),
    ),
    Level(
        key="working",
        label="Working",
        who="Someone who has to decide something.",
        shows=("every cause that matters", "how much each contributes", "the numbers"),
    ),
    Level(
        key="physics",
        label="Physics",
        who="Someone who wants to check the model, or does this for a living.",
        shows=(
            "the governing equation",
            "every term, including negligible ones",
            "the operating point",
            "assumptions and limits",
        ),
    ),
)

_INDEX = {lv: i for i, lv in enumerate(LEVELS)}


def get_level(key: str | None) -> str:
    if key is None:
        return DEFAULT_LEVEL
    if key not in _INDEX:
        raise KeyError(f"unknown level {key!r}; expected one of {list(LEVELS)}")
    return key


def at_least(level: str, minimum: str) -> bool:
    """True when ``level`` is ``minimum`` or deeper. The guard every renderer uses."""
    return _INDEX[get_level(level)] >= _INDEX[minimum]


def deeper(level: str) -> str | None:
    """The next level down, or ``None`` at the bottom. Backs the 'more' affordance."""
    i = _INDEX[get_level(level)]
    return LEVELS[i + 1] if i + 1 < len(LEVELS) else None
