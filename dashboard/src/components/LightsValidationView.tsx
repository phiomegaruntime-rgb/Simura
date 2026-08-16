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
import {
  fetchLightStandards,
  runLightValidation,
  runLiveDaylightValidation,
  searchPlaces,
  uploadLightValidation,
} from "../api/client";
import type { Place } from "../api/client";
import type {
  LightStandardSpec,
  LightUploadOptions,
  LightValidationReport,
  LiveDaylightReport,
} from "../api/types";
import StatTile from "./StatTile";
import { NumField, Row, Section, SelectField, TextField } from "./formkit";

const UPLOAD_QUANTITIES = [
  "luminous_efficacy",
  "flux_vs_junction_temp",
  "flux_vs_ambient_temp",
  "photopic_response",
];

// The Lights validation view: check the simura.lights model against published
// reference data at five different depths — from the CIE observer the whole
// package rests on, up to whole-lamp efficacy — and then against the live sky.
//
// The parallel to the battery and wire validation views, with one addition that
// neither has: a reference that is different every time you run it.
export default function LightsValidationView() {
  const [standards, setStandards] = useState<LightStandardSpec[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [report, setReport] = useState<LightValidationReport | null>(null);
  const [busy, setBusy] = useState<"" | "run" | "upload">("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchLightStandards()
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
    runLightValidation(selected)
      .then(setReport)
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(""));
  };

  const runUpload = (file: File, opts: LightUploadOptions) => {
    setBusy("upload");
    setError(null);
    uploadLightValidation(file, opts)
      .then(setReport)
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(""));
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg bg-surface border border-hairline px-5 py-4">
        <h2 className="text-lg font-semibold text-ink">Validate the lighting model</h2>
        <p className="text-sm text-ink-secondary mt-1 max-w-3xl">
          Check the <span className="text-ink">simura.lights</span> physics against published
          reference data, at five depths: the CIE observer every lumen is computed from, the colour
          maths on the Planckian locus, whole-lamp efficacy for twenty real lamps, and the two
          temperature-derating curves that run in opposite directions. The reference tables are
          bundled and computed offline, so this runs without any download — and below,{" "}
          <span className="text-ink">the live sky</span> checks the daylight model against
          irradiance measured over a real place, right now.
        </p>
      </div>

      <StandardsCatalog standards={standards} selected={selected} onSelect={setSelected} />

      <div className="rounded-lg bg-surface border border-hairline px-5 py-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">Run the check</h3>
          <p className="text-xs text-muted mt-0.5">
            Replay {selectedSpec ? selectedSpec.name : "the selected standard"} through the model
            and report the per-point error.
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

      <LiveDaylightPanel />

      <UploadPanel busy={busy === "upload"} onValidate={runUpload} />
    </div>
  );
}

