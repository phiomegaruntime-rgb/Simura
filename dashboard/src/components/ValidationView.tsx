import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchDatasets, runValidation, uploadValidation } from "../api/client";
import type { DatasetSpec, UploadOptions, ValidationReport } from "../api/types";
import DatasetCatalog from "./DatasetCatalog";
import StatTile from "./StatTile";

const GENERIC = "__generic__";
const CHEMISTRIES = ["", "NMC", "LFP", "LCO", "NCA"];

// The Validation view: browse the catalog of open datasets, validate your own
// uploaded dataset file against Simura's physics, or run a quick synthetic demo.
export default function ValidationView() {
  const [datasets, setDatasets] = useState<DatasetSpec[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [busy, setBusy] = useState<"" | "demo" | "upload">("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDatasets()
      .then((d) => {
        setDatasets(d);
        setSelected((cur) => cur ?? d.find((x) => !x.synthetic)?.id ?? d[0]?.id ?? null);
      })
      .catch((e) => setError(String(e)));
  }, []);

  const selectedSpec = datasets.find((d) => d.id === selected) ?? null;
  const realDatasets = datasets.filter((d) => !d.synthetic);

  const runDemo = () => {
    if (!selected) return;
    setBusy("demo");
    setError(null);
    runValidation(selected, true)
      .then(setReport)
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(""));
  };

  const runUpload = (file: File, opts: UploadOptions) => {
    setBusy("upload");
    setError(null);
    uploadValidation(file, opts)
      .then(setReport)
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(""));
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg bg-surface border border-hairline px-5 py-4">
        <h2 className="text-lg font-semibold text-ink">Validate against real battery data</h2>
        <p className="text-sm text-ink-secondary mt-1 max-w-3xl">
          Check the Simura physics model against open, publicly-licensed battery datasets.
          Browse the catalog below, then <span className="text-ink">upload your own download</span>{" "}
          to validate it in the browser — Simura replays the measured current through its cell
          model and reports the terminal-voltage error. No data leaves for a third party; the file
          is parsed by the twin core you're already talking to.
        </p>
      </div>

      <DatasetCatalog datasets={datasets} selected={selected} onSelect={setSelected} />

      <UploadPanel
        datasets={realDatasets}
        selected={selected}
        busy={busy === "upload"}
        onValidate={runUpload}
      />

      <div className="rounded-lg bg-surface border border-hairline px-5 py-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">No download handy?</h3>
          <p className="text-xs text-muted mt-0.5">
            Run the pipeline on a bundled <span className="text-ink">synthetic</span> sample matched
            to {selectedSpec ? selectedSpec.name : "the selected dataset"}'s chemistry.
          </p>
        </div>
        <button
          type="button"
          onClick={runDemo}
          disabled={busy !== "" || !selected}
          className="rounded-md border border-hairline px-3 py-1.5 text-sm font-medium text-ink-secondary hover:text-ink hover:bg-surface-2 focus:outline-none focus:ring-1 focus:ring-series disabled:opacity-50"
        >
          {busy === "demo" ? "Running…" : "Run synthetic demo"}
        </button>
      </div>

      {error && (
        <div className="rounded-md border border-critical/40 bg-surface px-4 py-3 text-sm text-critical">
          {error}
        </div>
      )}

      {report && (
        <div className="rounded-lg bg-surface border border-hairline px-5 py-4">
          <ReportPanel report={report} selectedSpec={selectedSpec} />
        </div>
      )}
    </div>
  );
}

