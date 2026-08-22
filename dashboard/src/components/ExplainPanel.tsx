import { useEffect, useMemo, useState } from "react";
import { fetchLenses } from "../api/client";
import type { Explanation, ExplainLenses, ExplainLevel, ExplainResponse } from "../api/types";
import Jargon from "./Jargon";

interface Props {
  /** The explanation to show. `null` while it is being fetched. */
  data: ExplainResponse | null;
  /** Current lens; the panel does not fetch, it reports the change upward. */
  domain: string;
  level: ExplainLevel;
  onDomain: (d: string) => void;
  onLevel: (l: ExplainLevel) => void;
  error?: string | null;
  title?: string;
  /** Shown under the title — e.g. which cell this is about. */
  subtitle?: string;
  /**
   * Drop the outer card chrome. For callers that already have a surface around
   * it — a modal, a drawer — where a bordered panel inside a bordered panel
   * reads as two things rather than one.
   */
  bare?: boolean;
}

/**
 * Progressive disclosure, from one computation.
 *
 * The three depths are not three texts. They are three renderings of the same
 * attribution, produced server-side by `simura.explain`, and the contract they
 * keep is that **depth adds and never contradicts** — the headline is identical
 * at every level and every figure quoted at the top reappears, unrounded, at
 * the bottom. So this component never re-words anything: it shows more of what
 * it was given, and the "Physics" control is a request for a deeper render, not
 * a local expand.
 *
 * The two controls are separate on purpose. Depth is how much machinery you
 * want; domain is whose words it is in. A lighting designer reading a battery
 * usually wants their *own* vocabulary and *more* depth, and a single
 * "beginner/expert" slider cannot express that.
 */
