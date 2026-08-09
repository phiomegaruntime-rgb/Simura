"""MQTT topic conventions.

Topics are namespaced by system id so one broker can carry a whole fleet:

    simura/telemetry/{system_id}   # one message per timestep (QoS 1)
    simura/config/{system_id}      # retained topology/config, published once

Keeping these in one place means the publisher and the twin core can never drift
out of agreement on where messages live.
"""

from __future__ import annotations

TELEMETRY_PREFIX = "simura/telemetry"
CONFIG_PREFIX = "simura/config"
ANOMALY_PREFIX = "simura/anomaly"
ASSESSMENT_PREFIX = "simura/assessment"


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
    """Extract the system id from any simura topic (the last path segment)."""
    return topic.rsplit("/", 1)[-1]