function UploadPanel({
  datasets,
  selected,
  busy,
  onValidate,
}: {
  datasets: DatasetSpec[];
  selected: string | null;
  busy: boolean;
  onValidate: (file: File, opts: UploadOptions) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [choice, setChoice] = useState<string>(GENERIC);
  const [chemistry, setChemistry] = useState<string>("");
  const [timeCol, setTimeCol] = useState("time_s");
  const [currentCol, setCurrentCol] = useState("current_a");
  const [voltageCol, setVoltageCol] = useState("voltage_v");
  const [tempCol, setTempCol] = useState("temperature_c");
  const [dischargePositive, setDischargePositive] = useState(true);
  const [currentScale, setCurrentScale] = useState(1);
  const [capacity, setCapacity] = useState(5);

  // Default the dataset choice to the selected catalog card when it's a real dataset.
  useEffect(() => {
    if (selected && datasets.some((d) => d.id === selected)) setChoice(selected);
  }, [selected, datasets]);

  const chosenSpec = datasets.find((d) => d.id === choice) ?? null;
  const showColumns = choice === GENERIC || chosenSpec?.loader === "generic_csv";

  const submit = () => {
    if (!file) return;
    const opts: UploadOptions = {
      fit: true,
      datasetId: choice === GENERIC ? undefined : choice,
      chemistry: chemistry || undefined,
    };
    if (showColumns) {
      opts.timeCol = timeCol;
      opts.currentCol = currentCol;
      opts.voltageCol = voltageCol;
      opts.tempCol = tempCol || undefined;
      opts.dischargePositive = dischargePositive;
      opts.currentScale = currentScale;
      opts.nominalCapacityAh = capacity;
    }
    onValidate(file, opts);
  };

  return (
    <div className="rounded-lg bg-surface border border-hairline px-5 py-4 flex flex-col gap-3">
      <div>
        <h3 className="text-sm font-semibold text-ink">Validate your own dataset</h3>
        <p className="text-xs text-muted mt-0.5">
          Upload a CSV you downloaded (or a <code>.mat</code> for NASA / Oxford, if the twin core
          was built with SciPy). Pick its format below.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col gap-1 text-xs text-ink-secondary">
          File
          <input
            type="file"
            accept=".csv,.txt,.mat"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-xs text-ink file:mr-2 file:rounded file:border-0 file:bg-surface-2 file:px-2 file:py-1 file:text-ink"
          />
        </label>

        <label className="flex flex-col gap-1 text-xs text-ink-secondary">
          Format
          <select
            value={choice}
            onChange={(e) => setChoice(e.target.value)}
            className="bg-surface-2 border border-hairline rounded-md px-2 py-1 text-ink text-sm focus:outline-none focus:ring-1 focus:ring-series"
          >
            <option value={GENERIC}>Generic CSV (map columns)</option>
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} · {d.loader}
              </option>
            ))}
          </select>
        </label>

        <button
          type="button"
          onClick={submit}
          disabled={busy || !file}
          className="rounded-md bg-series px-3 py-1.5 text-sm font-medium text-plane hover:opacity-90 focus:outline-none focus:ring-1 focus:ring-series disabled:opacity-50"
        >
          {busy ? "Validating…" : "Validate my file"}
        </button>
      </div>

      {showColumns ? (
        <div className="flex flex-wrap items-end gap-3 pt-2 border-t border-hairline">
          <TextField label="Time col" value={timeCol} onChange={setTimeCol} />
          <TextField label="Current col" value={currentCol} onChange={setCurrentCol} />
          <TextField label="Voltage col" value={voltageCol} onChange={setVoltageCol} />
          <TextField label="Temp col (opt.)" value={tempCol} onChange={setTempCol} />
          <label className="flex flex-col gap-1 text-xs text-ink-secondary">
            Chemistry
            <select
              value={chemistry}
              onChange={(e) => setChemistry(e.target.value)}
              className="bg-surface-2 border border-hairline rounded-md px-2 py-1 text-ink text-sm w-24 focus:outline-none focus:ring-1 focus:ring-series"
            >
              {CHEMISTRIES.map((c) => (
                <option key={c} value={c}>
                  {c || "auto"}
                </option>
              ))}
            </select>
          </label>
          <NumField label="Capacity (Ah)" value={capacity} onChange={setCapacity} step={0.1} />
          <NumField label="Current ×" value={currentScale} onChange={setCurrentScale} step={0.001} />
          <label className="flex items-center gap-1.5 text-xs text-ink-secondary pb-1">
            <input
              type="checkbox"
              checked={dischargePositive}
              onChange={(e) => setDischargePositive(e.target.checked)}
            />
            Discharge is positive
          </label>
        </div>
      ) : (
        <p className="text-xs text-muted pt-2 border-t border-hairline">
          Parsed by the built-in <span className="text-ink">{chosenSpec?.loader}</span> reader —
          no column mapping needed.
        </p>
      )}
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-ink-secondary">
      {label}
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-surface-2 border border-hairline rounded-md px-2 py-1 text-ink text-sm w-28 focus:outline-none focus:ring-1 focus:ring-series"
      />
    </label>
  );
}

function NumField({
  label,
  value,
  onChange,
  step,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step: number;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-ink-secondary">
      {label}
      <input
        type="number"
        value={value}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        className="bg-surface-2 border border-hairline rounded-md px-2 py-1 text-ink text-sm w-24 focus:outline-none focus:ring-1 focus:ring-series"
      />
    </label>
  );
}

