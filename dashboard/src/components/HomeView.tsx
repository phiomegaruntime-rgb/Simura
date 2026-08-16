import { ALL_SECTIONS } from "../lib/sections";
import type { Section, View } from "../lib/sections";

interface Props {
  onOpen: (view: View) => void;
}

// The landing page: one card per simulation component. Picking a card drills into
// that component and the top bar switches to the component's own sub-nav. This is
// the only view with no nav in the header — it *is* the nav.
export default function HomeView({ onOpen }: Props) {
  return (
    <div className="flex flex-col gap-6">
      <div className="max-w-3xl">
        <h2 className="text-2xl font-semibold text-ink">Choose a simulation component</h2>
        <p className="text-sm text-ink-secondary mt-1">
          Simura is built from physics-based components.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {ALL_SECTIONS.map((s) => (
          <SectionCard key={s.key} section={s} onOpen={() => onOpen(s.landing)} />
        ))}
      </div>
    </div>
  );
}

function SectionCard({ section, onOpen }: { section: Section; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group text-left rounded-lg bg-surface border px-5 py-5 flex flex-col gap-4 transition-colors hover:bg-surface-2 focus:outline-none focus:ring-1 focus:ring-series"
      style={{ borderColor: `${section.accent}55` }}
    >
      <div className="flex items-start justify-between gap-3">
        <span
          className="inline-flex h-11 w-11 items-center justify-center rounded-lg text-2xl leading-none"
          style={{ backgroundColor: `${section.accent}22` }}
        >
          {section.icon}
        </span>
        <span
          className="text-[10px] font-semibold uppercase tracking-wide rounded px-1.5 py-0.5"
          style={{ backgroundColor: `${section.accent}22`, color: section.accent }}
        >
          {section.tagline}
        </span>
      </div>

      <div>
        <div className="text-lg font-semibold text-ink">{section.label}</div>
        <p className="text-sm text-ink-secondary mt-1 leading-snug">{section.description}</p>
      </div>

      <div className="flex flex-wrap items-center gap-1.5 mt-auto pt-3 border-t border-hairline">
        {section.contents.map((c) => (
          <span
            key={c}
            className="text-[11px] rounded px-1.5 py-0.5 text-ink-secondary bg-surface-2 border border-hairline"
          >
            {c}
          </span>
        ))}
        <span
          className="ml-auto text-sm font-medium transition-transform group-hover:translate-x-0.5"
          style={{ color: section.accent }}
        >
          Open →
        </span>
      </div>
    </button>
  );
}
