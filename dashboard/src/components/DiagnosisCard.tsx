import type { AssessmentReport } from "../api/types";
import { faultLabel, LEVEL_COLOR, LEVEL_ICON, safetyLevel } from "../lib/status";

interface Props {
  report: AssessmentReport | null;
}

function fmtTtc(s: number | null): string {
  if (s == null) return "—";
  if (s < 90) return `${Math.round(s)} s`;
  return `${(s / 60).toFixed(1)} min`;
}

// The Component 5 headline: what is wrong, how sure, how healthy, how long.
export default function DiagnosisCard({ report }: Props) {
  const safety = report ? safetyLevel(report.safety_state) : "good";
  const fault = report?.diagnosis.fault_type ?? "none";
  const hasFault = fault !== "none";
  const color = LEVEL_COLOR[safety];

  return (
    <div
      className="rounded-lg bg-surface border p-4"
      style={{ borderColor: hasFault ? color : "rgba(255,255,255,0.10)" }}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-ink">Diagnosis &amp; prognosis</h3>
        <span
          className="flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded-full"
          style={{ color, backgroundColor: `${color}1f` }}
        >
          <span
            className="inline-flex h-3.5 w-3.5 items-center justify-center rounded-full text-[9px] font-bold"
            style={{ backgroundColor: color, color: "#0d0d0d" }}
          >
            {LEVEL_ICON[safety]}
          </span>
          {report ? report.safety_state.toUpperCase() : "—"}
        </span>
      </div>

      {!report ? (
        <p className="text-sm text-muted">Waiting for analytics…</p>
      ) : (
        <>
          <div className="mb-3">
            <div className="text-lg font-semibold" style={{ color: hasFault ? color : "#c3c2b7" }}>
              {faultLabel(fault)}
            </div>
            {hasFault && (
              <>
                <div className="text-xs text-muted mt-0.5">
                  module {report.diagnosis.cell_series} · slot {report.diagnosis.cell_parallel} ·{" "}
                  {(report.diagnosis.confidence * 100).toFixed(0)}% confidence
                </div>
                <div className="mt-1.5 h-1.5 rounded-full bg-surface-2 overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${report.diagnosis.confidence * 100}%`, backgroundColor: color }}
                  />
                </div>
                <p className="text-sm text-ink-secondary mt-2">{report.diagnosis.rationale}</p>
              </>
            )}
          </div>

          <div className="grid grid-cols-3 gap-2 pt-3 border-t border-hairline text-center">
            <Metric label="Pack SoH" value={`${(report.pack_soh * 100).toFixed(0)}%`} />
            <Metric label="Worst cell SoH" value={`${(report.worst_cell_soh * 100).toFixed(0)}%`} />
            <Metric
              label="Time to critical"
              value={fmtTtc(report.min_time_to_critical_s)}
              highlight={report.min_time_to_critical_s != null && report.min_time_to_critical_s <= 600}
            />
          </div>
        </>
      )}
    </div>
  );
}

function Metric({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div>
      <div
        className="text-base font-semibold tnums"
        style={{ color: highlight ? LEVEL_COLOR.serious : "#ffffff" }}
      >
        {value}
      </div>
      <div className="text-[10px] uppercase tracking-wide text-muted mt-0.5">{label}</div>
    </div>
  );
}
