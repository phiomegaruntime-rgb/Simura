"""Tests for the in-twin simulation manager (simura.twincore.simctl).

The manager is MQTT-agnostic -- it takes an injected ``publish`` coroutine -- so
its whole lifecycle is exercised here with a fake publisher and a real asyncio
event loop, no broker required.
"""

from __future__ import annotations

import asyncio

import pytest

import json

from simura.builder import FaultSpec, SystemSpec, WeatherSpec
from simura.sim import SensorDrift
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


# -- live fault injection ("break it where it stands") ------------------------


def test_inject_fault_hits_the_running_simulator():
    async def run():
        pub = FakePublisher()
        mgr = SimManager(pub.publish, default_speed=200.0)
        mgr.create(_spec("sim-f1"))
        await mgr.start("sim-f1")
        await _settle()

        sim = mgr._sims["sim-f1"]
        assert sim.simulator is not None and not sim.simulator.faults
        t_before = sim.simulator.t

        applied = await mgr.inject_fault(
            "sim-f1", FaultSpec(type="internal_short", series=2, parallel=0)
        )
        # Stamped with "now" in sim time, not the FaultSpec default of 600 s.
        assert applied.start_s >= t_before
        assert applied.start_s != 600.0
        # Live in the running sim *and* recorded in the spec, so a rebuild keeps it.
        assert len(sim.simulator.faults) == 1
        assert [f.type for f in sim.spec.faults] == ["internal_short"]
        await mgr.close()

    asyncio.run(run())


def test_injected_fault_actually_heats_the_targeted_cell():
    async def run():
        pub = FakePublisher()
        mgr = SimManager(pub.publish, default_speed=500.0)
        mgr.create(_spec("sim-f2"))
        await mgr.start("sim-f2")
        await _settle()
        await mgr.inject_fault(
            "sim-f2",
            FaultSpec(type="internal_short", series=1, parallel=0, params={"r_short_ohm": 0.5}),
        )
        await _settle(0.4)
        await mgr.close()

        frames = [json.loads(p) for t, p, _ in pub.msgs if t == "simura/telemetry/sim-f2"]
        last = frames[-1]["telemetry"]
        cells = {(c["series_index"], c["parallel_index"]): c for c in last["cells"]}
        shorted = cells[(1, 0)]["temp_c"]
        peers = [c["temp_c"] for k, c in cells.items() if k != (1, 0)]
        assert shorted > max(peers)  # the shorted cell is the hottest in the pack

    asyncio.run(run())


def test_inject_fault_republishes_config_and_survives_rebuild():
    async def run():
        pub = FakePublisher()
        mgr = SimManager(pub.publish, default_speed=200.0)
        mgr.create(_spec("sim-f3"))
        await mgr.start("sim-f3")
        await _settle()
        await mgr.inject_fault("sim-f3", FaultSpec(type="cooling_fault", series=0, parallel=1))
        await mgr.close()

        # The newest retained config carries the fault, so a late-joining twin core
        # or dashboard sees the faulted system as it now is.
        latest = json.loads(pub.retained_configs("sim-f3")[-1])
        assert latest["config"]["spec"]["faults"][0]["type"] == "cooling_fault"

    asyncio.run(run())


def test_inject_fault_rejects_out_of_range_cell_and_unknown_type():
    async def run():
        mgr = SimManager(FakePublisher().publish, default_speed=200.0)
        mgr.create(_spec("sim-f4", series=4, parallel=2))
        with pytest.raises(ValueError, match="series index"):
            await mgr.inject_fault("sim-f4", FaultSpec(type="internal_short", series=9))
        with pytest.raises(ValueError, match="parallel index"):
            await mgr.inject_fault("sim-f4", FaultSpec(type="internal_short", parallel=5))
        with pytest.raises(ValueError, match="unknown fault type"):
            await mgr.inject_fault("sim-f4", FaultSpec(type="not-a-fault"))
        # A rejected fault leaves the spec untouched.
        assert mgr._sims["sim-f4"].spec.faults == []

    asyncio.run(run())


