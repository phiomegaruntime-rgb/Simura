import type { AnomalyReport } from "../api/types";
import { LEVEL_COLOR, LEVEL_ICON, Level, anomalyLevel } from "../lib/status";

interface Props {
  report: AnomalyReport | null;
}

// Ranks cells the detector considers abnormal, with the driving signal. This is
// the "early warning" view: cells show up here before they cross a hard limit.
export default function AnomalyPanel({ report }: Props) {
  const flagged = (report?.cells ?? [])
    .filter((c) => c.level !== "good")
    .sort((a, b) => b.score - a.score)
    .slice(0, 6);

  return (
    <div className="rounded-lg bg-surface border border-hairline p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-ink">Anomaly detection</h3>
        {report && (
          <span className="text-xs text-muted tnums">peak {report.max_score.toFixed(1)} σ</span>
        )}
      </div>
      {flagged.length === 0 ? (
        <p className="text-sm text-muted">
          {report ? "No cells deviating from their peers." : "Waiting for detector…"}
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {flagged.map((c) => {
            const level = c.level as Level;
            return (
              <li
                key={`${c.series_index}-${c.parallel_index}`}
                className="flex items-center gap-2.5 text-sm"
              >
                <span
                  className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
                  style={{ backgroundColor: LEVEL_COLOR[level], color: "#0d0d0d" }}
                >
                  {LEVEL_ICON[level]}
                </span>
                <span className="text-ink">
                  Module {c.series_index} · slot {c.parallel_index}
                </span>
                <span className="text-muted">— {c.driver}</span>
                <span className="ml-auto tnums" style={{ color: LEVEL_COLOR[level] }}>
                  {c.score.toFixed(1)} σ
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// Re-export so App can color the banner without importing status directly here.
export { anomalyLevel };
