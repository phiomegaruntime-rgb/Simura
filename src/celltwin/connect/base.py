"""Connector base classes.

A connector reads a device and publishes the twin's telemetry envelope to
``celltwin/telemetry/{id}`` -- identical to what the simulator's publisher emits,
so the twin core cannot tell (and does not care) whether data came from a
simulator or real hardware. That indistinguishability is the whole point of
Component 6.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import aiomqtt

from ..transport import config_topic, telemetry_topic
from .decode import build_telemetry
from .frame import DeviceMapping, SourceFrame

log = logging.getLogger("celltwin.connect")


class Connector:
    """Common publishing logic; subclasses implement how the device is read."""

    source_kind = "unknown"

    def __init__(
        self,
        system_id: str,
        mapping: DeviceMapping,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        name: str | None = None,
        reconnect_s: float = 3.0,
    ) -> None:
        self.system_id = system_id
        self.mapping = mapping
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.name = name or f"{system_id} ({self.source_kind})"
        self.reconnect_s = reconnect_s

    def decode(self, frame: SourceFrame) -> "PackTelemetry":  # noqa: F821
        return build_telemetry(frame, self.mapping)

    async def _publish_config(self, client: aiomqtt.Client) -> None:
        payload = {
            "system_id": self.system_id,
            "name": self.name,
            "config": {
                "pack": {"series": self.mapping.series, "parallel": self.mapping.parallel},
                "source": {"protocol": self.source_kind},
            },
        }
        await client.publish(config_topic(self.system_id), json.dumps(payload), qos=1, retain=True)

    async def _publish_telemetry(self, client: aiomqtt.Client, tel: "PackTelemetry") -> None:  # noqa: F821
        env = {
            "system_id": self.system_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "telemetry": tel.to_dict(),
        }
        await client.publish(telemetry_topic(self.system_id), json.dumps(env), qos=1)

    async def run(self) -> None:
        raise NotImplementedError


class PollingConnector(Connector):
    """For request/response protocols (Modbus, OPC-UA): poll, decode, publish."""

    def __init__(self, *args, poll_interval_s: float = 1.0, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.poll_interval_s = poll_interval_s

    async def open(self) -> None:  # connect to the device
        ...

    async def close(self) -> None:
        ...

    async def read_frame(self) -> SourceFrame | None:  # one device read
        raise NotImplementedError

    async def run(self) -> None:
        while True:
            try:
                async with aiomqtt.Client(hostname=self.mqtt_host, port=self.mqtt_port) as client:
                    await self.open()
                    await self._publish_config(client)
                    log.info("connector '%s' publishing via %s", self.system_id, self.source_kind)
                    try:
                        while True:
                            frame = await self.read_frame()
                            if frame is not None:
                                await self._publish_telemetry(client, self.decode(frame))
                            await asyncio.sleep(self.poll_interval_s)
                    finally:
                        await self.close()
            except aiomqtt.MqttError as err:
                log.warning("mqtt lost (%s); retrying in %.1fs", err, self.reconnect_s)
                await asyncio.sleep(self.reconnect_s)
            except asyncio.CancelledError:
                await self.close()
                raise
