import { useEffect, useMemo, useState } from "react";
import { fetchCards, fetchGlossary, fetchLenses } from "../api/client";
import type { ExplainLenses, GlossaryEntry, ModelCard } from "../api/types";

const COMPONENT_LABEL: Record<string, string> = {
  batteries: "Batteries",
  wires: "Wires",
  lights: "Lights",
  twin: "The twin",
};

const COMPONENT_ACCENT: Record<string, string> = {
  batteries: "#0ca30c",
  wires: "#eda100",
  lights: "#4fc3f7",
  twin: "#9085e9",
};

/**
 * The reading room: every model in the project, in plain language.
 *
 * This is the half of "get familiar" that is not about a running system. The
 * explain panels answer *what is this doing right now*; these cards answer
 * *what is this thing, and why would anyone care* — for someone whose expertise
 * is in a different domain entirely.
 *
 * Two deliberate choices show up in the layout. Each card leads with its
 * **limits** as prominently as its description, because a model card that only
 * says what a model does is marketing and the useful half is what it cannot
 * tell you. And each card can be re-read **in another field's words** via
 * "reads like", which is the mission stated as a UI control: the same model,
 * said the way a thermal engineer or an operator would say it.
 */
export default function LearnView() {
  const [cards, setCards] = useState<ModelCard[]>([]);
  const [glossary, setGlossary] = useState<GlossaryEntry[]>([]);
  const [lenses, setLenses] = useState<ExplainLenses | null>(null);
  const [component, setComponent] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [openCard, setOpenCard] = useState<string | null>(null);

  useEffect(() => {
    fetchCards().then(setCards).catch(() => {});
    fetchGlossary().then(setGlossary).catch(() => {});
    fetchLenses().then(setLenses).catch(() => {});
  }, []);

  const q = query.trim().toLowerCase();

  const shown = useMemo(
    () =>
      cards.filter((c) => {
        if (component !== "all" && c.component !== component) return false;
        if (!q) return true;
        return (
          c.title.toLowerCase().includes(q) ||
          c.one_line.toLowerCase().includes(q) ||
          c.what.toLowerCase().includes(q) ||
          c.params.some((p) => p.label.toLowerCase().includes(q) || p.key.includes(q))
        );
      }),
    [cards, component, q],
  );

  const shownTerms = useMemo(
    () =>
      q
        ? glossary.filter(
            (g) =>
              g.term.toLowerCase().includes(q) ||
              g.aliases.some((a) => a.toLowerCase().includes(q)) ||
              g.short.toLowerCase().includes(q),
          )
        : glossary,
    [glossary, q],
  );

  const components = ["all", ...Object.keys(COMPONENT_LABEL)];

  return (
    <div className="flex flex-col gap-5">
      <div className="max-w-3xl">
        <h2 className="text-2xl font-semibold text-ink">What everything means</h2>
        <p className="text-sm text-ink-secondary mt-1">
          Every model in Simura, and every setting it takes, written for someone who works in a
          different field. Each card says what the model does, why it matters, and — just as
          plainly — what it cannot tell you.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {components.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setComponent(c)}
            className={`text-xs rounded px-2.5 py-1 border transition-colors ${
              component === c
                ? "bg-surface-2 text-ink border-hairline"
                : "text-muted border-transparent hover:text-ink-secondary"
            }`}
          >
            {c === "all" ? "Everything" : COMPONENT_LABEL[c]}
          </button>
        ))}
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search models, settings and terms…"
          className="ml-auto text-sm bg-surface border border-hairline rounded px-3 py-1.5 text-ink placeholder:text-muted w-full sm:w-72"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
        <div className="lg:col-span-2 flex flex-col gap-3">
          {shown.length === 0 && (
            <p className="text-sm text-muted">No model matches that.</p>
          )}
          {shown.map((c) => (
            <CardBlock
              key={c.id}
              card={c}
              open={openCard === c.id}
              onToggle={() => setOpenCard(openCard === c.id ? null : c.id)}
              onOpenOther={(id) => setOpenCard(id)}
              domains={lenses?.domains ?? []}
            />
          ))}
        </div>

        <div className="rounded-lg bg-surface border border-hairline p-4">
          <h3 className="text-sm font-semibold text-ink mb-2">Glossary</h3>
          <p className="text-xs text-muted mb-3">
            {shownTerms.length} term{shownTerms.length === 1 ? "" : "s"}. These also appear
            underlined wherever they turn up elsewhere in the dashboard.
          </p>
          <dl className="flex flex-col gap-2.5 max-h-[70vh] overflow-y-auto pr-1">
            {shownTerms.map((g) => (
              <div key={g.term}>
                <dt className="text-xs font-medium text-ink">
                  {g.term}
                  {g.unit && <span className="text-muted font-normal"> ({g.unit})</span>}
                </dt>
                <dd className="text-xs text-ink-secondary leading-snug">{g.short}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </div>
  );
}

function CardBlock({
  card,
  open,
  onToggle,
  onOpenOther,
  domains,
}: {
  card: ModelCard;
  open: boolean;
  onToggle: () => void;
  onOpenOther: (id: string) => void;
  domains: { key: string; label: string }[];
}) {
  const accent = COMPONENT_ACCENT[card.component] ?? "#9085e9";
  const readsLike = Object.entries(card.reads_like);

  return (
    <div
      className="rounded-lg bg-surface border p-4 flex flex-col gap-2"
      style={{ borderColor: open ? `${accent}55` : "rgba(255,255,255,0.10)" }}
    >
      <button type="button" onClick={onToggle} className="text-left flex items-start gap-3">
        <span
          className="text-[10px] font-semibold uppercase tracking-wide rounded px-1.5 py-0.5 mt-0.5 shrink-0"
          style={{ backgroundColor: `${accent}22`, color: accent }}
        >
          {COMPONENT_LABEL[card.component]}
        </span>
        <span className="flex-1">
          <span className="block text-sm font-semibold text-ink">{card.title}</span>
          <span className="block text-xs text-ink-secondary leading-snug mt-0.5">
            {card.one_line}
          </span>
        </span>
        <span className="text-muted text-xs mt-0.5">{open ? "−" : "+"}</span>
      </button>

      {open && (
        <div className="flex flex-col gap-3 pt-1">
          <p className="text-sm text-ink-secondary leading-snug">{card.what}</p>
          <div>
            <div className="text-[11px] uppercase tracking-wide text-muted">Why it matters</div>
            <p className="text-sm text-ink-secondary leading-snug">{card.why}</p>
          </div>

          {card.equation && (
            <div className="text-xs font-mono text-ink bg-surface-2 rounded px-2 py-1.5 overflow-x-auto">
              {card.equation}
            </div>
          )}

          {readsLike.length > 0 && (
            <div>
              <div className="text-[11px] uppercase tracking-wide text-muted mb-1">
                Reads like, if your field is…
              </div>
              <div className="flex flex-col gap-1">
                {readsLike.map(([key, text]) => (
                  <div key={key} className="text-xs">
                    <span className="text-ink font-medium">
                      {domains.find((d) => d.key === key)?.label ?? key}
                    </span>
                    <span className="text-ink-secondary"> — {text}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {card.limits.length > 0 && (
            <div>
              <div className="text-[11px] uppercase tracking-wide text-muted mb-1">
                What it cannot tell you
              </div>
              <ul className="list-disc list-inside text-xs text-ink-secondary flex flex-col gap-0.5">
                {card.limits.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </div>
          )}

          {card.assumptions.length > 0 && (
            <details className="text-xs">
              <summary className="cursor-pointer text-muted hover:text-ink-secondary">
                Assumptions ({card.assumptions.length})
              </summary>
              <ul className="list-disc list-inside text-ink-secondary mt-1 flex flex-col gap-0.5">
                {card.assumptions.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </details>
          )}

          {card.params.length > 0 && (
            <div>
              <div className="text-[11px] uppercase tracking-wide text-muted mb-1.5">
                Settings ({card.params.length})
              </div>
              <div className="flex flex-col gap-2">
                {card.params.map((p) => (
                  <div key={p.key} className="border-l-2 border-hairline pl-2.5">
                    <div className="text-xs font-medium text-ink">
                      {p.label}
                      {p.unit && <span className="text-muted font-normal"> ({p.unit})</span>}
                      <span className="text-muted font-mono font-normal ml-1.5">{p.key}</span>
                    </div>
                    <p className="text-xs text-ink-secondary leading-snug">{p.what}</p>
                    <p className="text-xs text-ink-secondary leading-snug mt-0.5">{p.why}</p>
                    {p.feel && (
                      <p className="text-xs text-muted leading-snug mt-0.5 italic">{p.feel}</p>
                    )}
                    {p.typical && (
                      <p className="text-[11px] text-muted mt-0.5">Typical: {p.typical}</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-hairline">
            <span className="text-[11px] text-muted font-mono">{card.source}</span>
            {card.see_also.map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => onOpenOther(id)}
                className="text-[11px] rounded px-1.5 py-0.5 bg-surface-2 border border-hairline text-ink-secondary hover:text-ink"
              >
                {id}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
