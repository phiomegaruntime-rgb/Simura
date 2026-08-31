import { useCallback, useEffect, useMemo, useState } from "react";
import {
  addLibraryDecision,
  addLibraryNote,
  deleteLibraryEntry,
  fetchLibrary,
  fetchLibraryEntry,
  fetchLibraryTrace,
  instantiateEntry,
  promoteEntry,
  seedLibrary,
  setLibraryValidated,
} from "../api/client";
import type {
  ExplainedChange,
  LibraryChange,
  LibraryDecision,
  LibraryDetail,
  LibraryEntry,
  LibraryRow,
  LibrarySummary,
  LibraryTrace,
} from "../api/types";

const ACCENT = "#3fb6a8";

const RELATION_LABEL: Record<string, string> = {
  origin: "first saved",
  revision: "new version of",
  fork: "forked from",
  promotion: "promoted from",
};

const NOTE_LABEL: Record<string, string> = {
  note: "Note",
  gotcha: "Gotcha",
  result: "Result",
};

/**
 * The library: every system anyone has saved, and why it looks the way it does.
 *
 * The one thing to understand before reading this file is that nothing here
 * renders a stored description of a change. "What changed from its parent" is
 * computed server-side from the two specs on every request (`changes`), and the
 * only human-written half is the reason attached to it. That is why a change can
 * arrive with `decision: null` — and why that case is rendered loudly rather
 * than hidden: an unexplained change is the most useful thing this screen can
 * tell the next person, because it is the question they should go and ask.
 */
