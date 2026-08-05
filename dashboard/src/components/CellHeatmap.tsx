import { useMemo, useRef, useState } from "react";
import type { CellAnomaly, CellTelemetry } from "../api/types";
import { METRIC_LABEL, MetricKey, rampColor, RAMPS } from "../lib/color";
import { Level, LEVEL_COLOR } from "../lib/status";

interface Props {
  cells: CellTelemetry[];
  series: number;
  parallel: number;
  anomalies?: Map<string, CellAnomaly>;
}

const METRICS: MetricKey[] = ["temp", "voltage", "soc", "anomaly"];
const METRIC_BTN: Record<MetricKey, string> = {
  temp: "Temp",
  voltage: "Voltage",
  soc: "SoC",
  anomaly: "Anomaly",
};

function metricValue(cell: CellTelemetry, m: MetricKey, anom?: CellAnomaly): number {
  if (m === "temp") return cell.temp_c;
  if (m === "voltage") return cell.voltage_v;
  if (m === "soc") return cell.soc;
  return anom?.score ?? 0; // anomaly
}

function formatValue(v: number, m: MetricKey): string {
  if (m === "temp") return `${v.toFixed(1)} °C`;
  if (m === "voltage") return `${v.toFixed(3)} V`;
  if (m === "soc") return `${(v * 100).toFixed(1)} %`;
  return `${v.toFixed(1)} σ`;
}

export default function CellHeatmap({ cells, series, parallel, anomalies }: Props) {
  const [metric, setMetric] = useState<MetricKey>("temp");
  const [hover, setHover] = useState<{ cell: CellTelemetry; x: number; y: number } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const grid = useMemo(() => {
    const byPos = new Map<string, CellTelemetry>();
    for (const c of cells) byPos.set(`${c.series_index}-${c.parallel_index}`, c);
    return byPos;
  }, [cells]);

  const { min, max } = useMemo(() => {
    // Temperature is colored on an ABSOLUTE safety scale; anomaly on its fixed
    // 0–6σ severity scale; voltage/SoC RELATIVE to the current spread (imbalance).
    if (metric === "temp") return { min: 20, max: 60 };
    if (metric === "anomaly") return { min: 0, max: 6 };
    if (cells.length === 0) return { min: 0, max: 1 };
    const vals = cells.map((c) => metricValue(c, metric));
    return { min: Math.min(...vals), max: Math.max(...vals) };
  }, [cells, metric]);

  const range = max - min || 1;

  return (
    <div className="rounded-lg bg-surface border border-hairline p-4 relative" ref={containerRef}>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-ink">
          Cell map <span className="text-muted font-normal">· {series}S{parallel}P</span>
        </h2>
        <div className="flex gap-1 rounded-md bg-surface-2 p-0.5">
          {METRICS.map((m) => (
            <button
              key={m}
              onClick={() => setMetric(m)}
              className={`px-2.5 py-1 text-xs rounded ${
                metric === m ? "bg-series text-plane font-medium" : "text-ink-secondary hover:text-ink"
              }`}
            >
              {METRIC_BTN[m]}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-auto max-h-[62vh]">
        <div
          className="grid gap-1.5 mx-auto w-fit"
          style={{ gridTemplateColumns: `24px repeat(${parallel}, 116px)` }}
        >
          {Array.from({ length: series }).flatMap((_, s) => [
            <div
              key={`lbl-${s}`}
              className="flex items-center justify-end pr-1 text-[10px] text-muted tnums"
            >
              M{s}
            </div>,
            ...Array.from({ length: parallel }).map((__, p) => {
              const key = `${s}-${p}`;
              const cell = grid.get(key);
              const anom = anomalies?.get(key);
              const v = cell ? metricValue(cell, metric, anom) : min;
              const t = (v - min) / range;
              const anomFlagged = anom && anom.level !== "good";
              return (
                <div
                  key={key}
                  className="relative h-11 rounded-md flex items-center justify-center text-[11px] font-medium tnums transition-colors cursor-default"
                  style={{
                    backgroundColor: cell ? rampColor([...RAMPS[metric]], t) : "#232322",
                    boxShadow: anomFlagged ? `inset 0 0 0 2px ${LEVEL_COLOR[anom!.level as Level]}` : undefined,
                    color: t > 0.55 ? "#0d0d0d" : "#c3c2b7",
                  }}
                  onMouseEnter={(e) => {
                    if (!cell) return;
                    const rect = containerRef.current!.getBoundingClientRect();
                    setHover({ cell, x: e.clientX - rect.left, y: e.clientY - rect.top });
                  }}
                  onMouseMove={(e) => {
                    if (!cell) return;
                    const rect = containerRef.current!.getBoundingClientRect();
                    setHover({ cell, x: e.clientX - rect.left, y: e.clientY - rect.top });
                  }}
                  onMouseLeave={() => setHover(null)}
                >
                  {cell ? formatValue(v, metric).replace(/ .*/, "") : "–"}
                  {anomFlagged && (
                    <span
                      className="absolute top-1 right-1 h-2 w-2 rounded-full"
                      style={{ backgroundColor: LEVEL_COLOR[anom!.level as Level] }}
                    />
                  )}
                </div>
              );
            }),
          ])}
        </div>
      </div>

      {/* Colorbar legend */}
      <div className="mt-4 flex items-center gap-3">
        <span className="text-xs text-muted w-28 shrink-0">{METRIC_LABEL[metric]}</span>
        <div
          className="h-2.5 flex-1 rounded-full"
          style={{ background: `linear-gradient(to right, ${RAMPS[metric].join(", ")})` }}
        />
        <span className="text-xs text-ink-secondary tnums w-14 text-right">
          {formatValue(min, metric)}
        </span>
        <span className="text-xs text-muted">→</span>
        <span className="text-xs text-ink-secondary tnums w-14">{formatValue(max, metric)}</span>
      </div>

      {hover && (
        <div
          className="absolute z-10 pointer-events-none rounded-md border border-hairline bg-surface-2 px-3 py-2 text-xs shadow-lg"
          style={{
            left: Math.min(hover.x + 12, (containerRef.current?.clientWidth ?? 0) - 160),
            top: hover.y + 12,
          }}
        >
          <div className="font-semibold text-ink mb-1">
            Module {hover.cell.series_index} · slot {hover.cell.parallel_index}
          </div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-ink-secondary tnums">
            <span>Temp</span>
            <span className="text-right text-ink">{hover.cell.temp_c.toFixed(1)} °C</span>
            <span>Voltage</span>
            <span className="text-right text-ink">{hover.cell.voltage_v.toFixed(3)} V</span>
            <span>Current</span>
            <span className="text-right text-ink">{hover.cell.current_a.toFixed(2)} A</span>
            <span>SoC</span>
            <span className="text-right text-ink">{(hover.cell.soc * 100).toFixed(1)} %</span>
            {(() => {
              const a = anomalies?.get(`${hover.cell.series_index}-${hover.cell.parallel_index}`);
              return a ? (
                <>
                  <span>Anomaly</span>
                  <span className="text-right" style={{ color: LEVEL_COLOR[a.level as Level] }}>
                    {a.score.toFixed(1)} σ ({a.driver})
                  </span>
                </>
              ) : null;
            })()}
          </div>
        </div>
      )}
    </div>
  );
}
