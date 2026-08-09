"""MQTT ingest loop: the bridge from transport into the twin.

Subscribes to telemetry and config topics for the whole fleet, persists each
frame to TimescaleDB, updates the live-state cache, and fans out to WebSocket
subscribers. Runs as a background task for the FastAPI app's lifetime and
reconnects on its own if the broker blips.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import aiomqtt

from ..transport import (
    anomaly_wildcard,
    assessment_wildcard,
    config_wildcard,
    system_id_from_topic,
    telemetry_wildcard,
)
from .settings import Settings
from .state import LatestState, WebSocketManager
from .store import TimescaleStore

log = logging.getLogger("simura.ingest")


def _parse_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        ts = datetime.fromisoformat(value)
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


async def _handle_config(store: TimescaleStore, topic: str, payload: dict) -> None:
    system_id = payload.get("system_id") or system_id_from_topic(topic)
    await store.upsert_system(system_id, payload.get("name"), payload.get("config"))
    log.info("registered system %s", system_id)


async def _handle_telemetry(
    store: TimescaleStore,
    state: LatestState,
    ws: WebSocketManager,
    seen: set[str],
    topic: str,
    payload: dict,
) -> None:
    system_id = payload.get("system_id") or system_id_from_topic(topic)
    tel = payload.get("telemetry", {})
    ts = _parse_timestamp(payload.get("timestamp"))

    # Ensure the system exists even if no config message arrived first.
    if system_id not in seen:
        await store.upsert_system(system_id, payload.get("name"), None)
        seen.add(system_id)

    await store.insert_pack(system_id, ts, tel)
    await store.insert_cells(system_id, ts, tel.get("cells", []))
    state.update(system_id, payload)
    await ws.broadcast(system_id, payload)


async def _handle_anomaly(
    store: TimescaleStore,
    anomaly_state: LatestState,
    ws: WebSocketManager,
    topic: str,
    payload: dict,
) -> None:
    system_id = payload.get("system_id") or system_id_from_topic(topic)
    report = payload.get("anomaly", {})
    ts = _parse_timestamp(payload.get("timestamp"))
    await store.insert_anomaly_summary(system_id, ts, report)
    anomaly_state.update(system_id, payload)
    await ws.broadcast(system_id, payload)


async def _handle_assessment(
    store: TimescaleStore,
    assessment_state: LatestState,
    ws: WebSocketManager,
    topic: str,
    payload: dict,
) -> None:
    system_id = payload.get("system_id") or system_id_from_topic(topic)
    report = payload.get("assessment", {})
    ts = _parse_timestamp(payload.get("timestamp"))
    await store.insert_assessment_summary(system_id, ts, report)
    assessment_state.update(system_id, payload)
    await ws.broadcast(system_id, payload)


async def run_ingest(
    settings: Settings,
    store: TimescaleStore,
    state: LatestState,
    anomaly_state: LatestState,
    assessment_state: LatestState,
    ws: WebSocketManager,
) -> None:
    """Long-running ingest loop with automatic reconnect. Cancel to stop."""
    seen_systems: set[str] = set()
    while True:
        try:
            async with aiomqtt.Client(
                hostname=settings.mqtt_host, port=settings.mqtt_port
            ) as client:
                await client.subscribe(telemetry_wildcard())
                await client.subscribe(config_wildcard())
                await client.subscribe(anomaly_wildcard())
                await client.subscribe(assessment_wildcard())
                log.info("ingest connected to mqtt %s:%s", settings.mqtt_host, settings.mqtt_port)
                async for message in client.messages:
                    topic = str(message.topic)
                    try:
                        payload = json.loads(message.payload)
                    except (json.JSONDecodeError, TypeError):
                        log.warning("dropping non-JSON message on %s", topic)
                        continue
                    if topic.startswith("simura/config/"):
                        await _handle_config(store, topic, payload)
                    elif topic.startswith("simura/anomaly/"):
                        await _handle_anomaly(store, anomaly_state, ws, topic, payload)
                    elif topic.startswith("simura/assessment/"):
                        await _handle_assessment(store, assessment_state, ws, topic, payload)
                    else:
                        await _handle_telemetry(
                            store, state, ws, seen_systems, topic, payload
                        )
        except aiomqtt.MqttError as err:
            log.warning("mqtt connection lost (%s); retrying in %.1fs", err, settings.mqtt_reconnect_s)
            await asyncio.sleep(settings.mqtt_reconnect_s)
        except asyncio.CancelledError:
            log.info("ingest loop cancelled")
            raise
