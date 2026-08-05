import type { SystemInfo } from "../api/types";

type View = "fleet" | "system" | "validation" | "build";

interface Props {
  view: View;
  systems: SystemInfo[];
  selected: string | null;
  onFleet: () => void;
  onValidation: () => void;
  onBuild: () => void;
  connected: boolean;
}

// Top-level destinations. The main nav shows the ones you're NOT currently on
// (e.g. on Fleet it offers Validation + Build; on Validation it offers Fleet +
// Build). The per-system detail view replaces the nav with a sub-nav.
const NAV: { key: "fleet" | "validation" | "build"; label: string }[] = [
  { key: "fleet", label: "Fleet" },
  { key: "validation", label: "Validation" },
  { key: "build", label: "Build" },
];

export default function TopBar({
  view,
  systems,
  selected,
  onFleet,
  onValidation,
  onBuild,
  connected,
}: Props) {
  const go = { fleet: onFleet, validation: onValidation, build: onBuild };
  const viewLabel = view === "system" ? "System" : NAV.find((n) => n.key === view)?.label ?? "";
  const systemName = systems.find((s) => s.system_id === selected)?.name || selected || "System";

  return (
    <header className="flex items-center justify-between gap-4 px-6 py-4 border-b border-hairline bg-surface">
      <button
        type="button"
        onClick={onFleet}
        className="flex items-center gap-3 text-left focus:outline-none focus:ring-1 focus:ring-series rounded-md"
        title="Fleet overview"
      >
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold leading-none text-ink">CellTwin</h1>
            <span className="text-[10px] uppercase tracking-wider text-muted border border-hairline rounded px-1 py-0.5 leading-none">
              by Simura
            </span>
          </div>
          <p className="text-xs text-muted mt-0.5">A BESS Digital Twin — {viewLabel}</p>
        </div>
      </button>

      {view === "system" ? (
        // Sub-nav for a single system: back + name + live tag.
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onFleet}
            className="text-sm text-ink-secondary hover:text-ink focus:outline-none focus:ring-1 focus:ring-series rounded px-2 py-1"
          >
            ← Back
          </button>
          <div className="h-5 w-px bg-hairline" />
          <span className="text-sm font-medium text-ink truncate max-w-[16rem]">{systemName}</span>
          <span className="flex items-center gap-2 text-sm">
            <span
              className={`h-2.5 w-2.5 rounded-full ${connected ? "bg-good" : "bg-critical"}`}
              style={connected ? { boxShadow: "0 0 8px #0ca30c" } : undefined}
            />
            <span className={connected ? "text-good" : "text-critical"}>
              {connected ? "Live" : "Disconnected"}
            </span>
          </span>
        </div>
      ) : (
        // Main nav: the sibling top-level views (the current one is omitted).
        <nav className="flex items-center gap-1 text-sm">
          {NAV.filter((n) => n.key !== view).map((n) => (
            <button
              key={n.key}
              type="button"
              onClick={go[n.key]}
              className="rounded px-3 py-1.5 text-ink-secondary hover:text-ink hover:bg-surface-2 focus:outline-none focus:ring-1 focus:ring-series"
            >
              {n.label}
            </button>
          ))}
        </nav>
      )}
    </header>
  );
}
