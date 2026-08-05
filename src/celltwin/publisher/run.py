"""Simulator -> MQTT publisher.

Drives a Component-1 :class:`~celltwin.sim.simulator.Simulator` and publishes its
telemetry to MQTT, standing in for a real battery + BMS gateway. It first sends a
*retained* config message (so any twin core learns the topology, even if it joins
late), then one telemetry frame per timestep.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone

import aiomqtt

from ..builder import SystemSpec, build_pack_config, build_sim_config
from ..builder import build_simulator as build_simulator_from_spec
from ..sim import (
    ChargeDischargeCycle,
    InternalShort,
    PackConfig,
    SimConfig,
    Simulator,
    ThermalRunaway,
)
from ..transport import config_topic, telemetry_topic

log = logging.getLogger("celltwin.publisher")


def build_simulator(scenario: str) -> tuple[Simulator, PackConfig, SimConfig]:
    """Return a simulator for a named scenario, plus its config (for publishing)."""
    pack = PackConfig(series=12, parallel=2, initial_soc=0.9)
    sim = SimConfig(dt_s=1.0, duration_s=3600.0)
    profile = ChargeDischargeCycle(discharge_a=20.0, charge_a=15.0)

    faults = []
    if scenario == "fault":
        # Internal short in module 3 that heats the cell into thermal runaway.
        faults = [
            InternalShort(cell=(3, 0), r_short_ohm=2.0, start_s=600.0),
            ThermalRunaway(cell=(3, 0), trigger_c=70.0, start_s=600.0),
        ]
    elif scenario != "healthy":
        raise ValueError(f"unknown scenario '{scenario}' (use 'healthy' or 'fault')")

    return Simulator(pack, sim, profile, faults), pack, sim


def _build_iteration(
    scenario: str, spec: SystemSpec | None
) -> tuple[Simulator, PackConfig, SimConfig, dict]:
    """One fresh simulator + its config, from either a user spec or a named scenario."""
    if spec is not None:
        return (
            build_simulator_from_spec(spec),
            build_pack_config(spec),
            build_sim_config(spec),
            {"chemistry": spec.chemistry, "spec": spec.to_dict()},
        )
    simulator, pack_cfg, sim_cfg = build_simulator(scenario)
    return simulator, pack_cfg, sim_cfg, {"scenario": scenario}


async def publish_run(
    system_id: str,
    scenario: str = "healthy",
    mqtt_host: str = "localhost",
    mqtt_port: int = 1883,
    speed: float = 1.0,
    loop: bool = False,
    name: str | None = None,
    spec: SystemSpec | None = None,
) -> None:
    """Publish a scenario -- or a user-defined ``spec`` -- to MQTT.

    ``speed`` is a real-time multiplier: 1.0 plays at wall-clock speed, 60.0 plays
    a simulated minute per real second. ``loop`` restarts forever. When ``spec`` is
    given it defines the whole system (topology, chemistry, profile, faults) and
    takes precedence over ``scenario``.
    """
    label = spec.name if spec is not None else f"{system_id} ({scenario})"
    async with aiomqtt.Client(hostname=mqtt_host, port=mqtt_port) as client:
        log.info("publisher connected to mqtt %s:%s as '%s'", mqtt_host, mqtt_port, system_id)
        while True:
            simulator, pack_cfg, sim_cfg, config_extra = _build_iteration(scenario, spec)

            # Retained config so late-joining twin cores still learn the topology.
            config_payload = {
                "system_id": system_id,
                "name": name or label,
                "config": {"pack": asdict(pack_cfg), "sim": asdict(sim_cfg), **config_extra},
            }
            await client.publish(
                config_topic(system_id), json.dumps(config_payload), qos=1, retain=True
            )

            topic = telemetry_topic(system_id)
            for tel in simulator.run():
                envelope = {
                    "system_id": system_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "telemetry": tel.to_dict(),
                }
                await client.publish(topic, json.dumps(envelope), qos=1)
                if speed > 0:
                    await asyncio.sleep(sim_cfg.dt_s / speed)

            log.info("scenario '%s' complete for '%s'", scenario, system_id)
            if not loop:
                break
