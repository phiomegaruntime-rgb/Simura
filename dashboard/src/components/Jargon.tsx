import { useEffect, useMemo, useState } from "react";
import { fetchGlossary } from "../api/client";
import type { GlossaryEntry } from "../api/types";

/**
 * Underlines any glossary term inside a run of text and explains it on hover.
 *
 * The point of the "get familiar" layer is that a newcomer can read a sentence
 * that was written for an engineer without leaving the page to find out what
 * one word meant. So the explanation has to arrive *in place* — a link to a
 * glossary is a page a reader will not visit mid-sentence.
 *
 * Matching is done here rather than server-side because the same prose is
 * rendered in several places and the glossary is a single small payload fetched
 * once. Longest term first, so "voltage imbalance" is annotated as a phrase
 * instead of having "voltage" matched out from under it, and each term is
 * annotated at most once per block: an underline on every occurrence of "cell"
 * is noise, not help.
 */
export default function Jargon({ children }: { children: string }) {
  const [glossary, setGlossary] = useState<GlossaryEntry[] | null>(null);

  useEffect(() => {
    fetchGlossary().then(setGlossary).catch(() => {});
  }, []);

  const parts = useMemo(() => annotate(children, glossary ?? []), [children, glossary]);

  return (
    <>
      {parts.map((p, i) =>
        typeof p === "string" ? (
          <span key={i}>{p}</span>
        ) : (
          <abbr
            key={i}
            title={`${p.entry.term}: ${p.entry.short}`}
            className="no-underline border-b border-dotted border-muted cursor-help"
          >
            {p.text}
          </abbr>
        ),
      )}
    </>
  );
}

type Part = string | { text: string; entry: GlossaryEntry };

/** Split `text` into plain runs and annotated ones. Pure, so it is testable. */
export function annotate(text: string, glossary: GlossaryEntry[]): Part[] {
  if (glossary.length === 0) return [text];

  // Every surface form (canonical + aliases), longest first.
  const forms: { form: string; entry: GlossaryEntry }[] = [];
  for (const e of glossary) {
    forms.push({ form: e.term, entry: e });
    for (const a of e.aliases) forms.push({ form: a, entry: e });
  }
  forms.sort((a, b) => b.form.length - a.form.length);

  const used = new Set<string>();
  let parts: Part[] = [text];

  for (const { form, entry } of forms) {
    if (used.has(entry.term)) continue;
    const re = new RegExp(`\\b${escapeRe(form)}\\b`, "i");
    const next: Part[] = [];
    let matched = false;
    for (const part of parts) {
      if (typeof part !== "string" || matched) {
        next.push(part);
        continue;
      }
      const m = re.exec(part);
      if (!m) {
        next.push(part);
        continue;
      }
      matched = true;
      if (m.index > 0) next.push(part.slice(0, m.index));
      next.push({ text: m[0], entry });
      const rest = part.slice(m.index + m[0].length);
      if (rest) next.push(rest);
    }
    if (matched) {
      used.add(entry.term);
      parts = next;
    }
  }
  return parts;
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