export default function ExplainPanel({
  data,
  domain,
  level,
  onDomain,
  onLevel,
  error,
  title = "What is happening, and why",
  subtitle,
  bare = false,
}: Props) {
  const [lenses, setLenses] = useState<ExplainLenses | null>(null);

  useEffect(() => {
    fetchLenses().then(setLenses).catch(() => {});
  }, []);

  return (
    <div
      className={
        bare
          ? "flex flex-col gap-3"
          : "rounded-lg bg-surface border border-hairline p-4 flex flex-col gap-3"
      }
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">{title}</h3>
          {subtitle && <p className="text-xs text-muted mt-0.5">{subtitle}</p>}
        </div>
        <div className="flex items-center gap-2">
          {lenses && (
            <select
              value={domain}
              onChange={(e) => onDomain(e.target.value)}
              title={lenses.domains.find((d) => d.key === domain)?.who}
              className="text-xs bg-surface-2 border border-hairline rounded px-2 py-1 text-ink-secondary"
            >
              {lenses.domains.map((d) => (
                <option key={d.key} value={d.key}>
                  {d.label}
                </option>
              ))}
            </select>
          )}
          <LevelSwitch
            levels={lenses?.levels}
            value={level}
            onChange={onLevel}
          />
        </div>
      </div>

      {error ? (
        <p className="text-sm text-ink-secondary">{error}</p>
      ) : !data ? (
        <p className="text-sm text-muted">Working it out…</p>
      ) : data.explanations.length === 0 ? (
        <p className="text-sm text-muted">Nothing to explain yet.</p>
      ) : (
        <>
          {data.source && <SourceBadge source={data.source} exact={data.exact ?? false} />}
          <div className="flex flex-col gap-3">
            {data.explanations.map((e) => (
              <ExplanationBlock key={e.key} e={e} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/**
 * Where the answer came from. Worth its own badge rather than a footnote: an
 * explanation read out of the running solver and one inferred from a telemetry
 * frame are different claims, and the second cannot see fault heat at all.
 */
function SourceBadge({ source, exact }: { source: "model" | "telemetry"; exact: boolean }) {
  const fromModel = source === "model" && exact;
  return (
    <div
      className="text-[11px] rounded px-2 py-1 border inline-flex items-start gap-1.5 self-start"
      style={{
        borderColor: fromModel ? "#0ca30c55" : "#eda10055",
        backgroundColor: fromModel ? "#0ca30c14" : "#eda10014",
        color: fromModel ? "#0ca30c" : "#eda100",
      }}
    >
      <span aria-hidden>{fromModel ? "✓" : "≈"}</span>
      <span>
        {fromModel
          ? "Read from the running model — exact."
          : "Inferred from telemetry — some terms are estimated."}
      </span>
    </div>
  );
}

function LevelSwitch({
  levels,
  value,
  onChange,
}: {
  levels?: { key: ExplainLevel; label: string; who: string }[];
  value: ExplainLevel;
  onChange: (l: ExplainLevel) => void;
}) {
  const items =
    levels ??
    ([
      { key: "overview", label: "Overview", who: "" },
      { key: "working", label: "Working", who: "" },
      { key: "physics", label: "Physics", who: "" },
    ] as const);
  return (
    <div className="inline-flex rounded border border-hairline overflow-hidden">
      {items.map((lv) => (
        <button
          key={lv.key}
          type="button"
          onClick={() => onChange(lv.key)}
          title={lv.who}
          className={`text-xs px-2 py-1 transition-colors ${
            lv.key === value
              ? "bg-surface-2 text-ink font-medium"
              : "text-muted hover:text-ink-secondary"
          }`}
        >
          {lv.label}
        </button>
      ))}
    </div>
  );
}

function ExplanationBlock({ e }: { e: Explanation }) {
  const share = (s: number) => `${Math.round(s * 100)}%`;
  const opPairs = useMemo(() => Object.entries(e.operating_point), [e.operating_point]);

  return (
    <div className="rounded border border-hairline bg-surface-2/40 p-3 flex flex-col gap-2">
      <p className="text-sm text-ink leading-snug">
        <Jargon>{e.headline}</Jargon>
      </p>

      {/* An inexact answer says so at every depth. Trustworthiness is not a
          detail that deeper levels reveal. */}
      {e.caveat && (
        <p className="text-[11px] text-muted leading-snug border-l-2 border-hairline pl-2">
          {e.caveat}
        </p>
      )}

      {e.summary && (
        <p className="text-xs text-ink-secondary leading-snug">
          <Jargon>{e.summary}</Jargon>
        </p>
      )}

      {e.terms.length > 0 && (
        <div className="flex flex-col gap-1.5 mt-0.5">
          {e.terms.map((t) => (
            <div key={t.key} className="flex flex-col gap-0.5">
              <div className="flex items-baseline gap-2 text-xs">
                <span
                  className={`flex-1 ${t.negligible ? "text-muted" : "text-ink-secondary"}`}
                  title={t.why}
                >
                  {t.label}
                </span>
                <span className="tnums text-ink">{formatTerm(t.value, t.unit)}</span>
                <span className="tnums text-muted w-10 text-right">{share(t.share)}</span>
              </div>
              {/* A share bar, because "88% of what is going on" is a
                  proportion and proportions are read faster as length. */}
              <div className="h-0.5 rounded bg-hairline overflow-hidden">
                <div
                  className="h-full"
                  style={{
                    width: `${Math.max(t.share * 100, 0.5)}%`,
                    backgroundColor: t.value < 0 ? "#4fc3f7" : "#eda100",
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {e.equation && (
        <div className="text-[11px] text-muted font-mono mt-1 overflow-x-auto">{e.equation}</div>
      )}

      {opPairs.length > 0 && (
        <details className="text-[11px] text-muted">
          <summary className="cursor-pointer hover:text-ink-secondary">
            Evaluated at ({opPairs.length} values)
          </summary>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 mt-1">
            {opPairs.map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2">
                <span>{k}</span>
                <span className="tnums text-ink-secondary">{fmtNumber(v)}</span>
              </div>
            ))}
          </div>
        </details>
      )}

      {(e.assumptions.length > 0 || e.limits.length > 0) && (
        <div className="text-[11px] flex flex-col gap-1.5 mt-1">
          {e.assumptions.length > 0 && (
            <div>
              <div className="text-muted uppercase tracking-wide">Assumes</div>
              <ul className="list-disc list-inside text-ink-secondary">
                {e.assumptions.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
          )}
          {e.limits.length > 0 && (
            <div>
              <div className="text-muted uppercase tracking-wide">Cannot tell you</div>
              <ul className="list-disc list-inside text-ink-secondary">
                {e.limits.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function formatTerm(value: number, unit: string): string {
  if (unit === "×") return `×${value.toPrecision(3)}`;
  return `${fmtNumber(value)} ${unit}`.trim();
}

function fmtNumber(v: number): string {
  if (!Number.isFinite(v)) return "—";
  const m = Math.abs(v);
  if (m === 0) return "0";
  if (m >= 100) return v.toFixed(0);
  if (m >= 10) return v.toFixed(1);
  if (m >= 1) return v.toFixed(2);
  return v.toPrecision(3);
}
