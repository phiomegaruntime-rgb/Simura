"""Tests for the in-twin simulation manager (simura.twincore.simctl).

The manager is MQTT-agnostic -- it takes an injected ``publish`` coroutine -- so
its whole lifecycle is exercised here with a fake publisher and a real asyncio
event loop, no broker required.
"""

from __future__ import annotations

import asyncio

import pytest

import json

from simura.builder import SystemSpec, WeatherSpec
from simura.twincore.simctl import PAUSED, RUNNING, STOPPED, SimManager


class FakePublisher:
    """Records every publish; lets tests count telemetry frames."""

    def __init__(self) -> None:
        self.msgs: list[tuple[str, str, bool]] = []

    async def publish(self, topic: str, payload: str, retain: bool = False) -> None:
        self.msgs.append((topic, payload, retain))

    def telemetry_count(self, system_id: str) -> int:
        topic = f"simura/telemetry/{system_id}"
        return sum(1 for t, _, _ in self.msgs if t == topic)

    def retained_configs(self, system_id: str) -> list[str]:
        topic = f"simura/config/{system_id}"
        return [p for t, p, r in self.msgs if t == topic and r]


def _spec(system_id="sim-1", **kw) -> SystemSpec:
    # Long run so it never completes mid-test; fast speed so frames flow quickly.
    return SystemSpec(system_id=system_id, name="T", dt_s=1.0, duration_s=100000.0, **kw)


async def _settle(seconds: float = 0.06) -> None:
    await asyncio.sleep(seconds)


def test_create_start_publishes_frames_and_config():
    async def run():
        pub = FakePublisher()
        mgr = SimManager(pub.publish, default_speed=200.0)
        mgr.create(_spec())
        assert mgr.run_state("sim-1") == STOPPED
        await mgr.start("sim-1")
        assert mgr.run_state("sim-1") == RUNNING
        await _settle()
        assert pub.telemetry_count("sim-1") > 0
        assert pub.retained_configs("sim-1")  # retained config published
        await mgr.close()

    asyncio.run(run())


def test_pause_freezes_then_resume_continues():
    async def run():
        pub = FakePublisher()
        mgr = SimManager(pub.publish, default_speed=200.0)
        mgr.create(_spec("sim-2"))
        await mgr.start("sim-2")
        await _settle()

        await mgr.pause("sim-2")
        assert mgr.run_state("sim-2") == PAUSED
        n = pub.telemetry_count("sim-2")
        await _settle()
        assert pub.telemetry_count("sim-2") == n  # frozen while paused

        await mgr.resume("sim-2")
        assert mgr.run_state("sim-2") == RUNNING
        await _settle()
        assert pub.telemetry_count("sim-2") > n  # flowing again
        await mgr.close()

    asyncio.run(run())


def test_stop_then_start_again():
    async def run():
        pub = FakePublisher()
        mgr = SimManager(pub.publish, default_speed=200.0)
        mgr.create(_spec("sim-3"))
        await mgr.start("sim-3")
        await _settle()
        await mgr.stop("sim-3")
        assert mgr.run_state("sim-3") == STOPPED
        frozen = pub.telemetry_count("sim-3")
        await _settle()
        assert pub.telemetry_count("sim-3") == frozen  # task really stopped
        await mgr.start("sim-3")  # can restart
        await _settle()
        assert pub.telemetry_count("sim-3") > frozen
        await mgr.close()

    asyncio.run(run())


def test_remove_clears_retained_config_and_forgets():
    async def run():
        pub = FakePublisher()
        mgr = SimManager(pub.publish, default_speed=200.0)
        mgr.create(_spec("sim-4"))
        await mgr.start("sim-4")
        await _settle()
        await mgr.remove("sim-4")
        assert not mgr.is_managed("sim-4")
        assert mgr.states() == {}
        # an empty retained payload was published to clear the retained config
        assert "" in pub.retained_configs("sim-4")

    asyncio.run(run())


def test_managed_sim_with_weather_publishes_conditions():
    async def run():
        pub = FakePublisher()
        mgr = SimManager(pub.publish, default_speed=200.0)
        spec = _spec(
            "sim-wx",
            weather=WeatherSpec("synthetic", {"mean_temp_c": 22.0, "temp_amplitude_c": 8.0}),
        )
        mgr.create(spec)
        await mgr.start("sim-wx")
        await _settle()
        # A telemetry frame should carry the weather that produced it.
        frames = [
            json.loads(p)
            for t, p, _ in pub.msgs
            if t == "simura/telemetry/sim-wx"
        ]
        assert frames and frames[0]["telemetry"]["weather"] is not None
        assert "air_temp_c" in frames[0]["telemetry"]["weather"]
        await mgr.close()

    asyncio.run(run())


def test_states_map_and_missing_id():
    async def run():
        mgr = SimManager(FakePublisher().publish)
        mgr.create(_spec("a"))
        mgr.create(_spec("b"))
        assert set(mgr.states()) == {"a", "b"}
        with pytest.raises(KeyError):
            await mgr.start("does-not-exist")

    asyncio.run(run())
