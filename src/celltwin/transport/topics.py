"""MQTT topic conventions.

Topics are namespaced by system id so one broker can carry a whole fleet:

    celltwin/telemetry/{system_id}   # one message per timestep (QoS 1)
    celltwin/config/{system_id}      # retained topology/config, published once

Keeping these in one place means the publisher and the twin core can never drift
out of agreement on where messages live.
"""

from __future__ import annotations

TELEMETRY_PREFIX = "celltwin/telemetry"
CONFIG_PREFIX = "celltwin/config"
ANOMALY_PREFIX = "celltwin/anomaly"
ASSESSMENT_PREFIX = "celltwin/assessment"


def telemetry_topic(system_id: str) -> str:
    return f"{TELEMETRY_PREFIX}/{system_id}"


def telemetry_wildcard() -> str:
    return f"{TELEMETRY_PREFIX}/+"


def anomaly_topic(system_id: str) -> str:
    return f"{ANOMALY_PREFIX}/{system_id}"


def anomaly_wildcard() -> str:
    return f"{ANOMALY_PREFIX}/+"


def assessment_topic(system_id: str) -> str:
    return f"{ASSESSMENT_PREFIX}/{system_id}"


def assessment_wildcard() -> str:
    return f"{ASSESSMENT_PREFIX}/+"


def config_topic(system_id: str) -> str:
    return f"{CONFIG_PREFIX}/{system_id}"


def config_wildcard() -> str:
    return f"{CONFIG_PREFIX}/+"


def system_id_from_topic(topic: str) -> str:
    """Extract the system id from any celltwin topic (the last path segment)."""
    return topic.rsplit("/", 1)[-1]