function ReportPanel({
  report,
  selectedSpec,
}: {
  report: ValidationReport;
  selectedSpec: DatasetSpec | null;
}) {
  const isUpload = report.data_source === "user-upload";
  const ranForReal = !isUpload && report.requested_dataset_id !== report.sample_dataset_id;

  return (
    <div className="flex flex-col gap-3">
      {/* Honest banner: what actually ran. */}
      {isUpload ? (
        <div
          className="rounded-md px-3 py-2 text-xs"
          style={{ backgroundColor: "#0ca30c1a", color: "#c9c7c1" }}
        >
          Validated your file{" "}
          <span className="text-ink">{report.filename ?? "upload"}</span> against the{" "}
          <span className="text-ink">{report.ocv_curve}</span> OCV curve — real measured data,
          replayed through Simura's model.
        </div>
      ) : (
        <div
          className="rounded-md px-3 py-2 text-xs"
          style={{ backgroundColor: "#9085e91a", color: "#c9c7c1" }}
        >
          {ranForReal ? (
            <>
              This ran on the bundled <span className="text-ink">synthetic {report.chemistry}</span>{" "}
              sample (matched to the dataset's chemistry, validated with the{" "}
              <span className="text-ink">{report.ocv_curve}</span> OCV curve) — not{" "}
              <span className="text-ink">
                {selectedSpec?.name ?? report.requested_dataset_id}
              </span>
              . Upload your download above to validate that dataset for real.
            </>
          ) : (
            <>
              Ran on the bundled <span className="text-ink">synthetic</span> sample — generated by
              Simura's own simulator, not measured data.
            </>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatTile label="RMSE (nominal)" value={mv(report.metrics.rmse)} unit="mV" />
        <StatTile label="MAE" value={mv(report.metrics.mae)} unit="mV" />
        <StatTile label="Max error" value={mv(report.metrics.max_abs_err)} unit="mV" />
        <StatTile
          label="RMSE (best-fit R0)"
          value={report.fitted ? mv(report.fitted.metrics.rmse) : "—"}
          unit="mV"
        />
      </div>

      <OverlayChart report={report} />

      <div className="text-xs text-muted flex flex-wrap gap-x-6 gap-y-1">
        <span>
          Cell {report.cell_id} · {report.chemistry} · {report.n_samples} samples over{" "}
          {report.duration_s.toFixed(0)} s
        </span>
        <span>OCV curve: {report.ocv_curve}</span>
        <span>
          Nominal R0 {(report.params.r0_ohm * 1000).toFixed(0)} mΩ
          {report.fitted && <> · best-fit R0 {(report.fitted.r0_ohm * 1000).toFixed(0)} mΩ</>}
        </span>
      </div>
      {report.notes && <div className="text-xs text-ink-secondary">{report.notes}</div>}
    </div>
  );
}

function OverlayChart({ report }: { report: ValidationReport }) {
  const { t, v_measured, v_model, v_model_fitted } = report.overlay;
  const data = useMemo(
    () =>
      t.map((tt, i) => ({
        t: tt,
        measured: v_measured[i],
        model: v_model[i],
        fitted: v_model_fitted ? v_model_fitted[i] : undefined,
      })),
    [t, v_measured, v_model, v_model_fitted]
  );

  return (
    <div className="rounded-lg bg-surface-2 border border-hairline p-4">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-semibold text-ink">Terminal voltage — measured vs model</h4>
        <div className="flex items-center gap-3 text-xs">
          <LegendDot color="#e8e6e0" label="measured" />
          <LegendDot color="#3987e5" label="model" />
          {v_model_fitted && <LegendDot color="#0ca30c" label="best-fit" />}
        </div>
      </div>
      <div style={{ width: "100%", height: 240 }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
            <CartesianGrid stroke="#2c2c2a" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(v) => `${Math.round(v)}s`}
              tick={{ fill: "#898781", fontSize: 11 }}
              stroke="#383835"
              minTickGap={40}
            />
            <YAxis
              domain={["auto", "auto"]}
              tick={{ fill: "#898781", fontSize: 11 }}
              stroke="#383835"
              width={44}
              tickFormatter={(v) => v.toFixed(2)}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#232322",
                border: "1px solid rgba(255,255,255,0.10)",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: "#898781" }}
              itemStyle={{ color: "#ffffff" }}
              labelFormatter={(v) => `${Math.round(v as number)} s`}
              formatter={(value: number, name: string) => [`${value.toFixed(3)} V`, name]}
            />
            <Line
              type="monotone"
              dataKey="measured"
              stroke="#e8e6e0"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="model"
              stroke="#3987e5"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            {v_model_fitted && (
              <Line
                type="monotone"
                dataKey="fitted"
                stroke="#0ca30c"
                strokeWidth={2}
                strokeDasharray="4 3"
                dot={false}
                isAnimationActive={false}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-muted">
      <span className="h-2 w-3 rounded-sm" style={{ backgroundColor: color }} />
      {label}
    </span>
  );
}

function mv(volts: number): string {
  return (volts * 1000).toFixed(1);
}
