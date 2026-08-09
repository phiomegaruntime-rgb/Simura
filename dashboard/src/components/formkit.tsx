import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

// Shared form + chart primitives for the Wires views. These mirror the ones
// inlined in BuildView; kept here so the newer views don't each re-declare them.

export function Section({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
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

export function Row({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap items-end gap-3">{children}</div>;
}

export function TextField({
  label,
  value,
  onChange,
  width = "w-40",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  width?: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-ink-secondary">
      {label}
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`bg-surface-2 border border-hairline rounded-md px-2 py-1 text-ink text-sm ${width} focus:outline-none focus:ring-1 focus:ring-series`}
      />
    </label>
  );
}

export function NumField({
  label,
  value,
  step,
  onChange,
  width = "w-28",
}: {
  label: string;
  value: number;
  step: number;
  onChange: (v: number) => void;
  width?: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-ink-secondary">
      {label}
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        className={`bg-surface-2 border border-hairline rounded-md px-2 py-1 text-ink text-sm ${width} tnums focus:outline-none focus:ring-1 focus:ring-series`}
      />
    </label>
  );
}

export function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
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

export function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-ink-secondary pb-1.5 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="accent-series h-3.5 w-3.5"
      />
      {label}
    </label>
  );
}

export function CopyButton({ text, label }: { text: string; label: string }) {
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

export function ProblemList({ problems, okText }: { problems: string[]; okText: string }) {
  if (problems.length === 0)
    return <div className="text-sm text-good flex items-center gap-1.5">✓ {okText}</div>;
  return (
    <div className="rounded-md border border-critical/40 bg-surface px-4 py-3 text-sm text-critical">
      <ul className="list-disc pl-5 space-y-0.5">
        {problems.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>
    </div>
  );
}

export function Spark({
  title,
  t,
  y,
  y2,
  y2Label,
  unit,
  color,
  domain = ["auto", "auto"],
}: {
  title: string;
  t: number[];
  y: number[];
  y2?: number[];
  y2Label?: string;
  unit: string;
  color: string;
  domain?: [number | string, number | string];
}) {
  const data = useMemo(
    () => t.map((tt, i) => ({ t: tt, y: y[i], y2: y2 ? y2[i] : undefined })),
    [t, y, y2],
  );
  return (
    <div className="rounded-lg bg-surface-2 border border-hairline p-3">
      <h4 className="text-xs font-semibold text-ink mb-1">{title}</h4>
      <div style={{ width: "100%", height: 120 }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="#2c2c2a" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(v) => `${Math.round(v / 60)}m`}
              tick={{ fill: "#898781", fontSize: 10 }}
              stroke="#383835"
              minTickGap={40}
            />
            <YAxis
              domain={domain}
              tick={{ fill: "#898781", fontSize: 10 }}
              stroke="#383835"
              width={40}
              tickFormatter={(v) => v.toFixed(0)}
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
              labelFormatter={(v) => `${Math.round((v as number) / 60)} min`}
              formatter={(value: number, name: string) => [
                `${value.toFixed(1)} ${unit}`,
                name === "y2" ? y2Label ?? "b" : title,
              ]}
            />
            {y2 && (
              <Line
                type="monotone"
                dataKey="y2"
                stroke="#6b7280"
                strokeWidth={1.5}
                strokeDasharray="4 3"
                dot={false}
                isAnimationActive={false}
              />
            )}
            <Line
              type="monotone"
              dataKey="y"
              stroke={color}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
