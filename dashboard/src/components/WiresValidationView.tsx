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
import { fetchWireStandards, runWireValidation, uploadWireValidation } from "../api/client";
import type { WireStandardSpec, WireUploadOptions, WireValidationReport } from "../api/types";
import StatTile from "./StatTile";

const MATERIALS = ["copper", "aluminum", "tinned_copper"];
const UNITS = ["ohm/km", "mohm/m", "ohm/1000ft"];

function awgLabel(awg: number): string {
  return awg <= 0 ? `${1 - awg}/0` : String(awg);
}

// The Wires validation view: check the simura.wires conductor model against
// published DC-resistance standards (annealed copper, hard-drawn aluminium), or
// against the user's own measured-resistance CSV. The parallel to the battery
// ValidationView — replay a reference through the same physics the twin uses and
// report the error.
export default function WiresValidationView() {
  const [standards, setStandards] = useState<WireStandardSpec[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [report, setReport] = useState<WireValidationReport | null>(null);
  const [busy, setBusy] = useState<"" | "run" | "upload">("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchWireStandards()
      .then((s) => {
        setStandards(s);
        setSelected((cur) => cur ?? s[0]?.id ?? null);
      })
      .catch((e) => setError(String(e)));
  }, []);

  const selectedSpec = standards.find((s) => s.id === selected) ?? null;

  const runStandard = () => {
    if (!selected) return;
    setBusy("run");
    setError(null);
    runWireValidation(selected)
      .then(setReport)
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(""));
  };

  const runUpload = (file: File, opts: WireUploadOptions) => {
    setBusy("upload");
    setError(null);
    uploadWireValidation(file, opts)
      .then(setReport)
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(""));
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg bg-surface border border-hairline px-5 py-4">
        <h2 className="text-lg font-semibold text-ink">Validate against conductor standards</h2>
        <p className="text-sm text-ink-secondary mt-1 max-w-3xl">
          Check the <span className="text-ink">simura.wires</span> physics against published
          DC-resistance standards. Simura builds each gauge with the same conductor model the twin
          uses, then compares its predicted resistance to the standard's value. The reference tables
          are bundled and computed offline, so this runs without any download —{" "}
          <span className="text-ink">upload your own measured resistances</span> below to validate
          against them instead.
        </p>
      </div>

      <StandardsCatalog standards={standards} selected={selected} onSelect={setSelected} />

      <div className="rounded-lg bg-surface border border-hairline px-5 py-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">Run the check</h3>
          <p className="text-xs text-muted mt-0.5">
            Replay {selectedSpec ? selectedSpec.name : "the selected standard"} through the wire
            model and report the per-gauge resistance error.
          </p>
        </div>
        <button
          type="button"
          onClick={runStandard}
          disabled={busy !== "" || !selected}
          className="rounded-md bg-series px-3 py-1.5 text-sm font-medium text-plane hover:opacity-90 focus:outline-none focus:ring-1 focus:ring-series disabled:opacity-50"
        >
          {busy === "run" ? "Running…" : "Validate against standard"}
        </button>
      </div>

      <UploadPanel busy={busy === "upload"} onValidate={runUpload} />

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

