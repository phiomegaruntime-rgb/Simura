import type { Level } from "../lib/status";
import { LEVEL_COLOR, LEVEL_ICON, LEVEL_LABEL } from "../lib/status";

interface Props {
  level: Level;
  reason: string;
  simTimeS: number | null;
}

export default function HealthBanner({ level, reason, simTimeS }: Props) {
  const color = LEVEL_COLOR[level];
  return (
    <div
      className="rounded-lg px-5 py-4 flex items-center justify-between border"
      style={{ borderColor: color, backgroundColor: `${color}14` }}
    >
      <div className="flex items-center gap-3">
        <span
          className="inline-flex h-8 w-8 items-center justify-center rounded-full text-sm font-bold"
          style={{ backgroundColor: color, color: "#0d0d0d" }}
        >
          {LEVEL_ICON[level]}
        </span>
        <div>
          <div className="text-lg font-semibold" style={{ color }}>
            {LEVEL_LABEL[level]}
          </div>
          <div className="text-sm text-ink-secondary">{reason}</div>
        </div>
      </div>
      {simTimeS != null && (
        <div className="text-right">
          <div className="text-xs uppercase tracking-wide text-muted">Sim time</div>
          <div className="text-sm text-ink tnums">{formatSimTime(simTimeS)}</div>
        </div>
      )}
    </div>
  );
}

function formatSimTime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return `${h}h ${String(m).padStart(2, "0")}m ${String(sec).padStart(2, "0")}s`;
}
