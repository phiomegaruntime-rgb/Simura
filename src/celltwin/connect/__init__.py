"""Hardware connectors: bring real BMS data into the twin over industrial protocols.

Every connector produces the same telemetry envelope as the simulator, so the
twin core, analytics, and dashboard work on real data unchanged.
"""

from .base import Connector, PollingConnector
from .decode import build_telemetry
from .frame import DeviceMapping, SourceFrame

__all__ = [
    "Connector",
    "PollingConnector",
    "build_telemetry",
    "DeviceMapping",
    "SourceFrame",
]
