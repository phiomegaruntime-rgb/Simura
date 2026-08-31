"""The provider interface every building source implements.

A :class:`PlanProvider` answers one question -- "what does this building look
like?" -- via :meth:`plan`. Keeping the contract this small is what makes a
hand-typed rectangle, a saved JSON plan, an IFC model and a DXF export
interchangeable, and it means every consumer depends only on the protocol, never
on a concrete source. The shape is lifted straight from
:class:`simura.weather.provider.WeatherProvider`, which has proved it.

The one difference from the weather contract is the missing argument. Weather is
asked *at a time*, because weather varies with time and that is the whole of what
it does. A building does not: it varies with **storey**, which is a dimension of
the plan itself rather than a query parameter, so :meth:`plan` takes nothing and
:meth:`FloorPlan.spaces_on` does the selecting. Adding a ``level`` argument here
would push the choice into every provider and let two of them disagree about what
"the ground floor" means.

Providers are expected to be **cheap to call twice**. Parsing a 200 MB IFC file is
not, so a provider that reads a file caches the parsed plan and returns the same
object -- see :class:`simura.space.providers.file.FilePlanProvider`, which every
file-backed importer inherits that behaviour from.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .plan import FloorPlan


@runtime_checkable
class PlanProvider(Protocol):
    """Anything that can produce a :class:`~simura.space.plan.FloorPlan`."""

    def plan(self) -> FloorPlan:
        """Return the building's floor plan, in metres."""
        ...


class PlanError(ValueError):
    """A source file could not be read as a building.

    Raised only when there is **no plan at all** to return -- an unreadable file,
    a format the importer does not recognise, a model with no spaces and no walls
    in it. Anything less than that is not an error: it is a gap, and gaps are
    recorded in the plan's :class:`~simura.space.fidelity.Fidelity` record and
    returned along with whatever *was* understood. A 40 MB model with one
    unsupported solid in it is still a building somebody wants to light.
    """
