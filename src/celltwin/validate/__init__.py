"""Validate the CellTwin physics model against real, open-licensed battery data.

Three pieces:

* :mod:`~celltwin.validate.catalog` -- a curated directory of open datasets
  (NASA, Oxford, CALCE, Sandia, Stanford-MIT-TRI, ...) with license + citation
  metadata. CellTwin does not redistribute the data; you download it yourself.
* :mod:`~celltwin.validate.loaders` -- turn a downloaded file into one normalized
  :class:`~celltwin.validate.reference.ReferenceRun`.
* :mod:`~celltwin.validate.engine` -- replay the measured current through
  CellTwin's own cell model and report the voltage error.

A tiny, clearly-labelled *synthetic* sample (``demo-synthetic``) is bundled so the
whole pipeline runs offline::

    python -m celltwin.validate --list
    python -m celltwin.validate --dataset demo-synthetic
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
