"""A plan carried in the spec that references it.

Every other provider names a *file*, which is right when there is one and wrong
the moment a spec has to outlive it. Two callers make that unavoidable:

* **The browser.** Somebody uploads a model, the plan comes back, and the plan
  lives in the tab. There is no path on the server to point a spec at.
* **The library.** A saved system that referenced ``/models/block-a.ifc`` would
  break the first time that file moved, and would be meaningless on anybody
  else's machine — which is the exact failure :mod:`simura.library` exists to
  refuse. A recorded system has to still mean something in a year.

So a ``SystemSpec.space`` can carry the plan itself::

    {"type": "inline", "params": {"plan": {...}}, "space_id": "sp-plant"}

and the spec is self-contained: it runs on any machine, with no file, with the
twin core rebuilt from scratch.

**Send one room, not the building.** A spec only needs the room it is standing
in — that is all :func:`simura.space.couple.ambient_for` reads — and embedding a
forty-room plan in every rack would bloat every spec, every diff and every
library entry with geometry none of them use. :func:`one_room` cuts the plan
down to the room in question, which is a few hundred bytes.

The fidelity record comes along, unchanged. A room whose ceiling height was
assumed is still a room whose ceiling height was assumed six months later, in a
spec somebody else opened.
"""

from __future__ import annotations

from typing import Any

from ..plan import FloorPlan
from ..provider import PlanError


class InlinePlanProvider:
    """A plan given directly, as the document rather than as a path."""

    format = "inline"

    def __init__(self, plan: dict[str, Any] | FloorPlan | None = None, **_ignored: Any) -> None:
        if plan is None:
            raise PlanError("the 'inline' plan provider needs a 'plan' document")
        if isinstance(plan, FloorPlan):
            self._plan = plan
        elif isinstance(plan, dict):
            if "spaces" not in plan and "walls" not in plan:
                raise PlanError(
                    "the 'inline' plan provider was given something that is not a "
                    "floor plan (no 'spaces' and no 'walls')"
                )
            try:
                self._plan = FloorPlan.from_dict(plan)
            except (KeyError, TypeError, ValueError) as exc:
                raise PlanError(f"could not read the inline plan: {exc}") from None
        else:
            raise PlanError("'plan' must be a floor-plan document")

    def plan(self) -> FloorPlan:
        return self._plan


def one_room(plan: FloorPlan, space_id: str) -> dict[str, Any]:
    """The smallest plan that still answers "what is it like in this room?".

    Keeps the room, the level it is on, the georeference (so the weather join
    still works) and the fidelity record (so what was assumed about *this* room
    is still readable). Drops every other room, every wall and every opening,
    because nothing downstream of a `SystemSpec.space` reads them.
    """
    space = plan.space(space_id)
    if space is None:
        raise PlanError(f"no room '{space_id}' in this plan")
    level = plan.level(space.level_id)
    return {
        "id": plan.id,
        "name": plan.name,
        "source_units": plan.source_units,
        "georeference": plan.georeference.to_dict(),
        "levels": [level.to_dict()] if level else [],
        "spaces": [space.to_dict()],
        "walls": [],
        "openings": [],
        "fidelity": plan.fidelity.to_dict(),
    }
