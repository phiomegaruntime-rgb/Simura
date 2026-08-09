import type { SystemInfo } from "../api/types";
import { sectionOf } from "../lib/sections";
import type { View } from "../lib/sections";

interface Props {
  view: View;
  systems: SystemInfo[];
  selected: string | null;
  onHome: () => void;
  onNavigate: (view: View) => void;
  connected: boolean;
}

// The top bar. On the landing page it shows only the brand — no nav. Once inside a
// simulation component it shows that component's sub-nav (with the active view
// highlighted), and a way back to the landing cards. The per-system detail view
// keeps its own back + live-status sub-nav.
export default function TopBar({
  view,
  systems,
  selected,
  onHome,
  onNavigate,
  connected,
}: Props) {
  const section = sectionOf(view);
  const isHome = view === "home";
  const isSystem = view === "system";

  const tagline = isHome ? "" : ` — ${isSystem ? "Batteries" : section?.label ?? ""}`;
  const systemName = systems.find((s) => s.system_id === selected)?.name || selected || "System";

  return (
    <header className="flex items-center justify-between gap-4 px-6 py-4 border-b border-hairline bg-surface">
      <button
        type="button"
        onClick={onHome}
        className="flex items-center gap-3 text-left focus:outline-none focus:ring-1 focus:ring-series rounded-md"
        title="Back to components"
      >
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold leading-none text-ink">Simura</h1>
          </div>
          <p className="text-xs text-muted mt-0.5">Simulate Everything. Miss Nothing{tagline}</p>
        </div>
      </button>

      {isHome ? (
        // Landing page: no nav — the cards are the nav.
        <span />
      ) : isSystem ? (
        // Sub-nav for a single system: back + name + live tag.
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => onNavigate("fleet")}
            className="text-sm text-ink-secondary hover:text-ink focus:outline-none focus:ring-1 focus:ring-series rounded px-2 py-1"
          >
            ← Fleet
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
        // Inside a component: back to the cards, then the component's sub-nav.
        <nav className="flex items-center gap-1 text-sm">
          <button
            type="button"
            onClick={onHome}
            className="rounded px-2 py-1.5 text-muted hover:text-ink hover:bg-surface-2 focus:outline-none focus:ring-1 focus:ring-series"
            title="Back to components"
          >
            ← Components
          </button>
          {section && section.nav.length > 0 && <div className="h-5 w-px bg-hairline mx-1" />}
          {section?.nav.map((n) => {
            const active = n.key === view;
            return (
              <button
                key={n.key}
                type="button"
                onClick={() => onNavigate(n.key)}
                aria-current={active ? "page" : undefined}
                className={`rounded px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-series ${
                  active
                    ? "text-ink bg-surface-2"
                    : "text-ink-secondary hover:text-ink hover:bg-surface-2"
                }`}
              >
                {n.label}
              </button>
            );
          })}
        </nav>
      )}
    </header>
  );
}
