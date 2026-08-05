"""In-twin simulation control: run user-defined systems the twin core owns.

Component 10. Until now every system was fed by an *external* process over MQTT,
so the twin core had no way to start/pause/resume/stop one. The ``SimManager``
lets the twin core run simulations itself -- built from a Component-9
:class:`~celltwin.builder.spec.SystemSpec` -- and publish their telemetry to MQTT
*exactly* like the external publisher. The frames then flow through the normal
ingest -> store -> analytics -> fleet pipeline unchanged, but the twin core holds
the task handle, so it can pause (freeze the sim), resume, stop, and remove it.

The manager is deliberately **MQTT-agnostic**: it takes an injected ``publish``
coroutine (``publish(topic, payload, retain)``), so its lifecycle logic is
unit-tested with a fake publisher and no broker. The real MQTT publisher lives in
:mod:`celltwin.twincore.main`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Awaitable, Callable

from ..builder import (
    SystemSpec,
    build_pack_config,
    build_sim_config,
    build_simulator,
)
from ..transport import config_topic, telemetry_topic

log = logging.getLogger("celltwin.simctl")

Publish = Callable[[str, str, bool], Awaitable[None]]

RUNNING = "running"
PAUSED = "paused"
STOPPED = "stopped"


class ManagedSim:
    """One twin-core-owned simulation and its run state."""

    def __init__(self, spec: SystemSpec, speed: float) -> None:
        self.spec = spec
        self.speed = speed
        self.task: asyncio.Task | None = None
        # An asyncio.Event used as a gate: set == running, cleared == paused.
        self._gate = asyncio.Event()
        self._gate.set()
        self.run_state = STOPPED

    @property
    def paused(self) -> bool:
        return not self._gate.is_set()


class SimManager:
    """Runs and controls twin-core-owned simulations."""

    def __init__(self, publish: Publish, default_speed: float = 10.0) -> None:
        self._publish = publish
        self._default_speed = default_speed
        self._sims: dict[str, ManagedSim] = {}

    # -- introspection ----------------------------------------------------
    def is_managed(self, system_id: str) -> bool:
        return system_id in self._sims

    def states(self) -> dict[str, str]:
        """``{system_id: run_state}`` for every managed simulation."""
        return {sid: s.run_state for sid, s in self._sims.items()}

    def run_state(self, system_id: str) -> str | None:
        sim = self._sims.get(system_id)
        return sim.run_state if sim else None

    # -- lifecycle --------------------------------------------------------
    def create(self, spec: SystemSpec, speed: float | None = None) -> ManagedSim:
        """Register a simulation (stopped). Overwrites any prior one with that id."""
        sim = ManagedSim(spec, speed if speed is not None else self._default_speed)
        self._sims[spec.system_id] = sim
        return sim

    async def start(self, system_id: str) -> str:
        """Start (or resume) a simulation. Idempotent for an already-running one."""
        sim = self._require(system_id)
        sim._gate.set()
        if sim.task is None or sim.task.done():
            sim.task = asyncio.create_task(self._run(system_id, sim))
        sim.run_state = RUNNING
        return sim.run_state

    async def resume(self, system_id: str) -> str:
        return await self.start(system_id)

    async def pause(self, system_id: str) -> str:
        """Freeze a simulation: it stops publishing and holds its state."""
        sim = self._require(system_id)
        if sim.task is None or sim.task.done():
            return sim.run_state  # nothing to pause
        sim._gate.clear()
        sim.run_state = PAUSED
        return sim.run_state

    async def stop(self, system_id: str) -> str:
        """Cancel the sim task but keep the spec so it can be started again."""
        sim = self._require(system_id)
        await self._cancel(sim)
        sim.run_state = STOPPED
        return sim.run_state

    async def remove(self, system_id: str) -> None:
        """Stop the sim, clear its retained config, and forget it entirely."""
        sim = self._sims.pop(system_id, None)
        if sim is None:
            return
        await self._cancel(sim)
        # Empty retained payload clears the retained config so a restarted ingest
        # loop doesn't re-register a deleted system.
        try:
            await self._publish(config_topic(system_id), "", True)
        except Exception:  # best-effort cleanup
            log.warning("could not clear retained config for %s", system_id)

    async def close(self) -> None:
        """Cancel every running simulation (on shutdown)."""
        for sim in list(self._sims.values()):
            await self._cancel(sim)

    # -- internals --------------------------------------------------------
    def _require(self, system_id: str) -> ManagedSim:
        sim = self._sims.get(system_id)
        if sim is None:
            raise KeyError(f"no managed simulation '{system_id}'")
        return sim

    async def _cancel(self, sim: ManagedSim) -> None:
        sim._gate.set()  # unblock a paused loop so cancellation lands promptly
        if sim.task is not None and not sim.task.done():
            sim.task.cancel()
            try:
                await sim.task
            except asyncio.CancelledError:
                pass
        sim.task = None

    async def _run(self, system_id: str, sim: ManagedSim) -> None:
        """Publish a sim's config + telemetry until cancelled (loops forever)."""
        spec = sim.spec
        pack_cfg = build_pack_config(spec)
        sim_cfg = build_sim_config(spec)
        config_payload = {
            "system_id": system_id,
            "name": spec.name,
            "config": {
                "pack": asdict(pack_cfg),
                "sim": asdict(sim_cfg),
                "chemistry": spec.chemistry,
                "source": "simulation",
                "spec": spec.to_dict(),
            },
        }
        try:
            while True:
                await self._publish(config_topic(system_id), json.dumps(config_payload), True)
                simulator = build_simulator(spec)
                for tel in simulator.run():
                    await sim._gate.wait()  # blocks here while paused
                    envelope = {
                        "system_id": system_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "telemetry": tel.to_dict(),
                    }
                    await self._publish(telemetry_topic(system_id), json.dumps(envelope), False)
                    if sim.speed > 0:
                        await asyncio.sleep(sim_cfg.dt_s / sim.speed)
        except asyncio.CancelledError:
            raise
        except Exception:  # a bug in one sim must not take the twin core down
            log.exception("simulation '%s' crashed", system_id)
            sim.run_state = STOPPED
