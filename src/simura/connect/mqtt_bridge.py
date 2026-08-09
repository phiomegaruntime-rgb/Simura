"""MQTT bridge connector -- adapt a BMS that already publishes MQTT in its own schema.

Many gateways speak MQTT but with a vendor-specific JSON layout. This connector
subscribes to that foreign topic, pulls the standard signals out via dotted
paths, and republishes the twin's envelope. No polling -- it reacts to whatever
cadence the device publishes at.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

import aiomqtt

from .base import Connector
from .frame import SourceFrame

log = logging.getLogger("simura.connect")


@dataclass
class MqttSource:
    topic: str                      # foreign topic to subscribe to
    cell_voltage_path: str          # dotted path to the per-cell voltage array
    cell_temp_path: str             # dotted path to the temperature array
    pack_current_path: str          # dotted path to pack current
    pack_soc_path: Optional[str] = None


def _dig(payload: Any, path: str) -> Any:
    node = payload
    for key in path.split("."):
        if isinstance(node, list):
            node = node[int(key)]
        else:
            node = node[key]
    return node


class MqttBridgeConnector(Connector):
    source_kind = "mqtt"

    def __init__(self, *args, source: MqttSource, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.source = source

    def _extract(self, payload: dict) -> Optional[SourceFrame]:
        try:
            scalars: dict[str, float] = {"pack_current": float(_dig(payload, self.source.pack_current_path))}
            if self.source.pack_soc_path:
                scalars["pack_soc"] = float(_dig(payload, self.source.pack_soc_path))
            arrays = {
                "cell_voltage": [float(v) for v in _dig(payload, self.source.cell_voltage_path)],
                "cell_temp": [float(t) for t in _dig(payload, self.source.cell_temp_path)],
            }
            return SourceFrame(scalars=scalars, arrays=arrays)
        except (KeyError, IndexError, TypeError, ValueError) as err:
            log.warning("could not map foreign payload: %s", err)
            return None

    async def run(self) -> None:
        import asyncio

        while True:
            try:
                async with aiomqtt.Client(hostname=self.mqtt_host, port=self.mqtt_port) as client:
                    await client.subscribe(self.source.topic)
                    await self._publish_config(client)
                    log.info("mqtt bridge '%s' subscribed to '%s'", self.system_id, self.source.topic)
                    async for message in client.messages:
                        try:
                            payload = json.loads(message.payload)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        frame = self._extract(payload)
                        if frame is not None:
                            await self._publish_telemetry(client, self.decode(frame))
            except aiomqtt.MqttError as err:
                log.warning("mqtt lost (%s); retrying in %.1fs", err, self.reconnect_s)
                await asyncio.sleep(self.reconnect_s)
            except asyncio.CancelledError:
                raise
