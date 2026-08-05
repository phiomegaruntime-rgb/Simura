// Placeholder locations — update these when the repo / docs site go public.
// (Kept in one place so it's a one-line change per link.)
const DOCS_URL = "https://celltwin.github.io";
const REPO_URL = "https://github.com/simura/celltwin";

const LINKS: { label: string; href: string }[] = [
  { label: "Documentation", href: DOCS_URL },
  { label: "License", href: `${REPO_URL}/blob/main/LICENSE` },
  { label: "How to contribute", href: `${REPO_URL}/blob/main/CONTRIBUTING.md` },
  { label: "Terms", href: `${DOCS_URL}/terms/` },
  { label: "Privacy", href: `${DOCS_URL}/privacy/` },
];

export default function Footer() {
  const year = new Date().getFullYear();
  return (
    <footer className="border-t border-hairline bg-surface px-6 py-4 text-xs text-muted">
      <div className="max-w-[1400px] mx-auto flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <div className="flex items-center gap-1.5">
          <span className="text-ink-secondary font-medium">CellTwin</span>
          <span>— a</span>
          <span className="text-ink-secondary font-semibold">Simura</span>
          <span>product</span>
          <span className="text-muted">·</span>
          <span>© {year} Simura</span>
          <span className="text-muted">·</span>
          <span>Apache-2.0</span>
        </div>
        <nav className="flex flex-wrap items-center gap-x-4 gap-y-1">
          {LINKS.map((l) => (
            <a
              key={l.label}
              href={l.href}
              target="_blank"
              rel="noreferrer noopener"
              className="hover:text-ink focus:outline-none focus:ring-1 focus:ring-series rounded"
            >
              {l.label}
            </a>
          ))}
        </nav>
      </div>
    </footer>
  );
}
