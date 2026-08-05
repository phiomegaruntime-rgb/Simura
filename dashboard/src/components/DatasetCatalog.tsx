import { useState } from "react";
import type { DatasetSpec } from "../api/types";

interface Props {
  datasets: DatasetSpec[];
  selected: string | null;
  onSelect: (id: string) => void;
}

// The selectable catalog of open battery datasets. CellTwin ships no real data —
// each card links out to the source and shows the exact CLI command to validate
// that dataset against your own download.
export default function DatasetCatalog({ datasets, selected, onSelect }: Props) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {datasets.map((d) => (
        <DatasetCard
          key={d.id}
          spec={d}
          active={d.id === selected}
          onSelect={() => onSelect(d.id)}
        />
      ))}
    </div>
  );
}

function DatasetCard({
  spec,
  active,
  onSelect,
}: {
  spec: DatasetSpec;
  active: boolean;
  onSelect: () => void;
}) {
  const accent = spec.synthetic ? "#9085e9" : "#3987e5";
  const cli = spec.synthetic
    ? `python -m celltwin.validate --dataset ${spec.id}`
    : `python -m celltwin.validate --dataset ${spec.id} --file <your-download>`;

  return (
    <button
      type="button"
      onClick={onSelect}
      className="text-left rounded-lg bg-surface border px-4 py-3 flex flex-col gap-2 hover:bg-surface-2 focus:outline-none focus:ring-1 focus:ring-series transition-colors"
      style={{ borderColor: active ? accent : "rgba(255,255,255,0.10)" }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-ink truncate">{spec.name}</div>
          <div className="text-xs text-muted truncate">{spec.institution}</div>
        </div>
        {spec.synthetic && (
          <span
            className="shrink-0 text-[10px] font-semibold uppercase tracking-wide rounded px-1.5 py-0.5"
            style={{ backgroundColor: "#9085e933", color: "#9085e9" }}
          >
            synthetic
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <Chip>{spec.chemistry}</Chip>
        <Chip>{spec.cell_format}</Chip>
        <Chip color="#0ca30c">{spec.license}</Chip>
      </div>

      <ul className="text-xs text-ink-secondary leading-snug list-disc pl-4 min-h-[2.5rem]">
        {spec.what_it_validates.slice(0, 2).map((w) => (
          <li key={w}>{w}</li>
        ))}
      </ul>

      <div className="flex items-center gap-3 text-xs pt-1 border-t border-hairline">
        {spec.homepage_url && (
          <a
            href={spec.homepage_url}
            target="_blank"
            rel="noreferrer noopener"
            onClick={(e) => e.stopPropagation()}
            className="text-series hover:underline"
          >
            Homepage ↗
          </a>
        )}
        <CopyLink label="Copy citation" text={spec.citation} />
        <CopyLink label="Copy CLI" text={cli} />
      </div>
    </button>
  );
}

function Chip({ children, color }: { children: React.ReactNode; color?: string }) {
  return (
    <span
      className="text-[10px] rounded px-1.5 py-0.5"
      style={{
        backgroundColor: color ? `${color}22` : "rgba(255,255,255,0.06)",
        color: color ?? "#c9c7c1",
      }}
    >
      {children}
    </span>
  );
}

function CopyLink({ label, text }: { label: string; text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard?.writeText(text).then(
          () => {
            setDone(true);
            setTimeout(() => setDone(false), 1200);
          },
          () => {}
        );
      }}
      className="text-ink-secondary hover:text-ink"
    >
      {done ? "Copied ✓" : label}
    </button>
  );
}
