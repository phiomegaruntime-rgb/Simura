"""In-twin simulation control: run user-defined systems the twin core owns.

Component 10. Until now every system was fed by an *external* process over MQTT,
so the twin core had no way to start/pause/resume/stop one. The ``SimManager``
lets the twin core run simulations itself -- built from a Component-9
:class:`~simura.builder.spec.SystemSpec` -- and publish their telemetry to MQTT
*exactly* like the external publisher. The frames then flow through the normal
ingest -> store -> analytics -> fleet pipeline unchanged, but the twin core holds
the task handle, so it can pause (freeze the sim), resume, stop, and remove it.

The manager is deliberately **MQTT-agnostic**: it takes an injected ``publish``
coroutine (``publish(topic, payload, retain)``), so its lifecycle logic is
unit-tested with a fake publisher and no broker. The real MQTT publisher lives in
:mod:`simura.twincore.main`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Awaitable, Callable

from ..builder import (
    FaultSpec,
    SystemSpec,
    build_fault,
    build_pack_config,
    build_sim_config,
    build_simulator,
)
from ..transport import config_topic, telemetry_topic

log = logging.getLogger("simura.simctl")

Publish = Callable[[str, str, bool], Awaitable[None]]

RUNNING = "running"
PAUSED = "paused"
STOPPED = "stopped"


def _warm_weather(simulator) -> None:
    """Trigger a weather provider's first (blocking) fetch, ignoring failures.

    Run via ``asyncio.to_thread`` so the HTTP call stays off the event loop. A
    failure here is non-fatal: the provider (wrapped in a CachedProvider) will
    fall back to its offline model when the sim actually queries it.
    """
    import time

    try:
        simulator.weather.at(time.time())
    except Exception:  # pragma: no cover - best-effort warm-up
        log.warning("weather warm-up failed; will fall back at run time")


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
        # The live Simulator while the run loop is going, so faults can be
        # injected into a system that is already running (None when stopped).
        self.simulator = None

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

    def simulator(self, system_id: str):
        """The live :class:`~simura.sim.simulator.Simulator`, or ``None``.

        ``None`` for a real-time feed (there is no model behind it) and for a
        simulation that is registered but not currently running. The explainer
        uses this to decompose a running twin from the solver's own state --
        including the fault coefficients telemetry deliberately cannot carry --
        and falls back to inferring them from the telemetry frame when it is
        ``None``.
        """
        sim = self._sims.get(system_id)
        return sim.simulator if sim else None

    def spec(self, system_id: str) -> SystemSpec | None:
        """The spec a managed simulation was built from, or ``None``."""
        sim = self._sims.get(system_id)
        return sim.spec if sim else None

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

    # -- fault injection --------------------------------------------------
    async def inject_fault(self, system_id: str, fault: FaultSpec) -> FaultSpec:
        """Inject a fault into a simulation *while it runs*.

        Until now a fault could only be declared in the spec before the system
        was built, so breaking a pack meant rebuilding it from t=0. Injection
        instead appends to the two places a fault lives:

        * the **running** :class:`~simura.sim.simulator.Simulator`'s fault list,
          stamped with the simulator's current time so it takes effect on the very
          next timestep -- the pack degrades from wherever it already is; and
        * the **spec**, so the fault is part of the system's description from here
          on -- it survives the run loop's rebuild when a run's duration rolls
          over, and the updated config is republished (retained) so a late-joining
          twin core or dashboard sees the faulted system as it now is.

        ``fault.start_s`` is ignored and replaced with "now" in sim time. Returns
        the stamped :class:`~simura.builder.spec.FaultSpec` that was applied.
        """
        sim = self._require(system_id)
        stamped = FaultSpec(
            type=fault.type,
            series=fault.series,
            parallel=fault.parallel,
            start_s=float(getattr(sim.simulator, "t", 0.0)),
            params=dict(fault.params),
        )
        self._check_cell(sim.spec, stamped)
        built = build_fault(stamped)  # raises ValueError on an unknown type
        if sim.simulator is not None:
            sim.simulator.faults.append(built)
        sim.spec.faults.append(stamped)
        await self._publish_config(system_id, sim.spec)
        log.info(
            "injected %s fault at cell (%d, %d) of '%s' at t=%.1fs",
            stamped.type,
            stamped.series,
            stamped.parallel,
            system_id,
            stamped.start_s,
        )
        return stamped

    def faults(self, system_id: str) -> list[FaultSpec]:
        """Every fault currently on a system, in the order they were applied.

        That order is also the order of the live simulator's fault list -- both
        are built from, and appended to, in lockstep -- which is what makes an
        index a usable handle for :meth:`remove_fault`.
        """
        return list(self._require(system_id).spec.faults)

    async def remove_fault(self, system_id: str, index: int) -> FaultSpec:
        """Remove one fault by its position, from the running sim and the spec.

        Repairing a single bad cell while leaving the rest of a pack's damage in
        place is the difference between a maintenance action and starting over,
        so this is deliberately finer-grained than :meth:`clear_faults`.
        """
        sim = self._require(system_id)
        if not 0 <= index < len(sim.spec.faults):
            raise ValueError(
                f"no fault at index {index} (system has {len(sim.spec.faults)})"
            )
        removed = sim.spec.faults.pop(index)
        # The live list is parallel to the spec's, so the same index is the same
        # fault. Guarded anyway: a sim that crashed mid-run has no fault list.
        if sim.simulator is not None and index < len(sim.simulator.faults):
            sim.simulator.faults.pop(index)
        await self._publish_config(system_id, sim.spec)
        log.info("removed %s fault from '%s'", removed.type, system_id)
        return removed

    async def clear_faults(self, system_id: str) -> int:
        """Repair a system: drop every fault, live and in the spec. Returns the count."""
        sim = self._require(system_id)
        n = len(sim.spec.faults)
        sim.spec.faults.clear()
        if sim.simulator is not None:
            sim.simulator.faults.clear()
        await self._publish_config(system_id, sim.spec)
        return n

    @staticmethod
    def _check_cell(spec: SystemSpec, fault: FaultSpec) -> None:
        """Reject a fault aimed at a cell the pack doesn't have."""
        if not 0 <= fault.series < spec.series:
            raise ValueError(
                f"series index {fault.series} out of range (pack has {spec.series} modules)"
            )
        if not 0 <= fault.parallel < spec.parallel:
            raise ValueError(
                f"parallel index {fault.parallel} out of range (pack has {spec.parallel} slots)"
            )

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

    @staticmethod
    def _config_payload(system_id: str, spec: SystemSpec) -> dict:
        """The retained config message describing a system as it currently is."""
        return {
            "system_id": system_id,
            "name": spec.name,
            "config": {
                "pack": asdict(build_pack_config(spec)),
                "sim": asdict(build_sim_config(spec)),
                "chemistry": spec.chemistry,
                "source": "simulation",
                "spec": spec.to_dict(),
            },
        }

    async def _publish_config(self, system_id: str, spec: SystemSpec) -> None:
        """(Re)publish a system's retained config. Best-effort: never fatal."""
        try:
            await self._publish(
                config_topic(system_id), json.dumps(self._config_payload(system_id, spec)), True
            )
        except Exception:  # pragma: no cover - broker hiccup must not fail the call
            log.warning("could not publish config for %s", system_id)

    async def _run(self, system_id: str, sim: ManagedSim) -> None:
        """Publish a sim's config + telemetry until cancelled (loops forever)."""
        spec = sim.spec
        sim_cfg = build_sim_config(spec)
        try:
            while True:
                # Rebuilt each pass so a fault injected mid-run is carried into the
                # next one (inject_fault appends to the spec as well as the sim).
                await self._publish(
                    config_topic(system_id),
                    json.dumps(self._config_payload(system_id, spec)),
                    True,
                )
                simulator = build_simulator(spec)
                sim.simulator = simulator
                # A live weather source fetches over HTTP on its first query; do
                # that off the event loop so a managed sim never blocks the twin
                # core. Later queries hit the provider's in-memory cache.
                if simulator.weather is not None:
                    await asyncio.to_thread(_warm_weather, simulator)
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
            sim.simulator = None
            raise
        except Exception:  # a bug in one sim must not take the twin core down
            log.exception("simulation '%s' crashed", system_id)
            sim.simulator = None
            sim.run_state = STOPPED