function StandardsCatalog({
  standards,
  selected,
  onSelect,
}: {
  standards: WireStandardSpec[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  if (standards.length === 0) return <div className="text-muted">Loading standards…</div>;
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {standards.map((s) => {
        const active = s.id === selected;
        return (
          <button
            key={s.id}
            type="button"
            onClick={() => onSelect(s.id)}
            aria-pressed={active}
            className={`text-left rounded-lg bg-surface border px-4 py-3 flex flex-col gap-2 transition-colors hover:bg-surface-2 focus:outline-none focus:ring-1 focus:ring-series ${
              active ? "border-series" : "border-hairline"
            }`}
          >
            <div className="flex items-start justify-between gap-2">
              <span className="text-sm font-semibold text-ink">{s.name}</span>
              <span className="text-[10px] uppercase tracking-wide rounded px-1.5 py-0.5 text-ink-secondary bg-surface-2 border border-hairline shrink-0">
                {s.material}
              </span>
            </div>
            <div className="text-xs text-muted">{s.institution}</div>
            <ul className="text-xs text-ink-secondary list-disc pl-4 space-y-0.5">
              {s.what_it_validates.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
            <div className="text-[11px] text-muted mt-auto pt-2 border-t border-hairline flex flex-wrap gap-x-3">
              <span>{s.n_points} gauges</span>
              <span>{s.ref_temp_c.toFixed(0)} °C</span>
              <span>{s.license}</span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function UploadPanel({
  busy,
  onValidate,
}: {
  busy: boolean;
  onValidate: (file: File, opts: WireUploadOptions) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [material, setMaterial] = useState("copper");
  const [awgCol, setAwgCol] = useState("awg");
  const [resistanceCol, setResistanceCol] = useState("resistance_ohm_per_km");
  const [refTempC, setRefTempC] = useState(20);
  const [unit, setUnit] = useState("ohm/km");

  const submit = () => {
    if (!file) return;
    onValidate(file, {
      material,
      awgCol,
      resistanceCol,
      refTempC,
      resistanceUnit: unit,
    });
  };

  return (
    <div className="rounded-lg bg-surface border border-hairline px-5 py-4 flex flex-col gap-3">
      <div>
        <h3 className="text-sm font-semibold text-ink">Validate your own measurements</h3>
        <p className="text-xs text-muted mt-0.5">
          Upload a CSV with an <span className="text-ink">AWG</span> column and a{" "}
          <span className="text-ink">DC-resistance</span> column (bench-measured or from a datasheet).
          Rows whose gauge isn't a standard AWG size are skipped.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col gap-1 text-xs text-ink-secondary">
          File
          <input
            type="file"
            accept=".csv,.txt"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-xs text-ink file:mr-2 file:rounded file:border-0 file:bg-surface-2 file:px-2 file:py-1 file:text-ink"
          />
        </label>

        <label className="flex flex-col gap-1 text-xs text-ink-secondary">
          Material
          <select
            value={material}
            onChange={(e) => setMaterial(e.target.value)}
            className="bg-surface-2 border border-hairline rounded-md px-2 py-1 text-ink text-sm focus:outline-none focus:ring-1 focus:ring-series"
          >
            {MATERIALS.map((m) => (
              <option key={m} value={m}>
                {m}
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

      <div className="flex flex-wrap items-end gap-3 pt-2 border-t border-hairline">
        <TextField label="AWG col" value={awgCol} onChange={setAwgCol} />
        <TextField label="Resistance col" value={resistanceCol} onChange={setResistanceCol} />
        <label className="flex flex-col gap-1 text-xs text-ink-secondary">
          Resistance unit
          <select
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            className="bg-surface-2 border border-hairline rounded-md px-2 py-1 text-ink text-sm focus:outline-none focus:ring-1 focus:ring-series"
          >
            {UNITS.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        </label>
        <NumField label="Ref temp (°C)" value={refTempC} onChange={setRefTempC} step={1} />
      </div>
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
        className="bg-surface-2 border border-hairline rounded-md px-2 py-1 text-ink text-sm w-40 focus:outline-none focus:ring-1 focus:ring-series"
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
  report: WireValidationReport;
  selectedSpec: WireStandardSpec | null;
}) {
  const isUpload = report.data_source === "user-upload";
  const biasLevel = Math.abs(report.metrics.mean_bias_pct) > 8 ? "warning" : "good";
  const maxLevel = report.metrics.max_abs_pct > 10 ? "warning" : "good";

  return (
    <div className="flex flex-col gap-3">
      {isUpload ? (
        <div className="rounded-md px-3 py-2 text-xs" style={{ backgroundColor: "#0ca30c1a", color: "#c9c7c1" }}>
          Validated your file <span className="text-ink">{report.filename ?? "upload"}</span> —{" "}
          {report.n_points} measured {report.material} gauges, replayed through Simura's wire model.
        </div>
      ) : (
        <div className="rounded-md px-3 py-2 text-xs" style={{ backgroundColor: "#eda1001a", color: "#c9c7c1" }}>
          Validated against{" "}
          <span className="text-ink">{selectedSpec?.name ?? report.standard_id}</span> — a bundled
          published standard ({report.material}, {report.ref_temp_c.toFixed(0)} °C), computed offline.
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatTile label="RMSE" value={report.metrics.rmse_pct.toFixed(2)} unit="%" />
        <StatTile label="MAE" value={report.metrics.mae_pct.toFixed(2)} unit="%" />
        <StatTile label="Max error" value={report.metrics.max_abs_pct.toFixed(2)} unit="%" level={maxLevel} />
        <StatTile
          label="Mean bias"
          value={report.metrics.mean_bias_pct.toFixed(2)}
          unit="%"
          level={biasLevel}
        />
      </div>

      <OverlayChart report={report} />
      <PerGaugeTable report={report} />

      <div className="text-xs text-muted flex flex-wrap gap-x-6 gap-y-1">
        <span>
          {report.material} · {report.n_points} gauges · reference {report.ref_temp_c.toFixed(0)} °C
        </span>
        <span>quantity: DC resistance ({report.unit})</span>
      </div>
      {report.notes && <div className="text-xs text-ink-secondary">{report.notes}</div>}
    </div>
  );
}

function OverlayChart({ report }: { report: WireValidationReport }) {
  const { awg, published_ohm_per_km, model_ohm_per_km } = report.overlay;
  const data = useMemo(
    () =>
      awg.map((a, i) => ({
        awg: a,
        label: awgLabel(a),
        published: published_ohm_per_km[i],
        model: model_ohm_per_km[i],
      })),
    [awg, published_ohm_per_km, model_ohm_per_km]
  );

  return (
    <div className="rounded-lg bg-surface-2 border border-hairline p-4">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-semibold text-ink">DC resistance — published vs model</h4>
        <div className="flex items-center gap-3 text-xs">
          <LegendDot color="#e8e6e0" label="published" />
          <LegendDot color="#eda100" label="model" />
        </div>
      </div>
      <div style={{ width: "100%", height: 240 }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 4 }}>
            <CartesianGrid stroke="#2c2c2a" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fill: "#898781", fontSize: 11 }}
              stroke="#383835"
              label={{ value: "AWG", position: "insideBottom", offset: -2, fill: "#898781", fontSize: 11 }}
            />
            <YAxis
              scale="log"
              domain={["auto", "auto"]}
              tick={{ fill: "#898781", fontSize: 11 }}
              stroke="#383835"
              width={52}
              tickFormatter={(v) => v.toFixed(v < 1 ? 2 : 1)}
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
              labelFormatter={(v) => `AWG ${v}`}
              formatter={(value: number, name: string) => [`${value.toFixed(3)} ${report.unit}`, name]}
            />
            <Line type="monotone" dataKey="published" stroke="#e8e6e0" strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
            <Line type="monotone" dataKey="model" stroke="#eda100" strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function PerGaugeTable({ report }: { report: WireValidationReport }) {
  const { awg, published_ohm_per_km, model_ohm_per_km, error_pct } = report.overlay;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm text-left tnums">
        <thead className="text-xs uppercase text-muted border-b border-hairline">
          <tr>
            <th className="py-1.5 pr-4 text-right">AWG</th>
            <th className="py-1.5 pr-4 text-right">Published ({report.unit})</th>
            <th className="py-1.5 pr-4 text-right">Model ({report.unit})</th>
            <th className="py-1.5 text-right">Error %</th>
          </tr>
        </thead>
        <tbody>
          {awg.map((a, i) => {
            const e = error_pct[i];
            const hot = Math.abs(e) > 10;
            return (
              <tr key={a} className="border-b border-hairline/50">
                <td className="py-1.5 pr-4 text-right text-ink">{awgLabel(a)}</td>
                <td className="py-1.5 pr-4 text-right text-ink-secondary">{published_ohm_per_km[i].toFixed(4)}</td>
                <td className="py-1.5 pr-4 text-right text-ink-secondary">{model_ohm_per_km[i].toFixed(4)}</td>
                <td className={`py-1.5 text-right ${hot ? "text-warning" : "text-ink-secondary"}`}>
                  {e >= 0 ? "+" : ""}
                  {e.toFixed(2)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
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
