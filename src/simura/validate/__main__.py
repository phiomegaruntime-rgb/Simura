"""CLI:  python -m simura.validate [--list | --dataset <id> [--file <path>] ...]

Examples
--------
List the catalog::

    python -m simura.validate --list

Validate against the bundled synthetic sample (no download needed)::

    python -m simura.validate --dataset demo-synthetic --fit

Validate against your own download of a real dataset::

    python -m simura.validate --dataset oxford-degradation --file cell1.mat --fit
"""

from __future__ import annotations

import argparse
import json
import sys

from .catalog import get_dataset, list_datasets
from .engine import validate_run
from .loaders import load_sample, loader_for


def _reconfigure_stdout() -> None:
    # Windows consoles default to cp1252; force UTF-8 so any stray unicode is safe.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def _print_catalog() -> None:
    print(f"{'ID':<20} {'CHEMISTRY':<10} {'LICENSE':<26} INSTITUTION")
    print("-" * 96)
    for d in list_datasets():
        tag = " (synthetic)" if d.synthetic else ""
        print(f"{d.id:<20} {d.chemistry:<10} {d.license:<26} {d.institution}{tag}")
    print(
        "\nSimura does not redistribute real datasets -- download one, then:\n"
        "  python -m simura.validate --dataset <id> --file <your-download>"
    )


def _print_report(report, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report.to_dict(), indent=2))
        return
    m = report.metrics
    print(f"Dataset:   {report.dataset_id}  (cell {report.cell_id}, {report.chemistry})")
    print(f"Source:    {report.data_source}")
    print(f"Samples:   {report.n_samples}  over {report.duration_s:.0f} s")
    print(f"Params:    R0={report.params['r0_ohm']*1000:.1f} mOhm  "
          f"Q={report.params['capacity_ah']:.2f} Ah  SoC0={report.params['soc0']*100:.0f}%")
    print("Voltage error (model vs measured):")
    print(f"  RMSE       {m['rmse']*1000:7.1f} mV")
    print(f"  MAE        {m['mae']*1000:7.1f} mV")
    print(f"  max |err|  {m['max_abs_err']*1000:7.1f} mV")
    print(f"  mean bias  {m['mean_bias']*1000:7.1f} mV")
    if report.fitted:
        fm = report.fitted["metrics"]
        print(f"Fitted (R0={report.fitted['r0_ohm']*1000:.1f} mOhm, "
              f"SoC0={report.fitted['soc0']*100:.0f}%):  RMSE {fm['rmse']*1000:.1f} mV")
    if report.notes:
        print(f"Notes:     {report.notes}")


def main() -> None:
    _reconfigure_stdout()
    parser = argparse.ArgumentParser(
        prog="python -m simura.validate",
        description="Validate the Simura model against open battery datasets.",
    )
    parser.add_argument("--list", action="store_true", help="print the dataset catalog and exit")
    parser.add_argument("--dataset", help="dataset id from the catalog (see --list)")
    parser.add_argument("--file", help="path to your downloaded dataset file")
    parser.add_argument("--fit", action="store_true", help="also report best-fit R0 / SoC0")
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args()

    if args.list or not args.dataset:
        _print_catalog()
        return

    spec = get_dataset(args.dataset)

    if args.file:
        loader = loader_for(spec)
        ref = loader(args.file)
        source = "user-file"
    elif spec.sample:
        ref = load_sample(spec)
        source = "bundled-synthetic-demo"
    else:
        raise SystemExit(
            f"dataset '{spec.id}' has no bundled sample -- download it and pass --file.\n"
            f"  homepage: {spec.homepage_url}"
        )

    report = validate_run(ref, fit=args.fit, data_source=source)
    _print_report(report, args.json)


if __name__ == "__main__":
    main()