export default function LibraryView({
  onOpenInBuilder,
  onOpenSystem,
}: {
  onOpenInBuilder?: (entry: LibraryEntry) => void;
  onOpenSystem?: (systemId: string) => void;
}) {
  const [rows, setRows] = useState<LibraryRow[]>([]);
  const [summary, setSummary] = useState<LibrarySummary | null>(null);
  const [kind, setKind] = useState<string>("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<LibraryDetail | null>(null);
  const [trace, setTrace] = useState<LibraryTrace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    fetchLibrary({ kind: kind || undefined, q: query || undefined })
      .then((r) => {
        setRows(r.entries);
        setSummary(r.summary);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, [kind, query]);

  useEffect(refresh, [refresh]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      setTrace(null);
      return;
    }
    let active = true;
    fetchLibraryEntry(selected)
      .then((d) => active && setDetail(d))
      .catch((e: Error) => active && setError(e.message));
    fetchLibraryTrace(selected)
      .then((t) => active && setTrace(t))
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [selected]);

  const reload = (d: LibraryDetail) => {
    setDetail(d);
    setSelected(d.entry.entry_id);
    fetchLibraryTrace(d.entry.entry_id).then(setTrace).catch(() => {});
    refresh();
  };

  const act = <T,>(p: Promise<T>, then?: (v: T) => void) => {
    setBusy(true);
    setError(null);
    p.then((v) => then?.(v))
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };

  const empty = rows.length === 0 && !query && !kind;

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg bg-surface border border-hairline px-5 py-4">
        <h2 className="text-lg font-semibold text-ink">The system library</h2>
        <p className="text-sm text-ink-secondary mt-1 max-w-3xl">
          Saved systems with the <span className="text-ink">reason</span> behind each choice, what
          they were forked from, and what was learned running them. What changed between two
          systems is computed from the specs themselves — the only thing anybody types is why.
        </p>
        {summary && (
          <div className="flex flex-wrap gap-x-5 gap-y-1 mt-3 text-sm text-ink-secondary">
            <Count n={summary.entries} label="systems" />
            <Count n={summary.templates} label="templates" />
            <Count n={summary.forks} label="forks" />
            <Count n={summary.decisions} label="recorded decisions" />
            <Count n={summary.notes} label="notes" />
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-md border border-critical/40 bg-surface px-4 py-3 text-sm text-critical">
          {error}
        </div>
      )}

      {empty ? (
        <div className="rounded-lg bg-surface border border-hairline px-5 py-8 text-center">
          <p className="text-ink-secondary max-w-xl mx-auto">
            The library is empty. Start it with a handful of systems somebody already thought
            about — two designs, a fork of each, and one of those promoted into a template.
          </p>
          <button
            type="button"
            disabled={busy}
            onClick={() => act(seedLibrary(), refresh)}
            className="mt-4 px-4 py-2 rounded-md text-sm font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: ACCENT }}
          >
            Add the starter systems
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] gap-4 items-start">
          <div className="flex flex-col gap-3">
            <div className="flex gap-2">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search names, notes and reasons…"
                className="flex-1 min-w-0 rounded-md bg-surface-2 border border-hairline px-3 py-1.5 text-sm text-ink placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-series"
              />
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value)}
                className="rounded-md bg-surface-2 border border-hairline px-2 py-1.5 text-sm text-ink"
              >
                <option value="">All</option>
                <option value="template">Templates</option>
                <option value="system">Systems</option>
              </select>
            </div>

            <div className="flex flex-col gap-2">
              {rows.map((row) => (
                <EntryRow
                  key={row.entry_id}
                  row={row}
                  active={row.entry_id === selected}
                  onOpen={() => setSelected(row.entry_id)}
                />
              ))}
              {rows.length === 0 && (
                <p className="text-sm text-muted px-1">Nothing matches that.</p>
              )}
            </div>
          </div>

          {detail ? (
            <EntryDetail
              detail={detail}
              trace={trace}
              busy={busy}
              onSelect={setSelected}
              onOpenInBuilder={onOpenInBuilder}
              onRun={(entryId, systemId) =>
                act(instantiateEntry(entryId, systemId ? { system_id: systemId } : {}), (r) => {
                  refresh();
                  onOpenSystem?.(r.system_id);
                })
              }
              onPromote={(entryId, because) => act(promoteEntry(entryId, { because }), reload)}
              onNote={(entryId, text, noteKind) =>
                act(addLibraryNote(entryId, { text, kind: noteKind }), reload)
              }
              onDecision={(entryId, body) => act(addLibraryDecision(entryId, body), reload)}
              onValidate={(entryId, validated) =>
                act(setLibraryValidated(entryId, validated), reload)
              }
              onDelete={(entryId) =>
                act(deleteLibraryEntry(entryId), () => {
                  setSelected(null);
                  refresh();
                })
              }
            />
          ) : (
            <div className="rounded-lg bg-surface border border-hairline px-5 py-10 text-center text-muted">
              Pick a system to read what it is, why it is that way, and where it came from.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Count({ n, label }: { n: number; label: string }) {
  return (
    <span>
      <span className="text-ink tnums font-medium">{n}</span> {label}
    </span>
  );
}

function EntryRow({
  row,
  active,
  onOpen,
}: {
  row: LibraryRow;
  active: boolean;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={`text-left rounded-lg border px-4 py-3 transition-colors ${
        active ? "bg-surface-2" : "bg-surface hover:bg-surface-2"
      }`}
      style={{ borderColor: active ? `${ACCENT}88` : undefined }}
    >
      <div className="flex items-start gap-2">
        <span className="text-sm font-medium text-ink flex-1">{row.name}</span>
        {row.kind === "template" && (
          <span
            className="text-[10px] font-semibold uppercase tracking-wide rounded px-1.5 py-0.5"
            style={{ backgroundColor: `${ACCENT}22`, color: ACCENT }}
          >
            Template
          </span>
        )}
        {row.validated && <span className="text-good text-xs" title="Checked by a person">✓</span>}
      </div>
      <div className="text-xs text-muted mt-1">
        {row.spec.chemistry} {row.spec.series}S{row.spec.parallel}P · v{row.version}
        {row.child_count > 0 && ` · ${row.child_count} fork${row.child_count > 1 ? "s" : ""}`}
      </div>
      {row.change_summary && (
        <div className="text-xs text-ink-secondary mt-1.5 leading-snug">
          {RELATION_LABEL[row.relation] ?? row.relation}: {row.change_summary}
        </div>
      )}
    </button>
  );
}

function EntryDetail({
  detail,
  trace,
  busy,
  onSelect,
  onOpenInBuilder,
  onRun,
  onPromote,
  onNote,
  onDecision,
  onValidate,
  onDelete,
}: {
  detail: LibraryDetail;
  trace: LibraryTrace | null;
  busy: boolean;
  onSelect: (entryId: string) => void;
  onOpenInBuilder?: (entry: LibraryEntry) => void;
  onRun: (entryId: string, systemId?: string) => void;
  onPromote: (entryId: string, because: string) => void;
  onNote: (entryId: string, text: string, kind: string) => void;
  onDecision: (
    entryId: string,
    body: { question: string; because: string; params: string[] },
  ) => void;
  onValidate: (entryId: string, validated: boolean) => void;
  onDelete: (entryId: string) => void;
}) {
  const { entry, parent, changes, coverage, ancestry, children, inherited } = detail;
  const [promoting, setPromoting] = useState(false);
  const [because, setBecause] = useState("");
  const spec = entry.spec;

  const unexplained = useMemo(() => changes.filter((c) => !c.decision), [changes]);

  return (
    <div className="flex flex-col gap-4 min-w-0">
      <div className="rounded-lg bg-surface border border-hairline px-5 py-4">
        <div className="flex items-start gap-3 flex-wrap">
          <div className="flex-1 min-w-0">
            <h3 className="text-lg font-semibold text-ink">{entry.name}</h3>
            <p className="text-xs text-muted mt-0.5">
              {entry.kind} · v{entry.version} ·{" "}
              {parent ? (
                <>
                  {RELATION_LABEL[entry.relation]}{" "}
                  <button
                    type="button"
                    className="underline decoration-dotted hover:text-ink"
                    onClick={() => onSelect(parent.entry_id)}
                  >
                    {parent.name}
                  </button>
                </>
              ) : (
                RELATION_LABEL.origin
              )}
              {entry.author && ` · by ${entry.author}`} ·{" "}
              {entry.source === "twin" ? "captured from a running twin" : `from the ${entry.source}`}
            </p>
          </div>
          <div className="flex gap-2 flex-wrap">
            <Action label="Run it" primary disabled={busy} onClick={() => onRun(entry.entry_id)} />
            {onOpenInBuilder && (
              <Action
                label="Open in builder"
                disabled={busy}
                onClick={() => onOpenInBuilder(entry)}
              />
            )}
            {entry.kind !== "template" && (
              <Action label="Promote…" disabled={busy} onClick={() => setPromoting((p) => !p)} />
            )}
          </div>
        </div>

        {entry.summary && <p className="text-sm text-ink-secondary mt-3">{entry.summary}</p>}

        <div className="flex flex-wrap items-center gap-1.5 mt-3">
          {entry.tags.map((t) => (
            <span
              key={t}
              className="text-[11px] rounded px-1.5 py-0.5 text-ink-secondary bg-surface-2 border border-hairline"
            >
              {t}
            </span>
          ))}
          <button
            type="button"
            disabled={busy}
            onClick={() => onValidate(entry.entry_id, !entry.validated)}
            className={`ml-auto text-xs rounded px-2 py-1 border ${
              entry.validated
                ? "border-good/50 text-good"
                : "border-hairline text-muted hover:text-ink-secondary"
            }`}
            title="Only a person can set this: a spec that runs is not a spec that is right."
          >
            {entry.validated ? "✓ Checked against something real" : "Mark as checked"}
          </button>
        </div>

        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-2 mt-4 text-sm">
          <Fact label="Chemistry" value={spec.chemistry} />
          <Fact label="Topology" value={`${spec.series}S${spec.parallel}P`} />
          <Fact label="Cell capacity" value={`${spec.capacity_ah} Ah`} />
          <Fact label="Load" value={spec.profile.type} />
          <Fact label="Ambient" value={`${spec.ambient_temp_c} °C`} />
          <Fact label="Weather" value={spec.weather?.type ?? "none"} />
          <Fact label="Duration" value={`${(spec.duration_s / 3600).toFixed(1)} h`} />
          <Fact label="Faults" value={String(spec.faults?.length ?? 0)} />
        </dl>

        {promoting && (
          <div className="mt-4 rounded-md border border-hairline bg-surface-2 px-4 py-3">
            <label className="text-xs uppercase tracking-wide text-muted">
              What makes this worth starting from?
            </label>
            <textarea
              value={because}
              onChange={(e) => setBecause(e.target.value)}
              rows={2}
              className="mt-1 w-full rounded-md bg-surface border border-hairline px-3 py-2 text-sm text-ink"
              placeholder="Every project on a hot site re-derives this and re-argues the same fan…"
            />
            <div className="flex gap-2 mt-2">
              <Action
                label="Promote to template"
                primary
                disabled={busy || !because.trim()}
                onClick={() => {
                  onPromote(entry.entry_id, because);
                  setBecause("");
                  setPromoting(false);
                }}
              />
              <Action label="Cancel" onClick={() => setPromoting(false)} />
            </div>
          </div>
        )}
      </div>

      {/* What changed from the parent, each paired with the reason for it. */}
      {parent && (
        <Panel
          title={`What changed from ${parent.name}`}
          note={
            coverage.complete
              ? `${coverage.total} change${coverage.total === 1 ? "" : "s"}, all accounted for`
              : `${unexplained.length} of ${coverage.total} with no reason recorded`
          }
          level={coverage.complete ? "good" : "warn"}
        >
          {changes.length === 0 ? (
            <p className="text-sm text-ink-secondary">
              Nothing. This is the same system under a new name — which is a record worth having.
            </p>
          ) : (
            <ul className="flex flex-col gap-3">
              {groupByReason(changes).map((g, i) => (
                <ChangeGroup key={i} group={g} />
              ))}
            </ul>
          )}
          {!coverage.complete && (
            <UnexplainedForm
              entryId={entry.entry_id}
              paths={unexplained.map((c) => c.change)}
              busy={busy}
              onDecision={onDecision}
            />
          )}
        </Panel>
      )}

      {entry.decisions.length > 0 && (
        <Panel title="Decisions" note="Why the numbers are the numbers">
          <ul className="flex flex-col gap-3">
            {entry.decisions.map((d, i) => (
              <li key={i} className="border-l-2 pl-3" style={{ borderColor: `${ACCENT}66` }}>
                <div className="text-sm text-ink font-medium">{d.question}</div>
                <div className="text-sm text-ink-secondary mt-0.5">
                  <span className="text-ink">{d.choice}</span> — {d.because}
                </div>
                {d.rejected.length > 0 && (
                  <div className="text-xs text-muted mt-1">
                    Rejected: {d.rejected.join("; ")}
                  </div>
                )}
                {d.params.length > 0 && (
                  <div className="text-[11px] text-muted mt-1 tnums">covers {d.params.join(", ")}</div>
                )}
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <NotesPanel entry={entry} busy={busy} onNote={onNote} />

      {(inherited.notes.length > 0 || inherited.decisions.length > 0) && (
        <Panel
          title="Inherited from further up"
          note="Written on the systems this one came from"
        >
          <ul className="flex flex-col gap-2">
            {inherited.notes.map((n, i) => (
              <li key={`n${i}`} className="text-sm text-ink-secondary">
                <span className="text-[10px] uppercase tracking-wide text-muted mr-2">
                  {NOTE_LABEL[n.kind] ?? n.kind}
                </span>
                {n.text}
                <button
                  type="button"
                  className="ml-2 text-xs text-muted underline decoration-dotted hover:text-ink"
                  onClick={() => onSelect(n.from)}
                >
                  {n.from_name}
                </button>
              </li>
            ))}
            {inherited.decisions.map((d, i) => (
              <li key={`d${i}`} className="text-sm text-ink-secondary">
                <span className="text-ink">{d.question}</span> — {d.because}
                <button
                  type="button"
                  className="ml-2 text-xs text-muted underline decoration-dotted hover:text-ink"
                  onClick={() => onSelect(d.from)}
                >
                  {d.from_name}
                </button>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      {trace && trace.generations > 0 && (
        <Panel
          title="How this got here"
          note={`${trace.generations} generation${trace.generations === 1 ? "" : "s"} · ${
            trace.changes
          } change${trace.changes === 1 ? "" : "s"}${
            trace.unexplained ? ` · ${trace.unexplained} unexplained` : ""
          }`}
        >
          <ol className="flex flex-col gap-3">
            {ancestry.map((step, i) => (
              <li key={step.entry_id} className="flex gap-3">
                <span className="text-xs text-muted tnums w-5 shrink-0 pt-0.5">{i + 1}</span>
                <div className="min-w-0">
                  <button
                    type="button"
                    className={`text-sm ${
                      step.entry_id === entry.entry_id
                        ? "text-ink font-medium"
                        : "text-ink-secondary underline decoration-dotted hover:text-ink"
                    }`}
                    onClick={() => onSelect(step.entry_id)}
                  >
                    {step.name}
                  </button>
                  {i > 0 && trace.steps[i - 1] && (
                    <div className="text-xs text-muted mt-0.5">
                      {RELATION_LABEL[trace.steps[i - 1].relation] ?? trace.steps[i - 1].relation}{" "}
                      the one above ·{" "}
                      {trace.steps[i - 1].coverage.total} change
                      {trace.steps[i - 1].coverage.total === 1 ? "" : "s"}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </Panel>
      )}

      {children.length > 0 && (
        <Panel title="What grew out of this" note={`${children.length}`}>
          <ul className="flex flex-col gap-2">
            {children.map((c) => (
              <li key={c.entry_id}>
                <button
                  type="button"
                  className="text-sm text-ink-secondary underline decoration-dotted hover:text-ink"
                  onClick={() => onSelect(c.entry_id)}
                >
                  {c.name}
                </button>
                {c.change_summary && (
                  <span className="text-xs text-muted ml-2">{c.change_summary}</span>
                )}
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <div className="flex justify-end">
        <button
          type="button"
          disabled={busy}
          onClick={() => onDelete(entry.entry_id)}
          className="text-xs text-muted hover:text-critical underline decoration-dotted"
          title="Forks of this system survive; their lineage simply stops here."
        >
          Delete this entry
        </button>
      </div>
    </div>
  );
}

/**
 * Collect changes under the reason they share.
 *
 * One decision usually covers several fields — somebody moves the ambient and
 * the cooling in the same breath, for the same reason — and repeating that
 * sentence under each field turns a paragraph into a wall. Everything with no
 * reason at all lands in one final group, which is the group worth reading.
 */
function groupByReason(paired: ExplainedChange[]) {
  const groups: { decision: LibraryDecision | null; changes: LibraryChange[] }[] = [];
  const seen = new Map<string, { decision: LibraryDecision | null; changes: LibraryChange[] }>();
  for (const item of paired) {
    const key = item.decision ? `${item.decision.question}|${item.decision.at}` : "";
    let group = seen.get(key);
    if (!group) {
      group = { decision: item.decision, changes: [] };
      seen.set(key, group);
      groups.push(group);
    }
    group.changes.push(item.change);
  }
  return groups;
}

function ChangeGroup({
  group,
}: {
  group: { decision: LibraryDecision | null; changes: LibraryChange[] };
}) {
  const { decision, changes } = group;
  return (
    <li className="border-l-2 pl-3" style={{ borderColor: decision ? `${ACCENT}66` : "#eda10088" }}>
      {changes.map((c) => (
        <div key={c.path} className="text-sm text-ink">
          {c.text}
        </div>
      ))}
      {decision ? (
        <div className="text-sm text-ink-secondary mt-1">because {decision.because}</div>
      ) : (
        <div className="text-sm text-warn mt-1">
          No reason recorded. {changes[0]?.why}
        </div>
      )}
    </li>
  );
}

function UnexplainedForm({
  entryId,
  paths,
  busy,
  onDecision,
}: {
  entryId: string;
  paths: { key: string; label: string }[];
  busy: boolean;
  onDecision: (
    entryId: string,
    body: { question: string; because: string; params: string[] },
  ) => void;
}) {
  const [because, setBecause] = useState("");
  const [picked, setPicked] = useState<string[]>(paths.map((p) => p.key));

  const toggle = (key: string) =>
    setPicked((cur) => (cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key]));

  return (
    <div className="mt-4 rounded-md border border-hairline bg-surface-2 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-muted">Fill in the gap</div>
      <p className="text-xs text-ink-secondary mt-1">
        A reason recorded here is bound to the fields you tick, so it stays attached to them
        however the system is forked later.
      </p>
      <div className="flex flex-wrap gap-1.5 mt-2">
        {paths.map((p) => (
          <button
            key={p.key}
            type="button"
            onClick={() => toggle(p.key)}
            className={`text-[11px] rounded px-1.5 py-0.5 border ${
              picked.includes(p.key)
                ? "text-ink border-hairline bg-surface"
                : "text-muted border-hairline"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>
      <textarea
        value={because}
        onChange={(e) => setBecause(e.target.value)}
        rows={2}
        placeholder="Because…"
        className="mt-2 w-full rounded-md bg-surface border border-hairline px-3 py-2 text-sm text-ink"
      />
      <Action
        label="Record the reason"
        primary
        disabled={busy || !because.trim() || picked.length === 0}
        onClick={() => {
          onDecision(entryId, {
            question: `Why ${paths
              .filter((p) => picked.includes(p.key))
              .map((p) => p.label.toLowerCase())
              .join(", ")}?`,
            because,
            params: picked,
          });
          setBecause("");
        }}
      />
    </div>
  );
}

function NotesPanel({
  entry,
  busy,
  onNote,
}: {
  entry: LibraryEntry;
  busy: boolean;
  onNote: (entryId: string, text: string, kind: string) => void;
}) {
  const [text, setText] = useState("");
  const [kind, setKind] = useState("note");

  return (
    <Panel title="Notes" note="What running it actually taught somebody">
      {entry.notes.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {entry.notes.map((n, i) => (
            <li key={i} className="text-sm text-ink-secondary">
              <span className="text-[10px] uppercase tracking-wide text-muted mr-2">
                {NOTE_LABEL[n.kind] ?? n.kind}
              </span>
              {n.text}
              {n.author && <span className="text-xs text-muted ml-2">— {n.author}</span>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">Nothing yet. The next person would like there to be.</p>
      )}
      <div className="flex gap-2 mt-3">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Leave what you learned…"
          className="flex-1 min-w-0 rounded-md bg-surface-2 border border-hairline px-3 py-1.5 text-sm text-ink placeholder:text-muted"
        />
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          className="rounded-md bg-surface-2 border border-hairline px-2 py-1.5 text-sm text-ink"
        >
          <option value="note">Note</option>
          <option value="gotcha">Gotcha</option>
          <option value="result">Result</option>
        </select>
        <Action
          label="Add"
          disabled={busy || !text.trim()}
          onClick={() => {
            onNote(entry.entry_id, text, kind);
            setText("");
          }}
        />
      </div>
    </Panel>
  );
}

function Panel({
  title,
  note,
  level,
  children,
}: {
  title: string;
  note?: string;
  level?: "good" | "warn";
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg bg-surface border border-hairline px-5 py-4">
      <div className="flex items-baseline gap-3 mb-3">
        <h4 className="text-sm font-semibold text-ink">{title}</h4>
        {note && (
          <span
            className={`text-xs ${
              level === "warn" ? "text-warn" : level === "good" ? "text-good" : "text-muted"
            }`}
          >
            {note}
          </span>
        )}
      </div>
      {children}
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wide text-muted">{label}</dt>
      <dd className="text-ink tnums">{value}</dd>
    </div>
  );
}

function Action({
  label,
  onClick,
  primary,
  disabled,
}: {
  label: string;
  onClick: () => void;
  primary?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`px-3 py-1.5 rounded-md text-sm font-medium disabled:opacity-50 ${
        primary ? "text-white" : "text-ink-secondary bg-surface-2 border border-hairline hover:text-ink"
      }`}
      style={primary ? { backgroundColor: ACCENT } : undefined}
    >
      {label}
    </button>
  );
}
