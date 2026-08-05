import type { Level } from "../lib/status";
import { LEVEL_COLOR, LEVEL_ICON, LEVEL_LABEL } from "../lib/status";

interface Props {
  label: string;
  value: string;
  unit?: string;
  level?: Level; // when present, shows a reserved status color + icon + label
}

// A hero number. Value stays in primary ink; a status chip (icon + label + color)
// carries state so meaning never rests on color alone.
export default function StatTile({ label, value, unit, level }: Props) {
  return (
    <div className="rounded-lg bg-surface border border-hairline px-4 py-3 flex flex-col gap-1">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="flex items-baseline gap-1">
        <span className="text-2xl font-semibold text-ink tnums">{value}</span>
        {unit && <span className="text-sm text-ink-secondary">{unit}</span>}
      </div>
      {level && (
        <div className="flex items-center gap-1.5 text-xs" style={{ color: LEVEL_COLOR[level] }}>
          <span
            className="inline-flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold"
            style={{ backgroundColor: LEVEL_COLOR[level], color: "#0d0d0d" }}
          >
            {LEVEL_ICON[level]}
          </span>
          <span className="font-medium">{LEVEL_LABEL[level]}</span>
        </div>
      )}
    </div>
  );
}
