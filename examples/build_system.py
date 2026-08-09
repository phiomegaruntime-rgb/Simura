"""Design your own battery system, preview it offline, and get the go-live command.

The system builder lets you describe a battery system as a plain
:class:`~simura.builder.spec.SystemSpec` -- chemistry, topology, load profile,
faults, sim settings -- then preview it *offline* (no MQTT, no database) to see
how it behaves before streaming it into the twin. This example builds a custom
LFP pack with an injected internal short, previews it, writes the spec to JSON,
and prints the one command that streams it live.

Usage:
    python examples/build_system.py

Only needs numpy.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from simura.builder import (  # noqa: E402
    FaultSpec,
    ProfileSpec,
    SystemSpec,
    preview,
    validate_spec,
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    spec = SystemSpec(
        system_id="my-lfp-rack",
        name="My LFP rack",
        chemistry="LFP",
        series=16,
        parallel=4,
        capacity_ah=5.0,
        initial_soc=0.9,
        temp_max_c=55.0,
        duration_s=3600.0,
        profile=ProfileSpec("cycle", {"discharge_a": 40.0, "charge_a": 30.0}),
        faults=[FaultSpec("internal_short", series=5, parallel=0, start_s=900.0,
                          params={"r_short_ohm": 1.0})],
    )

    problems = validate_spec(spec)
    if problems:
        print("Spec has problems:")
        for p in problems:
            print(f"  - {p}")
        return

    r = preview(spec)
    print(f"System:    {r.name}  ({r.chemistry}, {r.series_len}S{r.parallel_len}P)")
    print(f"Ran:       {r.n_steps} steps over {r.duration_s:.0f} s")
    print(f"SoC:       {r.min_soc*100:.1f}% .. final {r.final_soc*100:.1f}%")
    print(f"Voltage:   {r.min_pack_voltage_v:.1f} .. {r.max_pack_voltage_v:.1f} V")
    print(f"Peak temp: {r.peak_temp_c:.1f} C  (limit {r.temp_limit_c:.0f} C)")
    print(f"Energy:    {r.energy_throughput_wh:.1f} Wh, peak {r.peak_power_w/1000:.2f} kW")
    print("Safety:    " + ("LIMIT CROSSED at %.0f s" % r.time_to_limit_s
                           if r.temp_limit_exceeded else "within temperature limit"))

    out = Path("my-lfp-rack.json")
    out.write_text(json.dumps(spec.to_dict(), indent=2), encoding="utf-8")
    print(f"\nWrote {out}. Stream it live into a running twin with:")
    print(f"  python -m simura.publisher --spec {out} --speed 10 --loop")


if __name__ == "__main__":
    main()