def test_clear_faults_repairs_live_sim_and_spec():
    async def run():
        pub = FakePublisher()
        mgr = SimManager(pub.publish, default_speed=200.0)
        mgr.create(_spec("sim-f5"))
        await mgr.start("sim-f5")
        await _settle()
        await mgr.inject_fault("sim-f5", FaultSpec(type="internal_short"))
        await mgr.inject_fault("sim-f5", FaultSpec(type="resistance_growth", series=1))
        sim = mgr._sims["sim-f5"]

        assert await mgr.clear_faults("sim-f5") == 2
        assert sim.spec.faults == []
        assert sim.simulator.faults == []
        await mgr.close()

    asyncio.run(run())


def test_faults_lists_in_order_and_remove_takes_one_out():
    """Repairing one bad cell must not repair the whole pack."""
    async def run():
        pub = FakePublisher()
        mgr = SimManager(pub.publish, default_speed=200.0)
        mgr.create(_spec("sim-f6"))
        await mgr.start("sim-f6")
        await _settle()
        await mgr.inject_fault("sim-f6", FaultSpec(type="internal_short", series=0))
        await mgr.inject_fault("sim-f6", FaultSpec(type="cooling_fault", series=1))
        await mgr.inject_fault("sim-f6", FaultSpec(type="sensor_drift", series=2))

        assert [f.type for f in mgr.faults("sim-f6")] == [
            "internal_short",
            "cooling_fault",
            "sensor_drift",
        ]

        removed = await mgr.remove_fault("sim-f6", 1)
        assert removed.type == "cooling_fault"
        # Gone from the spec *and* the running sim, and the two stay parallel so a
        # later index still refers to the same fault in both.
        sim = mgr._sims["sim-f6"]
        assert [f.type for f in mgr.faults("sim-f6")] == ["internal_short", "sensor_drift"]
        assert len(sim.simulator.faults) == 2
        assert isinstance(sim.simulator.faults[1], SensorDrift)
        await mgr.close()

    asyncio.run(run())


def test_remove_fault_rejects_a_bad_index():
    async def run():
        mgr = SimManager(FakePublisher().publish, default_speed=200.0)
        mgr.create(_spec("sim-f7"))
        await mgr.inject_fault("sim-f7", FaultSpec(type="internal_short"))
        for bad in (-1, 1, 99):
            with pytest.raises(ValueError, match="no fault at index"):
                await mgr.remove_fault("sim-f7", bad)
        assert len(mgr.faults("sim-f7")) == 1  # nothing lost to a bad request

    asyncio.run(run())


def test_removing_a_fault_stops_its_effect_on_the_pack():
    """The physics has to actually let go: a repaired cell cools back down."""
    async def run():
        pub = FakePublisher()
        mgr = SimManager(pub.publish, default_speed=500.0)
        mgr.create(_spec("sim-f8"))
        await mgr.start("sim-f8")
        await _settle()
        await mgr.inject_fault(
            "sim-f8",
            FaultSpec(type="internal_short", series=1, parallel=0, params={"r_short_ohm": 0.4}),
        )
        await _settle(0.4)

        def hot_cell_temp() -> float:
            frames = [json.loads(p) for t, p, _ in pub.msgs if t == "simura/telemetry/sim-f8"]
            cells = frames[-1]["telemetry"]["cells"]
            return next(
                c["temp_c"]
                for c in cells
                if c["series_index"] == 1 and c["parallel_index"] == 0
            )

        while_faulted = hot_cell_temp()
        await mgr.remove_fault("sim-f8", 0)
        await _settle(0.5)
        after_repair = hot_cell_temp()
        await mgr.close()

        assert after_repair < while_faulted  # the short is gone, so the cell sheds heat

    asyncio.run(run())
