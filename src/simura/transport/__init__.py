"""Transport layer: how telemetry moves from an asset to the twin.

MQTT is the lingua franca of industrial IoT, so it is the default transport. The
same envelope format is what a real BMS gateway would publish, which is what lets
the twin core treat the simulator and real hardware identically.
"""

from .topics import (
    ANOMALY_PREFIX,
    ASSESSMENT_PREFIX,
    CONFIG_PREFIX,
    TELEMETRY_PREFIX,
    anomaly_topic,
    anomaly_wildcard,
    assessment_topic,
    assessment_wildcard,
    config_topic,
    config_wildcard,
    system_id_from_topic,
    telemetry_topic,
    telemetry_wildcard,
)

__all__ = [
    "TELEMETRY_PREFIX",
    "CONFIG_PREFIX",
    "ANOMALY_PREFIX",
    "ASSESSMENT_PREFIX",
    "telemetry_topic",
    "telemetry_wildcard",
    "config_topic",
    "config_wildcard",
    "anomaly_topic",
    "anomaly_wildcard",
    "assessment_topic",
    "assessment_wildcard",
    "system_id_from_topic",
]
