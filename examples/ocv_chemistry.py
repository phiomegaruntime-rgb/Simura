"""Swap the cell chemistry by replacing the OCV-SoC curve (NMC vs LFP).

The open-circuit-voltage vs state-of-charge curve is a chemistry's electrical
fingerprint. Simura's default is an illustrative NMC curve; LFP (lithium iron
phosphate) has a famously *flat* plateau across the mid-SoC range. This example
builds both curves with :func:`simura.sim.make_ocv`, compares them, and shows
how flatness makes estimating SoC from voltage much harder for LFP -- exactly the
sparsity a hardware connector has to cope with.

Adding a measured chemistry table is a great "good first area" for contributors.

To use a custom chemistry in a full simulation, replace the pack's OCV function
after construction:

    sim = Simulator(PackConfig(...), SimConfig(...), profile)
    sim.pack.ocv = make_ocv(LFP_OCV_TABLE)
    sim.pack.cell_voltage_v = sim.pack.ocv(sim.pack.soc).copy()  # re-seed voltage

Usage:
    python examples/ocv_chemistry.py

Only needs numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from simura.sim import make_ocv  # noqa: E402
from simura.sim.ocv import NMC_OCV_TABLE  # noqa: E402

# An illustrative LFP curve: ~3.2 V nominal with a very flat 20-90% plateau.
LFP_OCV_TABLE: list[tuple[float, float]] = [
    (0.00, 2.80),
    (0.05, 3.10),
    (0.10, 3.20),
    (0.20, 3.26),
    (0.30, 3.28),
    (0.40, 3.29),
    (0.50, 3.30),
    (0.60, 3.31),
    (0.70, 3.32),
    (0.80, 3.33),
    (0.90, 3.35),
    (1.00, 3.60),
]


def main() -> None:
    nmc = make_ocv(NMC_OCV_TABLE)
    lfp = make_ocv(LFP_OCV_TABLE)

    soc = np.linspace(0.0, 1.0, 11)
    print("OCV (V) vs SoC for two chemistries:\n")
    print(f"{'SoC':>5} {'NMC':>7} {'LFP':>7}")
    print("-" * 21)
    nmc_v = nmc(soc)
    lfp_v = lfp(soc)
    for s, vn, vl in zip(soc, nmc_v, lfp_v):
        print(f"{s:5.2f} {vn:7.3f} {vl:7.3f}")

    # Voltage swing across the usable 20-80% band -- the smaller it is, the harder
    # it is to read SoC off voltage (relevant to connectors that lack pack SoC).
    band = np.array([0.2, 0.8])
    nmc_swing = float(np.ptp(nmc(band)))
    lfp_swing = float(np.ptp(lfp(band)))
    print(f"\nVoltage swing across 20-80% SoC:")
    print(f"  NMC: {nmc_swing * 1000:5.0f} mV")
    print(f"  LFP: {lfp_swing * 1000:5.0f} mV  <- much flatter")
    print(
        f"\nLFP's plateau is ~{nmc_swing / lfp_swing:.1f}x flatter, which is why a"
        "\nvoltage-only SoC estimate is far less reliable for LFP packs."
    )


if __name__ == "__main__":
    main()
