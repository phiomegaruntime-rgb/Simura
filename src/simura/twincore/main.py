"""FastAPI application factory and lifespan wiring for the twin core.

Run with:  uvicorn simura.twincore.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import logging

from contextlib import asynccontextmanager

import aiomqtt
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..builder import SystemSpec
from .api import router, ws_router
from .auth import require_api_key
from .ingest import run_ingest
from .settings import get_settings
from .simctl import SimManager
from .state import LatestState, WebSocketManager
from .store import TimescaleStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("simura.twincore")


async def _connect_publisher(settings) -> aiomqtt.Client:
    """Open a long-lived MQTT client for the SimManager, retrying while the broker
    comes up (mosquitto may still be starting under docker compose)."""
    last_err: Exception | None = None
    for _ in range(settings.db_connect_retries):
        client = aiomqtt.Client(hostname=settings.mqtt_host, port=settings.mqtt_port)
        try:
            await client.__aenter__()
            return client
        except aiomqtt.MqttError as err:
            last_err = err
            await asyncio.sleep(settings.mqtt_reconnect_s)
    raise RuntimeError("SimManager could not connect to MQTT") from last_err


async def _restore_simulations(store: TimescaleStore, sim_manager: SimManager) -> None:
    """Recreate persisted simulations on startup; start those meant to be running."""
    for s in await store.list_systems():
        if s.get("source") != "simulation" or not s.get("spec"):
            continue
        try:
            spec = SystemSpec.from_dict(s["spec"])
            sim_manager.create(spec)
            if s.get("run_state") == "running":
                await sim_manager.start(spec.system_id)
                log.info("restored running simulation %s", spec.system_id)
        except Exception:  # a bad stored spec must not block startup
            log.exception("could not restore simulation %s", s.get("system_id"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    store = TimescaleStore(settings.database_url, settings.db_min_pool, settings.db_max_pool)
    await store.connect(settings.db_connect_retries, settings.db_connect_retry_s)
    await store.init_schema()
    log.info("connected to database and ensured schema")

    live = LatestState()
    anomaly_live = LatestState()
    assessment_live = LatestState()
    ws_manager = WebSocketManager()

    pub_client = await _connect_publisher(settings)

    async def publish(topic: str, payload: str, retain: bool = False) -> None:
        await pub_client.publish(topic, payload, qos=1, retain=retain)

    sim_manager = SimManager(publish, default_speed=settings.sim_default_speed)

    app.state.settings = settings
    app.state.store = store
    app.state.live = live
    app.state.anomaly_live = anomaly_live
    app.state.assessment_live = assessment_live
    app.state.ws_manager = ws_manager
    app.state.sim_manager = sim_manager

    ingest_task = asyncio.create_task(
        run_ingest(settings, store, live, anomaly_live, assessment_live, ws_manager)
    )
    await _restore_simulations(store, sim_manager)
    log.info("twin core ready")
    try:
        yield
    finally:
        await sim_manager.close()
        ingest_task.cancel()
        try:
            await ingest_task
        except asyncio.CancelledError:
            pass
        try:
            await pub_client.__aexit__(None, None, None)
        except Exception:
            pass
        await store.close()
        log.info("twin core shut down")


app = FastAPI(
    title="Simura Twin Core",
    description="Ingests BESS telemetry over MQTT, persists to TimescaleDB, and "
    "serves the live twin (single-system + whole-fleet) over REST + WebSocket.",
    version="0.17.0",
    lifespan=lifespan,
)
_origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Unauthenticated liveness probe (open even when an API key is set)."""
    return {"status": "ok"}


# REST requires the API key when one is configured (no-op otherwise); the
# WebSocket router self-guards inside its handler.
app.include_router(router, dependencies=[Depends(require_api_key)])
app.include_router(ws_router)
