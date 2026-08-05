"""The simulator: drives a pack through a load profile with faults, yielding telemetry.

This is the top-level object other components will drive. It is a generator at
heart -- ``run()`` yields one :class:`PackTelemetry` per timestep -- so the same
code can feed a plot, an MQTT publisher, or a training-data dump without change.
"""

from __future__ import annotations

from typing import Iterator

from .config import PackConfig, SimConfig
from .faults import Fault, accumulate
from .pack import BatteryPack
from .profiles import LoadProfile
from .telemetry import PackTelemetry, snapshot


class Simulator:
    def __init__(
        self,
        pack_config: PackConfig | None = None,
        sim_config: SimConfig | None = None,
        profile: LoadProfile | None = None,
        faults: list[Fault] | None = None,
    ) -> None:
        self.pack = BatteryPack(pack_config or PackConfig())
        self.sim = sim_config or SimConfig()
        self.profile = profile
        self.faults = faults or []
        self.t = 0.0

    def run(self) -> Iterator[PackTelemetry]:
        """Yield telemetry once per timestep until ``duration_s`` is reached."""
        if self.profile is None:
            raise ValueError("Simulator needs a load profile to run.")

        n_steps = int(self.sim.duration_s / self.sim.dt_s)
        for _ in range(n_steps):
            pack_current = self.profile.current(self.t, self.pack.pack_voltage_v)
            effect = accumulate(self.faults, self.pack, self.t)
            self.pack.step(pack_current, self.sim.dt_s, effect)
            self.t += self.sim.dt_s
            yield snapshot(self.pack, self.t, pack_current)

    def run_to_list(self) -> list[PackTelemetry]:
        """Convenience: collect the whole run into a list."""
        return list(self.run())
