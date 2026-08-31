"""A plan read back from the canonical JSON.

The round trip, and the reason the canonical form is worth having at all. Once a
model has been imported once, the expensive, lossy, vendor-shaped part is over --
what is left is a small JSON document that opens instantly, diffs cleanly, and
says exactly what the importer understood.

This is what the dashboard stores, what the 3D world extrudes, what a library
entry carries, and what somebody checks into a repository next to the system they
designed against it. The IFC file is the *provenance*; this is the artifact.

The fidelity record travels with it, unchanged, which is the whole point: a plan
loaded from JSON six months later still says which of its numbers were guesses.
Re-recording it as "read from JSON, nothing assumed" would be true about *this*
read and a lie about the plan, and it is the exact kind of laundering the
component exists to refuse.
"""

from __future__ import annotations

import json

from ..plan import FloorPlan
from ..provider import PlanError
from .file import FilePlanProvider


class JsonPlanProvider(FilePlanProvider):
    """A :class:`~simura.space.plan.FloorPlan` serialized by ``to_json``."""

    format = "json"

    def _parse(self, log) -> FloorPlan:  # noqa: ANN001 - log type is FidelityLog
        try:
            payload = json.loads(self.text())
        except json.JSONDecodeError as exc:
            raise PlanError(f"{self.name} is not valid JSON: {exc}") from None
        if not isinstance(payload, dict):
            raise PlanError(f"{self.name} is not a floor plan document")
        if "spaces" not in payload and "walls" not in payload:
            raise PlanError(
                f"{self.name} has neither 'spaces' nor 'walls' — it is not a floor plan"
            )
        plan = FloorPlan.from_dict(payload)
        # The source hash is the *file we just read*, which for a re-saved plan is
        # not the model it originally came from. Keep the recorded provenance and
        # let the plan's own id do the identifying.
        return plan
