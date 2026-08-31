"""Every building source, behind one interface.

Each of these answers :meth:`~simura.space.provider.PlanProvider.plan` and nothing
else, so a hand-written rectangle and a 200 MB IFC model are interchangeable at
every call site. See :mod:`simura.space.config` for turning a plain
``{"type": ...}`` dict into one of them.
"""

from .dxf import DxfProvider
from .file import FilePlanProvider
from .gbxml import GbxmlProvider
from .ifc import IfcProvider
from .ifc_full import IfcFullProvider, available as ifc_full_available
from .inline import InlinePlanProvider, one_room
from .json_plan import JsonPlanProvider
from .rect import RectangleProvider

__all__ = [
    "DxfProvider",
    "FilePlanProvider",
    "GbxmlProvider",
    "IfcProvider",
    "IfcFullProvider",
    "InlinePlanProvider",
    "one_room",
    "JsonPlanProvider",
    "RectangleProvider",
    "ifc_full_available",
]
