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
import { createSystem, fetchBuilderOptions, previewSpec } from "../api/client";
import type { PreviewError } from "../api/client";
import type { BuilderOptions, FaultSpec, PreviewResult, SystemSpec } from "../api/types";
import StatTile from "./StatTile";

// Build view: describe your own battery system, preview it offline, then either
// start it live in the fleet (twin-core-run) or export the spec + copy the
// one-line publisher command.
export default function BuildView({ onStarted }: { onStarted?: () => void }) {
  const [options, setOptions] = useState<BuilderOptions | null>(null);
  const [spec, setSpec] = useState<SystemSpec | null>(null);
  const [result, setResult] = useState<PreviewResult | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    fetchBuilderOptions()
      .then((o) => {
        setOptions(o);
        setSpec(o.default_spec);
      })
      .catch((e) => setLoadError(String(e)));
  }, []);

  if (loadError)
    return <div className="text-sm text-critical">Couldn't load builder options: {loadError}</div>;
  if (!options || !spec)
    return <div className="text-muted">Loading builder…</div>;

  const set = (patch: Partial<SystemSpec>) => setSpec({ ...spec, ...patch });

  const runPreview = () => {
    setBusy(true);
    setErrors([]);
    previewSpec(spec)
      .then((r) => {
        setResult(r);
        setErrors([]);
      })
      .catch((e: PreviewError | Error) => {
        setResult(null);
        setErrors("errors" in e ? e.errors : [String(e)]);
      })
      .finally(() => setBusy(false));
  };

  const startInFleet = () => {
    if (!spec) return;
    setBusy(true);
    setErrors([]);
    createSystem({ source: "simulation", spec, autostart: true })
      .then(() => onStarted?.())
      .catch((e: PreviewError | Error) => setErrors("errors" in e ? e.errors : [String(e)]))
      .finally(() => setBusy(false));
  };

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(spec, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${spec.system_id || "system"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const goLiveCmd = `python -m celltwin.publisher --spec ${spec.system_id || "system"}.json --speed 10 --loop`;

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg bg-surface border border-hairline px-5 py-4">
        <h2 className="text-lg font-semibold text-ink">Build your own system</h2>
        <p className="text-sm text-ink-secondary mt-1 max-w-3xl">
          Describe a battery system — chemistry, topology, load profile, faults — and{" "}
          <span className="text-ink">preview it offline</span> in the browser. When it behaves the
          way you want, export the spec and stream it live into the twin with one command.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Identity + topology */}
        <Section title="System">
          <Row>
            <TextField label="System ID" value={spec.system_id} onChange={(v) => set({ system_id: v })} />
            <TextField label="Name" value={spec.name} onChange={(v) => set({ name: v })} />
          </Row>
          <Row>
            <SelectField
              label="Chemistry"
              value={spec.chemistry}
              options={options.chemistries}
              onChange={(v) => set({ chemistry: v })}
            />
            <NumField label="Series (S)" value={spec.series} step={1} onChange={(v) => set({ series: Math.round(v) })} />
            <NumField label="Parallel (P)" value={spec.parallel} step={1} onChange={(v) => set({ parallel: Math.round(v) })} />
          </Row>
          <Row>
            <NumField label="Initial SoC" value={spec.initial_soc} step={0.01} onChange={(v) => set({ initial_soc: v })} />
            <NumField label="Ambient °C" value={spec.ambient_temp_c} step={1} onChange={(v) => set({ ambient_temp_c: v })} />
            <NumField label="Temp limit °C" value={spec.temp_max_c} step={1} onChange={(v) => set({ temp_max_c: v })} />
          </Row>
        </Section>

        {/* Cell + sim */}
        <Section title="Cell & simulation">
          <Row>
            <NumField label="Capacity (Ah)" value={spec.capacity_ah} step={0.1} onChange={(v) => set({ capacity_ah: v })} />
            <NumField label="R0 (Ω)" value={spec.r0_ohm} step={0.001} onChange={(v) => set({ r0_ohm: v })} />
          </Row>
          <Row>
            <NumField label="dt (s)" value={spec.dt_s} step={0.1} onChange={(v) => set({ dt_s: v })} />
            <NumField label="Duration (s)" value={spec.duration_s} step={60} onChange={(v) => set({ duration_s: v })} />
          </Row>
          <p className="text-xs text-muted">
            {spec.dt_s > 0 ? Math.round(spec.duration_s / spec.dt_s) : 0} steps · {spec.series}S
            {spec.parallel}P = {spec.series * spec.parallel} cells
          </p>
        </Section>
      </div>

      <ProfileEditor spec={spec} options={options} onChange={set} />
      <FaultsEditor spec={spec} options={options} onChange={set} />

      {/* Actions */}
      <div className="rounded-lg bg-surface border border-hairline px-5 py-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={runPreview}
          disabled={busy}
          className="rounded-md bg-series px-3 py-1.5 text-sm font-medium text-plane hover:opacity-90 focus:outline-none focus:ring-1 focus:ring-series disabled:opacity-50"
        >
          {busy ? "Running…" : "Preview offline"}
        </button>
        <button
          type="button"
          onClick={startInFleet}
          disabled={busy}
          className="rounded-md border border-series px-3 py-1.5 text-sm font-medium text-series hover:bg-surface-2 focus:outline-none focus:ring-1 focus:ring-series disabled:opacity-50"
          title="Create + start this simulation in the fleet (twin-core-run, controllable)"
        >
          ▶ Start in fleet
        </button>
        <button
          type="button"
          onClick={exportJson}
          className="rounded-md border border-hairline px-3 py-1.5 text-sm text-ink-secondary hover:text-ink hover:bg-surface-2 focus:outline-none focus:ring-1 focus:ring-series"
        >
          Export spec JSON
        </button>
        <CopyButton text={goLiveCmd} label="Copy go-live command" />
      </div>

      {errors.length > 0 && (
        <div className="rounded-md border border-critical/40 bg-surface px-4 py-3 text-sm text-critical">
          <div className="font-medium mb-1">Fix these before running:</div>
          <ul className="list-disc pl-5 space-y-0.5">
            {errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {result && <PreviewPanel result={result} goLiveCmd={goLiveCmd} />}
    </div>
  );
}

function ProfileEditor({
  spec,
  options,
  onChange,
}: {
  spec: SystemSpec;
  options: BuilderOptions;
  onChange: (patch: Partial<SystemSpec>) => void;
}) {
  const params = options.profile_params[spec.profile.type] ?? {};
  const setType = (type: string) =>
    onChange({ profile: { type, params: { ...(options.profile_params[type] ?? {}) } } });
  const setParam = (k: string, v: number) =>
    onChange({ profile: { ...spec.profile, params: { ...spec.profile.params, [k]: v } } });

  return (
    <Section title="Load profile">
      <Row>
        <SelectField label="Type" value={spec.profile.type} options={options.profile_types} onChange={setType} />
        {Object.keys(params).map((k) => (
          <NumField
            key={k}
            label={k}
            value={Number(spec.profile.params[k] ?? params[k])}
            step={0.1}
            onChange={(v) => setParam(k, v)}
          />
        ))}
      </Row>
    </Section>
  );
}

function FaultsEditor({
  spec,
  options,
  onChange,
}: {
  spec: SystemSpec;
  options: BuilderOptions;
  onChange: (patch: Partial<SystemSpec>) => void;
}) {
  const addFault = () => {
    const type = options.fault_types[0];
    const f: FaultSpec = {
      type,
      series: 0,
      parallel: 0,
      start_s: 600,
      params: { ...(options.fault_params[type] ?? {}) },
    };
    onChange({ faults: [...spec.faults, f] });
  };
  const update = (i: number, patch: Partial<FaultSpec>) =>
    onChange({ faults: spec.faults.map((f, j) => (j === i ? { ...f, ...patch } : f)) });
  const remove = (i: number) => onChange({ faults: spec.faults.filter((_, j) => j !== i) });
  const setType = (i: number, type: string) =>
    update(i, { type, params: { ...(options.fault_params[type] ?? {}) } });
  const setParam = (i: number, k: string, v: number | string) =>
    update(i, { params: { ...spec.faults[i].params, [k]: v } });

  return (
    <Section
      title="Faults"
      action={
        <button
          type="button"
          onClick={addFault}
          className="text-xs rounded border border-hairline px-2 py-1 text-ink-secondary hover:text-ink hover:bg-surface-2"
        >
          + Add fault
        </button>
      }
    >
      {spec.faults.length === 0 && (
        <p className="text-xs text-muted">No faults — a healthy system. Add one to inject a defect.</p>
      )}
      <div className="flex flex-col gap-3">
        {spec.faults.map((f, i) => (
          <div key={i} className="rounded-md bg-surface-2 border border-hairline p-3 flex flex-wrap items-end gap-3">
            <SelectField label="Type" value={f.type} options={options.fault_types} onChange={(v) => setType(i, v)} />
            <NumField label="Series" value={f.series} step={1} onChange={(v) => update(i, { series: Math.round(v) })} />
            <NumField label="Parallel" value={f.parallel} step={1} onChange={(v) => update(i, { parallel: Math.round(v) })} />
            <NumField label="Start (s)" value={f.start_s} step={10} onChange={(v) => update(i, { start_s: v })} />
            {f.type === "sensor_drift" && (
              <SelectField
                label="signal"
                value={String(f.params.signal ?? "voltage")}
                options={options.sensor_signals}
                onChange={(v) => setParam(i, "signal", v)}
              />
            )}
            {Object.keys(options.fault_params[f.type] ?? {}).map((k) => (
              <NumField
                key={k}
                label={k}
                value={Number(f.params[k] ?? options.fault_params[f.type][k])}
                step={0.1}
                onChange={(v) => setParam(i, k, v)}
              />
            ))}
            <button
              type="button"
              onClick={() => remove(i)}
              className="text-xs text-critical hover:underline pb-1.5"
            >
              remove
            </button>
          </div>
        ))}
      </div>
    </Section>
  );
}

function PreviewPanel({ result: r, goLiveCmd }: { result: PreviewResult; goLiveCmd: string }) {
  const safetyLevel = r.temp_limit_exceeded ? "critical" : "good";
  return (
    <div className="rounded-lg bg-surface border border-hairline px-5 py-4 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink">
          Offline preview — {r.name} ({r.chemistry}, {r.series_len}S{r.parallel_len}P)
        </h3>
        <span className="text-xs text-muted">
          {r.n_steps} steps · {r.duration_s.toFixed(0)} s
        </span>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <StatTile label="Final SoC" value={(r.final_soc * 100).toFixed(1)} unit="%" />
        <StatTile label="Voltage window" value={`${r.min_pack_voltage_v.toFixed(0)}–${r.max_pack_voltage_v.toFixed(0)}`} unit="V" />
        <StatTile label="Peak temp" value={r.peak_temp_c.toFixed(1)} unit="°C" level={safetyLevel} />
        <StatTile label="Energy" value={r.energy_throughput_wh.toFixed(0)} unit="Wh" />
        <StatTile label="Peak power" value={(r.peak_power_w / 1000).toFixed(2)} unit="kW" />
      </div>

      {r.temp_limit_exceeded && (
        <div className="rounded-md px-3 py-2 text-xs" style={{ backgroundColor: "#c0392b1a", color: "#eab0a6" }}>
          Temperature crossed the {r.temp_limit_c.toFixed(0)} °C limit at t ={" "}
          {r.time_to_limit_s?.toFixed(0)} s — this system runs into a thermal event.
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Spark title="State of charge" t={r.sparkline.t} y={r.sparkline.soc.map((v) => v * 100)} unit="%" color="#3987e5" />
        <Spark title="Max cell temp" t={r.sparkline.t} y={r.sparkline.max_temp} unit="°C" color="#eda100" />
        <Spark title="Pack voltage" t={r.sparkline.t} y={r.sparkline.voltage} unit="V" color="#0ca30c" />
      </div>

      <div className="text-xs text-ink-secondary">
        Looks good? Export the spec, then stream it live:
        <code className="ml-1 text-ink">{goLiveCmd}</code>
      </div>
    </div>
  );
}

function Spark({
  title,
  t,
  y,
  unit,
  color,
}: {
  title: string;
  t: number[];
  y: number[];
  unit: string;
  color: string;
}) {
  const data = useMemo(() => t.map((tt, i) => ({ t: tt, y: y[i] })), [t, y]);
  return (
    <div className="rounded-lg bg-surface-2 border border-hairline p-3">
      <h4 className="text-xs font-semibold text-ink mb-1">{title}</h4>
      <div style={{ width: "100%", height: 120 }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="#2c2c2a" vertical={false} />
            <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tickFormatter={(v) => `${Math.round(v)}s`} tick={{ fill: "#898781", fontSize: 10 }} stroke="#383835" minTickGap={40} />
            <YAxis domain={["auto", "auto"]} tick={{ fill: "#898781", fontSize: 10 }} stroke="#383835" width={40} tickFormatter={(v) => v.toFixed(0)} />
            <Tooltip
              contentStyle={{ backgroundColor: "#232322", border: "1px solid rgba(255,255,255,0.10)", borderRadius: 8, fontSize: 12 }}
              labelStyle={{ color: "#898781" }}
              itemStyle={{ color: "#ffffff" }}
              labelFormatter={(v) => `${Math.round(v as number)} s`}
              formatter={(value: number) => [`${value.toFixed(1)} ${unit}`, title]}
            />
            <Line type="monotone" dataKey="y" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ---- small form primitives ----
function Section({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-lg bg-surface border border-hairline px-5 py-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        {action}
      </div>
      {children}
    </div>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap items-end gap-3">{children}</div>;
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
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

function NumField({ label, value, step, onChange }: { label: string; value: number; step: number; onChange: (v: number) => void }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-ink-secondary">
      {label}
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        className="bg-surface-2 border border-hairline rounded-md px-2 py-1 text-ink text-sm w-28 tnums focus:outline-none focus:ring-1 focus:ring-series"
      />
    </label>
  );
}

function SelectField({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (v: string) => void }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-ink-secondary">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-surface-2 border border-hairline rounded-md px-2 py-1 text-ink text-sm focus:outline-none focus:ring-1 focus:ring-series"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={() =>
        navigator.clipboard?.writeText(text).then(() => {
          setDone(true);
          setTimeout(() => setDone(false), 1400);
        })
      }
      className="rounded-md border border-hairline px-3 py-1.5 text-sm text-ink-secondary hover:text-ink hover:bg-surface-2 focus:outline-none focus:ring-1 focus:ring-series"
    >
      {done ? "Copied ✓" : label}
    </button>
  );
}