function StandardsCatalog({
  standards,
  selected,
  onSelect,
}: {
  standards: LightStandardSpec[];
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
                {s.quantity.replace(/_/g, " ")}
              </span>
            </div>
            <div className="text-xs text-muted">{s.institution}</div>
            <ul className="text-xs text-ink-secondary list-disc pl-4 space-y-0.5">
              {s.what_it_validates.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
            <div className="text-[11px] text-muted mt-auto pt-2 border-t border-hairline flex flex-wrap gap-x-3">
              <span>{s.n_points} points</span>
              <span>{s.unit}</span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function ReportPanel({
  report,
  selectedSpec,
}: {
  report: LightValidationReport;
  selectedSpec: LightStandardSpec | null;
}) {
  const isUpload = report.data_source === "user-upload";
  // Percent error is the honest measure for efficacy; for a curve that passes
  // near zero (V(λ) in the far red) it is meaningless and the absolute error is
  // what matters. Both are always shown, so neither can flatter the model.
  const nearZero = report.quantity === "photopic_response";
  const biasLevel = Math.abs(report.metrics.mean_bias_pct) > 10 ? "warning" : "good";
  const maxLevel = report.metrics.max_abs_pct > 25 ? "warning" : "good";

  return (
    <div className="flex flex-col gap-3">
      {isUpload ? (
        <div className="rounded-md px-3 py-2 text-xs" style={{ backgroundColor: "#0ca30c1a", color: "#c9c7c1" }}>
          Validated your file <span className="text-ink">{report.filename ?? "upload"}</span> —{" "}
          {report.n_points} measured points, replayed through Simura's lighting model.
        </div>
      ) : (
        <div className="rounded-md px-3 py-2 text-xs" style={{ backgroundColor: "#4fc3f71a", color: "#c9c7c1" }}>
          Validated against <span className="text-ink">{selectedSpec?.name ?? report.standard_id}</span>{" "}
          — a bundled published reference, computed offline.
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatTile label="RMSE" value={fmt(report.metrics.rmse)} unit={report.unit} />
        <StatTile label="MAE" value={fmt(report.metrics.mae)} unit={report.unit} />
        <StatTile
          label={nearZero ? "Max error" : "Max error %"}
          value={nearZero ? fmt(report.metrics.max_abs) : report.metrics.max_abs_pct.toFixed(2)}
          unit={nearZero ? report.unit : "%"}
          level={maxLevel}
        />
        <StatTile
          label="Mean bias %"
          value={report.metrics.mean_bias_pct.toFixed(2)}
          unit="%"
          level={biasLevel}
        />
      </div>

      <OverlayChart report={report} />
      <PerPointTable report={report} />

      <div className="text-xs text-muted flex flex-wrap gap-x-6 gap-y-1">
        <span>
          {report.n_points} points · {report.quantity.replace(/_/g, " ")} ({report.unit})
        </span>
        <span>
          relative: RMSE {report.metrics.rmse_pct.toFixed(2)}% · MAE {report.metrics.mae_pct.toFixed(2)}%
        </span>
      </div>
      {report.notes && <div className="text-xs text-ink-secondary">{report.notes}</div>}
    </div>
  );
}

function OverlayChart({ report }: { report: LightValidationReport }) {
  const { x, published, model, key } = report.overlay;
  const data = useMemo(
    () =>
      x.map((xv, i) => ({
        x: xv,
        label: key[i],
        published: published[i],
        model: model[i],
      })),
    [x, published, model, key]
  );
  // Efficacy spans an order of magnitude across the lamp catalog, and lamps are
  // not ordered by anything meaningful, so index the axis by label there.
  const categorical = report.quantity === "luminous_efficacy";

  return (
    <div className="rounded-lg bg-surface-2 border border-hairline p-4">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-semibold text-ink">
          {report.quantity.replace(/_/g, " ")} — published vs model
        </h4>
        <div className="flex items-center gap-3 text-xs">
          <LegendDot color="#e8e6e0" label="published" />
          <LegendDot color="#4fc3f7" label="model" />
        </div>
      </div>
      <div style={{ width: "100%", height: 240 }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 4 }}>
            <CartesianGrid stroke="#2c2c2a" vertical={false} />
            <XAxis
              dataKey={categorical ? "label" : "x"}
              type={categorical ? "category" : "number"}
              domain={categorical ? undefined : ["dataMin", "dataMax"]}
              tick={{ fill: "#898781", fontSize: categorical ? 9 : 11 }}
              stroke="#383835"
              angle={categorical ? -35 : 0}
              textAnchor={categorical ? "end" : "middle"}
              height={categorical ? 68 : 28}
              interval={0}
              label={
                categorical
                  ? undefined
                  : {
                      value: `${report.x_label} (${report.x_unit})`,
                      position: "insideBottom",
                      offset: -2,
                      fill: "#898781",
                      fontSize: 11,
                    }
              }
            />
            <YAxis
              domain={["auto", "auto"]}
              tick={{ fill: "#898781", fontSize: 11 }}
              stroke="#383835"
              width={56}
              tickFormatter={(v) => fmt(v)}
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
              formatter={(value: number, name: string) => [`${fmt(value)} ${report.unit}`, name]}
            />
            <Line
              type="monotone"
              dataKey="published"
              stroke="#e8e6e0"
              strokeWidth={2}
              dot={{ r: 2 }}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="model"
              stroke="#4fc3f7"
              strokeWidth={2}
              dot={{ r: 2 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function PerPointTable({ report }: { report: LightValidationReport }) {
  const { key, published, model, error, error_pct } = report.overlay;
  return (
    <div className="overflow-x-auto max-h-96">
      <table className="w-full text-sm text-left tnums">
        <thead className="text-xs uppercase text-muted border-b border-hairline sticky top-0 bg-surface">
          <tr>
            <th className="py-1.5 pr-4">{report.x_label}</th>
            <th className="py-1.5 pr-4 text-right">Published</th>
            <th className="py-1.5 pr-4 text-right">Model</th>
            <th className="py-1.5 pr-4 text-right">Error</th>
            <th className="py-1.5 text-right">Error %</th>
          </tr>
        </thead>
        <tbody>
          {key.map((k, i) => {
            const hot = Math.abs(error_pct[i]) > 20;
            return (
              <tr key={k} className="border-b border-hairline/50">
                <td className="py-1.5 pr-4 text-ink">{k}</td>
                <td className="py-1.5 pr-4 text-right text-ink-secondary">{fmt(published[i])}</td>
                <td className="py-1.5 pr-4 text-right text-ink-secondary">{fmt(model[i])}</td>
                <td className="py-1.5 pr-4 text-right text-ink-secondary">
                  {error[i] >= 0 ? "+" : ""}
                  {fmt(error[i])}
                </td>
                <td className={`py-1.5 text-right ${hot ? "text-warning" : "text-ink-secondary"}`}>
                  {error_pct[i] >= 0 ? "+" : ""}
                  {error_pct[i].toFixed(2)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// The live check. Unlike every other validation in Simura, this one's reference
// data does not ship with the repository — it is fetched from Open-Meteo at the
// moment you press the button, for a place you choose.
function LiveDaylightPanel() {
  const [query, setQuery] = useState("");
  const [places, setPlaces] = useState<Place[]>([]);
  const [lat, setLat] = useState(51.5074);
  const [lon, setLon] = useState(-0.1278);
  const [label, setLabel] = useState("London, United Kingdom");
  const [hours, setHours] = useState(48);
  const [report, setReport] = useState<LiveDaylightReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const lookup = () => {
    if (!query.trim()) return;
    searchPlaces(query).then(setPlaces);
  };

  const run = () => {
    setBusy(true);
    setError(null);
    runLiveDaylightValidation(lat, lon, hours)
      .then(setReport)
      .catch((e) => setError(String(e?.message ?? e)))
      .finally(() => setBusy(false));
  };

  return (
    <Section title="Live sky — validate against measured irradiance">
      <p className="text-xs text-muted -mt-1 max-w-3xl">
        The daylight model is three steps of pure physics with nothing fitted: solar geometry from
        the date and place, the Haurwitz clear-sky irradiance model, and the 110 lm/W luminous
        efficacy of daylight. Open-Meteo reports what the sky actually delivered over the same hours,
        with no API key. Comparing them tests whether the geometry and that constant are right.
      </p>
      <p className="text-xs text-muted max-w-3xl">
        <span className="text-ink-secondary">Read it honestly:</span> a clear-sky model cannot know
        about clouds, so on an overcast day it over-predicts badly — and that is the definition of
        the model, not a defect. Judge it on the{" "}
        <span className="text-ink">clear-hour</span> figures and the envelope violations. The
        all-hours error measures how cloudy the window was.
      </p>

      <Row>
        <TextField label="Find a place" value={query} onChange={setQuery} />
        <button
          type="button"
          onClick={lookup}
          className="rounded-md border border-hairline px-3 py-1.5 text-sm text-ink-secondary hover:text-ink hover:bg-surface-2 focus:outline-none focus:ring-1 focus:ring-series"
        >
          Search
        </button>
        <NumField label="Latitude" value={lat} step={0.1} onChange={setLat} />
        <NumField label="Longitude" value={lon} step={0.1} onChange={setLon} />
        <NumField
          label="Window (h)"
          value={hours}
          step={12}
          onChange={(v) => setHours(Math.max(6, Math.min(240, Math.round(v))))}
        />
        <button
          type="button"
          onClick={run}
          disabled={busy}
          className="rounded-md bg-series px-3 py-1.5 text-sm font-medium text-plane hover:opacity-90 focus:outline-none focus:ring-1 focus:ring-series disabled:opacity-50"
        >
          {busy ? "Fetching the sky…" : "Validate against the live sky"}
        </button>
      </Row>

      {places.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {places.slice(0, 6).map((p) => (
            <button
              key={`${p.latitude},${p.longitude}`}
              type="button"
              onClick={() => {
                setLat(p.latitude);
                setLon(p.longitude);
                setLabel(p.label);
                setPlaces([]);
              }}
              className="text-xs rounded px-2 py-1 text-ink-secondary bg-surface-2 border border-hairline hover:text-ink"
            >
              {p.label}
            </button>
          ))}
        </div>
      )}

      <div className="text-xs text-muted">
        Validating over <span className="text-ink-secondary">{label}</span> ({lat.toFixed(3)},{" "}
        {lon.toFixed(3)})
      </div>

      {error && <div className="text-sm text-critical">{error}</div>}

      {report && <LiveReport report={report} />}
    </Section>
  );
}

function LiveReport({ report }: { report: LiveDaylightReport }) {
  const m = report.metrics;
  const data = useMemo(
    () =>
      report.overlay.timestamp.map((ts, i) => ({
        t: ts * 1000,
        measured: report.overlay.measured_lux[i],
        model: report.overlay.model_lux[i],
        kt: report.overlay.clearness_index[i],
      })),
    [report]
  );
  const clearBias = m.clear_mean_bias_pct ?? 0;
  const biasLevel = Math.abs(clearBias) > 20 ? "warning" : "good";

  return (
    <div className="flex flex-col gap-3 pt-2 border-t border-hairline">
      <div className="rounded-md px-3 py-2 text-xs" style={{ backgroundColor: "#4fc3f71a", color: "#c9c7c1" }}>
        {report.n_hours} daylight hours from <span className="text-ink">{report.source}</span>,{" "}
        {report.n_clear_hours} of them clear (mean clearness index{" "}
        {(m.mean_clearness_index ?? 0).toFixed(2)}).
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatTile
          label="Clear-hour RMSE"
          value={(m.clear_rmse_pct ?? 0).toFixed(1)}
          unit="%"
          level={(m.clear_rmse_pct ?? 0) > 25 ? "warning" : "good"}
        />
        <StatTile
          label="Clear-hour bias"
          value={clearBias.toFixed(1)}
          unit="%"
          level={biasLevel}
        />
        <StatTile label="All-hours RMSE" value={(m.rmse_pct ?? 0).toFixed(1)} unit="%" />
        <StatTile
          label="Envelope violations"
          value={String(report.envelope_violations)}
          level={report.envelope_violations > report.n_hours * 0.15 ? "warning" : "good"}
        />
      </div>

      <div className="rounded-lg bg-surface-2 border border-hairline p-4">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-sm font-semibold text-ink">Daylight illuminance — measured vs model</h4>
          <div className="flex items-center gap-3 text-xs">
            <LegendDot color="#e8e6e0" label="measured" />
            <LegendDot color="#4fc3f7" label="clear-sky model" />
          </div>
        </div>
        <div style={{ width: "100%", height: 240 }}>
          <ResponsiveContainer>
            <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 4 }}>
              <CartesianGrid stroke="#2c2c2a" vertical={false} />
              <XAxis
                dataKey="t"
                type="number"
                domain={["dataMin", "dataMax"]}
                tick={{ fill: "#898781", fontSize: 11 }}
                stroke="#383835"
                tickFormatter={(v) =>
                  new Date(v).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                }
                minTickGap={48}
              />
              <YAxis
                tick={{ fill: "#898781", fontSize: 11 }}
                stroke="#383835"
                width={62}
                tickFormatter={(v) => `${Math.round(v / 1000)}k`}
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
                labelFormatter={(v) => new Date(v as number).toLocaleString()}
                formatter={(value: number, name: string) => [
                  `${Math.round(value).toLocaleString()} lux`,
                  name,
                ]}
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
                stroke="#4fc3f7"
                strokeWidth={2}
                strokeDasharray="4 3"
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="text-xs text-muted">
        Where the two curves meet, the sky was clear and the model is being tested. Where the solid
        line dips below the dashed one, that is cloud — the gap is weather, not error.
      </div>
    </div>
  );
}

function UploadPanel({
  busy,
  onValidate,
}: {
  busy: boolean;
  onValidate: (file: File, opts: LightUploadOptions) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [quantity, setQuantity] = useState("luminous_efficacy");
  const [xCol, setXCol] = useState("x");
  const [valueCol, setValueCol] = useState("value");
  const [keyCol, setKeyCol] = useState("lamp_id");

  const needsKey = quantity === "luminous_efficacy";

  return (
    <Section title="Validate your own measurements">
      <p className="text-xs text-muted -mt-1 max-w-3xl">
        Upload a CSV from an integrating sphere, a lux meter, or a stack of datasheets. For{" "}
        <span className="text-ink">luminous efficacy</span> the file needs a column of catalog lamp
        ids, since the model has to build the same lamp to predict against. Relative curves are
        renormalised to 1.0 at their reference temperature, so a file normalised at 40 °C is not
        reported as error against a model normalised at 25 °C.
      </p>

      <Row>
        <label className="flex flex-col gap-1 text-xs text-ink-secondary">
          File
          <input
            type="file"
            accept=".csv,.txt"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-xs text-ink file:mr-2 file:rounded file:border-0 file:bg-surface-2 file:px-2 file:py-1 file:text-ink"
          />
        </label>
        <SelectField
          label="Quantity"
          value={quantity}
          options={UPLOAD_QUANTITIES}
          onChange={setQuantity}
        />
        <button
          type="button"
          onClick={() =>
            file &&
            onValidate(file, {
              quantity,
              xCol,
              valueCol,
              keyCol: needsKey ? keyCol : undefined,
            })
          }
          disabled={busy || !file}
          className="rounded-md bg-series px-3 py-1.5 text-sm font-medium text-plane hover:opacity-90 focus:outline-none focus:ring-1 focus:ring-series disabled:opacity-50"
        >
          {busy ? "Validating…" : "Validate my file"}
        </button>
      </Row>

      <Row>
        <TextField label="X column" value={xCol} onChange={setXCol} />
        <TextField label="Value column" value={valueCol} onChange={setValueCol} />
        {needsKey && <TextField label="Lamp-id column" value={keyCol} onChange={setKeyCol} />}
      </Row>
    </Section>
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

// Lighting quantities span from 0.0004 (V(λ) in the far red) to 48000 (lumens
// from a sodium lamp), so a fixed precision would be wrong nearly everywhere.
function fmt(v: number): string {
  const abs = Math.abs(v);
  if (abs === 0) return "0";
  if (abs >= 1000) return v.toFixed(0);
  if (abs >= 10) return v.toFixed(1);
  if (abs >= 1) return v.toFixed(2);
  if (abs >= 0.01) return v.toFixed(4);
  return v.toExponential(2);
}
