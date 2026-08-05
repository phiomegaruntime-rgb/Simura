"""Run a :class:`~celltwin.builder.spec.SystemSpec` offline and summarize it.

The preview is the fast feedback loop of the system builder: validate the spec,
run the simulation entirely in-process (no MQTT, no database), and return a small
summary plus downsampled sparklines. It answers "does my system behave sanely?"
in well under a second for a typical spec -- final SoC, voltage window, peak
temperature, energy throughput, and whether any safety limit was breached -- so
the user can iterate before going live with ``--spec``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .build import build_simulator
from .spec import SystemSpec
from .validate import validate_spec


@dataclass
class PreviewResult:
    """The offline summary of a spec run."""

    system_id: str
    name: str
    chemistry: str
    n_steps: int
    duration_s: float

    final_soc: float
    min_soc: float
    min_pack_voltage_v: float
    max_pack_voltage_v: float
    peak_temp_c: float
    max_imbalance_v: float
    energy_throughput_wh: float
    peak_power_w: float

    temp_limit_c: float
    temp_limit_exceeded: bool
    time_to_limit_s: float | None  # first time peak temp crossed temp_max_c, if any

    series_len: int
    parallel_len: int

    # Downsampled traces for sparklines (evenly-sampled by index).
    sparkline: dict[str, list[float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SpecError(ValueError):
    """Raised when a spec fails validation. ``errors`` holds the messages."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def preview(spec: SystemSpec, *, max_points: int = 200) -> PreviewResult:
    """Validate, run offline, and summarize a spec.

    Raises :class:`SpecError` if the spec is invalid (so callers get the full list
    of problems, not a physics crash).
    """
    errors = validate_spec(spec)
    if errors:
        raise SpecError(errors)

    sim = build_simulator(spec)

    ts: list[float] = []
    soc: list[float] = []
    temp: list[float] = []
    volt: list[float] = []
    power: list[float] = []

    energy_wh = 0.0
    peak_temp = -1e9
    min_v = 1e9
    max_v = -1e9
    min_soc = 1e9
    max_imb = 0.0
    peak_power = 0.0
    time_to_limit: float | None = None
    dt = spec.dt_s

    for frame in sim.run():
        ts.append(frame.time_s)
        soc.append(frame.pack_soc)
        temp.append(frame.max_temp_c)
        volt.append(frame.pack_voltage_v)
        power.append(frame.pack_power_w)

        energy_wh += abs(frame.pack_power_w) * dt / 3600.0
        peak_temp = max(peak_temp, frame.max_temp_c)
        min_v = min(min_v, frame.pack_voltage_v)
        max_v = max(max_v, frame.pack_voltage_v)
        min_soc = min(min_soc, frame.pack_soc)
        max_imb = max(max_imb, frame.voltage_imbalance_v)
        peak_power = max(peak_power, abs(frame.pack_power_w))
        if time_to_limit is None and frame.max_temp_c >= spec.temp_max_c:
            time_to_limit = frame.time_s

    if not ts:  # validate_spec guarantees >= 1 step, but be defensive
        raise SpecError(["spec produced no simulation steps"])

    return PreviewResult(
        system_id=spec.system_id,
        name=spec.name,
        chemistry=spec.chemistry,
        n_steps=len(ts),
        duration_s=ts[-1],
        final_soc=soc[-1],
        min_soc=min_soc,
        min_pack_voltage_v=min_v,
        max_pack_voltage_v=max_v,
        peak_temp_c=peak_temp,
        max_imbalance_v=max_imb,
        energy_throughput_wh=energy_wh,
        peak_power_w=peak_power,
        temp_limit_c=spec.temp_max_c,
        temp_limit_exceeded=time_to_limit is not None,
        time_to_limit_s=time_to_limit,
        series_len=spec.series,
        parallel_len=spec.parallel,
        sparkline=_downsample(
            {"t": ts, "soc": soc, "max_temp": temp, "voltage": volt, "power": power},
            max_points,
        ),
    )


def _downsample(series: dict[str, list[float]], max_points: int) -> dict[str, list[float]]:
    n = len(series["t"])
    if n <= max_points:
        return series
    step = n / max_points
    idx = [int(i * step) for i in range(max_points)]
    return {k: [v[i] for i in idx] for k, v in series.items()}
