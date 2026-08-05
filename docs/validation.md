# Validation

A digital twin is only trustworthy if its physics matches real batteries.
`celltwin.validate` lets you check the model against **open, publicly-licensed
battery datasets**: it replays a dataset's measured current through CellTwin's own
cell model and reports how closely the predicted terminal voltage tracks the
measured one.

CellTwin does **not** redistribute any dataset — the files are large and each
carries its own license. What ships is a *catalog* (where to find each dataset,
its license, how to cite it, and which loader parses its format) plus a tiny,
clearly-labelled **synthetic** sample so the whole pipeline runs offline.

## The catalog

```bash
python -m celltwin.validate --list
```

| Dataset | Institution | Chemistry | License |
|---------|-------------|-----------|---------|
| `demo-synthetic` | CellTwin (generated) | NMC | Apache-2.0 — **synthetic, not real data** |
| `demo-synthetic-lfp` | CellTwin (generated) | LFP | Apache-2.0 — **synthetic, not real data** |
| `nasa-pcoe` | NASA Ames PCoE | LCO | US Gov public domain |
| `oxford-degradation` | University of Oxford | NMC/LCO | CC-BY-4.0 |
| `calce` | University of Maryland (CALCE) | LCO | Research use |
| `sandia` | Sandia National Labs | NMC/NCA/LFP | CC-BY-4.0 |
| `stanford-tri` | Stanford / MIT / TRI | LFP | CC-BY-4.0 |
| `rwth-aachen` | RWTH Aachen (ISEA) | NMC | CC-BY-4.0 |
| `hnei` | Hawaii Natural Energy Inst. | NMC-LCO | CC-BY-4.0 |

!!! warning "Verify before you rely on it"
    The license and citation strings are curated best-effort metadata. Confirm
    the terms on each dataset's own homepage before redistributing data or
    publishing results.

## Validate the synthetic demo (offline, no download)

```bash
python -m celltwin.validate --dataset demo-synthetic --fit
python examples/validate_demo.py
```

The demo replays the bundled sample and reports voltage error with **nominal**
parameters and after **fitting** the internal resistance:

```
Voltage error (model vs measured):
  RMSE          19.6 mV      # nominal R0 = 20 mOhm
  ...
Fitted (R0=25.0 mOhm):  RMSE 1.9 mV
```

The sample was generated at 25 mΩ; fitting recovers it and drops the error to the
2 mV measurement-noise floor — the physics tracks the cell once R0 is right.

## Validate real data (your own download)

Download a dataset from its homepage, then point the matching loader at your file:

```bash
python -m celltwin.validate --dataset oxford-degradation --file cell1.mat --fit
```

`.mat` datasets (NASA, Oxford) need SciPy: `pip install celltwin[validate]`.
For any dataset, exporting a single cell to a CSV with `time_s,current_a,voltage_v`
columns lets you use the generic loader. See the loader docstrings in
[`loaders.py`](https://github.com/celltwin/celltwin/blob/main/src/celltwin/validate/loaders.py)
for each format's exact fields, and the library API:

```python
from celltwin.validate import get_dataset, loader_for, validate_run

spec = get_dataset("oxford-degradation")
ref = loader_for(spec)("cell1.mat")     # -> normalized ReferenceRun
report = validate_run(ref, fit=True)
print(report.metrics["rmse"])
```

## Chemistry-specific OCV curves

A cell's OCV-SoC curve is its electrical fingerprint, and it differs sharply by
chemistry — LFP's famously flat mid-SoC plateau looks nothing like NMC. The
engine picks the matching curve automatically from the dataset's chemistry
(`NMC`, `LFP`, `LCO`, `NCA`; unknown chemistries fall back to NMC), so LFP data
validates against the LFP curve rather than being penalized by the wrong one.

The bundled `demo-synthetic-lfp` sample makes the point:

```bash
python -m celltwin.validate --dataset demo-synthetic-lfp --fit
```

| OCV curve used | RMSE (nominal) | RMSE (best-fit) |
|----------------|----------------|-----------------|
| **LFP** (correct) | ~34 mV | ~9 mV |
| NMC (wrong) | ~270 mV | ~220 mV |

The wrong curve is off by hundreds of mV and **fitting R0/SoC can't rescue it** —
the error is in the OCV shape, not the resistance. Override the auto-selection
with `validate_run(ref, chemistry="LFP")` or pass your own `ocv_table=[(soc, v), …]`.
The built-in curves are *illustrative* (realistic shape, not manufacturer-exact);
swapping in a measured table is a great contribution.

## In the dashboard

The **Validation** tab renders the catalog as selectable cards (license badge,
copy-citation, copy-CLI-command) and lets you validate data three ways:

- **Upload your own dataset** — pick a file you downloaded, choose its format
  (a cataloged reader like NASA/Oxford/CALCE, or *Generic CSV* with a column
  mapping + chemistry + unit scale), and hit *Validate my file*. The twin core
  parses it, replays it through the model, and shows the measured-vs-model
  voltage overlay with RMSE/MAE/bias tiles. This is real validation of real data
  — the file is parsed by the same twin core the dashboard already talks to and
  is discarded after the run (it is never persisted).
- **Run synthetic demo** — no download handy? Validate a bundled synthetic sample
  matched to the selected dataset's chemistry, just to see the pipeline work.
- **CLI** — each card copies the exact `python -m celltwin.validate` command.

Upload size is capped by `CELLTWIN_VALIDATION_MAX_UPLOAD_MB` (default 25). The
default twin-core image is **CSV-only** to stay lean; parsing `.mat` files
(NASA / Oxford) is opt-in — rebuild the image with the `validate` extra
(`pip install ".[server,connect,validate]"`, which pulls in SciPy). A `.mat`
upload against a twin core without SciPy returns a clear "install SciPy" error.

## Honest limits

- OCV curves ship for **NMC / LFP / LCO / NCA** and are auto-selected by
  chemistry; an unrecognized chemistry falls back to NMC (the report's
  `ocv_curve` field and notes say which curve was used). The curves are
  illustrative, not manufacturer-exact — supply a measured `ocv_table` for
  publication-grade results.
- Initial SoC is estimated from the first sample via the inverse OCV curve, which
  is exact only at rest — the target datasets start from a soak step. LFP's flat
  plateau makes this ill-conditioned mid-charge, so the best-fit scan (which also
  tunes initial SoC) matters more for LFP.
- The API endpoint (`POST /api/validation/run`) is a demonstration on the
  synthetic sample; it never claims to have validated a real dataset server-side.
