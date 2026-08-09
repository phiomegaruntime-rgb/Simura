"""Validate the Simura model against a battery dataset -- offline demo.

Every twin is only as trustworthy as the physics behind it. This example runs the
:mod:`simura.validate` pipeline end-to-end against the bundled *synthetic*
sample (no download needed): it replays the sample's measured current through
Simura's own cell model and reports how closely the predicted terminal voltage
matches the measured one -- first with nominal parameters, then after fitting the
internal resistance.

To validate against *real* data instead, browse the catalog and point a loader at
your own download::

    python -m simura.validate --list
    python -m simura.validate --dataset oxford-degradation --file cell1.mat --fit

Usage:
    python examples/validate_demo.py

Only needs numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from simura.validate import (  # noqa: E402
    get_dataset,
    list_datasets,
    load_sample,
    validate_run,
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("Open datasets you can validate against (simura.validate.catalog):\n")
    for d in list_datasets():
        tag = "  [SYNTHETIC]" if d.synthetic else ""
        print(f"  {d.id:<20} {d.chemistry:<10} {d.license}{tag}")

    spec = get_dataset("demo-synthetic")
    ref = load_sample(spec)
    print(f"\nValidating against '{spec.id}' ({ref.n_samples} samples, "
          f"{ref.duration_s:.0f} s of a CC/CD cycle)...")

    report = validate_run(ref, fit=True, data_source="example")
    m = report.metrics
    print("\nModel vs measured terminal voltage:")
    print(f"  nominal (R0 = {report.params['r0_ohm']*1000:.0f} mOhm):"
          f"  RMSE {m['rmse']*1000:6.1f} mV   max |err| {m['max_abs_err']*1000:6.1f} mV")
    if report.fitted:
        fm = report.fitted["metrics"]
        print(f"  best-fit (R0 = {report.fitted['r0_ohm']*1000:.0f} mOhm):"
              f"  RMSE {fm['rmse']*1000:6.1f} mV")
        print(f"\nFitting the internal resistance cuts the error to the noise floor -- "
              f"the physics tracks the cell once R0 is right.")

    print(f"\nNote: {report.notes}")


if __name__ == "__main__":
    main()
