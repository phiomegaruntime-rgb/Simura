"""Validate the Simura physics model against real, open-licensed battery data.

Three pieces:

* :mod:`~simura.validate.catalog` -- a curated directory of open datasets
  (NASA, Oxford, CALCE, Sandia, Stanford-MIT-TRI, ...) with license + citation
  metadata. Simura does not redistribute the data; you download it yourself.
* :mod:`~simura.validate.loaders` -- turn a downloaded file into one normalized
  :class:`~simura.validate.reference.ReferenceRun`.
* :mod:`~simura.validate.engine` -- replay the measured current through
  Simura's own cell model and report the voltage error.

A tiny, clearly-labelled *synthetic* sample (``demo-synthetic``) is bundled so the
whole pipeline runs offline::

    python -m simura.validate --list
    python -m simura.validate --dataset demo-synthetic
"""

from .catalog import (
    DATASETS,
    DatasetSpec,
    datasets_for_chemistry,
    get_dataset,
    list_datasets,
    synthetic_for,
)
from .engine import ValidationReport, validate_run
from .loaders import (
    load_calce_csv,
    load_generic_csv,
    load_nasa_mat,
    load_oxford_mat,
    load_sample,
    load_sandia_csv,
    load_upload,
    loader_for,
    sample_path,
)
from .reference import ReferenceRun

__all__ = [
    "DATASETS",
    "DatasetSpec",
    "list_datasets",
    "get_dataset",
    "datasets_for_chemistry",
    "synthetic_for",
    "ReferenceRun",
    "load_generic_csv",
    "load_nasa_mat",
    "load_oxford_mat",
    "load_calce_csv",
    "load_sandia_csv",
    "load_sample",
    "load_upload",
    "loader_for",
    "sample_path",
    "validate_run",
    "ValidationReport",
]
