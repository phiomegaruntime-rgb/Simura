"""Analytics service: subscribes to telemetry, publishes anomaly + assessment.

For each telemetry frame it runs, per system:

* the :class:`AnomalyEngine` (Component 4) -> ``simura/anomaly/{id}``, and
* the :class:`AssessmentEngine` (Component 5: diagnosis + SoH + RUL + safety)
  -> ``simura/assessment/{id}``.

Doing both here means the diagnosis consumes the anomaly features on the *same*
frame, perfectly aligned. Like any real analytics service it consumes the public
telemetry stream and produces derived streams -- no special access.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import aiomqtt

from ..health import AssessmentEngine
from ..sim.telemetry import PackTelemetry
from ..transport import (
    anomaly_topic,
    assessment_topic,
    system_id_from_topic,
    telemetry_wildcard,
)
from .engine import AnomalyConfig, AnomalyEngine

log = logging.getLogger("simura.analytics")


@dataclass
class _Engines:
    anomaly: AnomalyEngine
    assessment: AssessmentEngine


async def run_detector(
    mqtt_host: str = "localhost",
    mqtt_port: int = 1883,
    reconnect_s: float = 3.0,
    config: AnomalyConfig | None = None,
) -> None:
    """Long-running analytics loop with automatic reconnect. Cancel to stop."""
    config = config or AnomalyConfig()
    engines: dict[str, _Engines] = {}  # per system; survives reconnects
    while True:
        try:
            async with aiomqtt.Client(hostname=mqtt_host, port=mqtt_port) as client:
                await client.subscribe(telemetry_wildcard())
                log.info("analytics connected to mqtt %s:%s", mqtt_host, mqtt_port)
                async for message in client.messages:
                    try:
                        env = json.loads(message.payload)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    system_id = env.get("system_id") or system_id_from_topic(str(message.topic))
                    tel_dict = env.get("telemetry")
                    if not tel_dict:
                        continue

                    eng = engines.get(system_id)
                    if eng is None:
                        eng = engines[system_id] = _Engines(AnomalyEngine(config), AssessmentEngine())

                    tel = PackTelemetry.from_dict(tel_dict)
                    anomaly = eng.anomaly.update(tel)
                    assessment = eng.assessment.update(tel, anomaly)

                    ts = env.get("timestamp") or datetime.now(timezone.utc).isoformat()
                    await client.publish(
                        anomaly_topic(system_id),
                        json.dumps({"system_id": system_id, "timestamp": ts, "anomaly": anomaly.to_dict()}),
                        qos=1,
                    )
                    await client.publish(
                        assessment_topic(system_id),
                        json.dumps({"system_id": system_id, "timestamp": ts, "assessment": assessment.to_dict()}),
                        qos=1,
                    )
        except aiomqtt.MqttError as err:
            log.warning("mqtt lost (%s); retrying in %.1fs", err, reconnect_s)
            await asyncio.sleep(reconnect_s)
        except asyncio.CancelledError:
            log.info("analytics cancelled")
            raise
