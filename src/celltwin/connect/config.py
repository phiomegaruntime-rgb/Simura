"""Load a connector from a YAML/JSON config file and build the right connector.

A config declares the protocol, the pack topology + unit scaling (``mapping``),
and the protocol-specific source (register map / node ids / topic + paths). This
is what an integrator edits to point CellTwin at a real device -- no code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import Connector
from .frame import DeviceMapping


def load_config(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    if str(path).endswith((".yaml", ".yml")):
        import yaml

        return yaml.safe_load(text)
    return json.loads(text)


def _mapping(cfg: dict) -> DeviceMapping:
    return DeviceMapping(**cfg["mapping"])


def build_connector(cfg: dict) -> Connector:
    protocol = cfg["protocol"]
    mapping = _mapping(cfg)
    mqtt = cfg.get("mqtt", {})
    common = dict(
        system_id=cfg["system_id"],
        mapping=mapping,
        mqtt_host=mqtt.get("host", "localhost"),
        mqtt_port=mqtt.get("port", 1883),
        name=cfg.get("name"),
    )
    src = cfg["source"]

    if protocol == "modbus":
        from .modbus import ModbusConnector, ModbusSource

        source = ModbusSource(**{k: v for k, v in src.items() if k not in ("host", "port")})
        return ModbusConnector(
            **common, host=src["host"], port=src.get("port", 502),
            source=source, poll_interval_s=cfg.get("poll_interval_s", 1.0),
        )

    if protocol == "opcua":
        from .opcua import OpcUaConnector, OpcUaSource

        source = OpcUaSource(**{k: v for k, v in src.items() if k != "url"})
        return OpcUaConnector(
            **common, url=src["url"], source=source,
            poll_interval_s=cfg.get("poll_interval_s", 1.0),
        )

    if protocol == "mqtt":
        from .mqtt_bridge import MqttBridgeConnector, MqttSource

        return MqttBridgeConnector(**common, source=MqttSource(**src))

    raise ValueError(f"unknown protocol '{protocol}' (modbus | opcua | mqtt)")
