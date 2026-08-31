"""CLI for the system library. Fully offline: one JSON file, no services.

The twin core keeps the library in TimescaleDB, but nothing here needs it --
which is the point. A library you can only read while a database is up is not
memory that survives the project; it is memory that survives the container.

Examples::

    python -m simura.library --seed --list
    python -m simura.library --show bundled.rack-lfp-16s4p
    python -m simura.library --trace bundled.rack-lfp-16s4p-hot
    python -m simura.library --tree
    python -m simura.library --fork bundled.rack-lfp-16s4p --name "Site B rack" \\
        --set ambient_temp_c=38 --set cooling_conductance_w_per_k=1.5 \\
        --because "Site B is in Phoenix and has no fan budget"
    python -m simura.library --note site-b-rack-1a2b3c4d --text "Trips at 15:00" --kind gotcha
    python -m simura.library --diff before.json after.json

``--set`` takes dotted paths (``profile.params.charge_a=12``), so a fork can be
made from the shell without opening the builder.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

from .diff import diff_specs
from .record import Entry, LibraryError, Note, fork
from .store import JsonFileLibrary
from .templates import seed as seed_bundled

DEFAULT_PATH = "simura-library.json"


def _reconfigure_stdout() -> None:
    # Windows consoles default to cp1252; force UTF-8 so output never crashes.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def _wrap(text: str, indent: str = "  ", width: int = 78) -> str:
    import textwrap

    return textwrap.fill(text, width=width, initial_indent=indent, subsequent_indent=indent)


def _coerce(raw: str) -> Any:
    """A ``--set`` value as the type it looks like."""
    low = raw.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _apply(spec: dict[str, Any], assignment: str) -> dict[str, Any]:
    if "=" not in assignment:
        raise LibraryError(f"--set wants key=value, got '{assignment}'")
    path, raw = assignment.split("=", 1)
    cursor: Any = spec
    parts = path.strip().split(".")
    for part in parts[:-1]:
        if part not in cursor or not isinstance(cursor[part], dict):
            cursor[part] = {}
        cursor = cursor[part]
    cursor[parts[-1]] = _coerce(raw)
    return spec


# -- rendering -------------------------------------------------------------


def _row(entry: Entry) -> str:
    mark = "T" if entry.kind == "template" else " "
    check = "✓" if entry.validated else " "
    return f"{mark}{check} {entry.entry_id:<40}v{entry.version:<3}{entry.name}"


def _print_entry(entry: Entry, library: JsonFileLibrary) -> None:
    print(f"\n{entry.name}   [{entry.entry_id}]")
    print(f"  {entry.kind} · v{entry.version} · {entry.relation} · from {entry.source}"
          f"{' · validated' if entry.validated else ''}")
    if entry.summary:
        print(_wrap(entry.summary))
    if entry.tags:
        print(f"  tags: {', '.join(entry.tags)}")
    spec = entry.spec
    print(
        f"  spec: {spec.get('chemistry')} {spec.get('series')}S{spec.get('parallel')}P · "
        f"{spec.get('capacity_ah')} Ah · {spec.get('profile', {}).get('type')} · "
        f"{len(spec.get('faults') or [])} fault(s)"
    )
    if entry.decisions:
        print("\n  Decisions")
        for d in entry.decisions:
            print(f"    - {d.question}")
            print(_wrap(f"{d.choice} — {d.because}", "      "))
            if d.rejected:
                print(_wrap("rejected: " + "; ".join(d.rejected), "      "))
    if entry.notes:
        print("\n  Notes")
        for n in entry.notes:
            print(_wrap(f"[{n.kind}] {n.text}", "    "))
    kids = library.children(entry.entry_id)
    if kids:
        print("\n  Forked into")
        for k in kids:
            print(f"    - {k.entry_id}  {k.name}")


def _print_trace(story: dict[str, Any]) -> None:
    chain = story["chain"]
    print(
        f"\n{story['entry_id']}: {story['generations']} generation(s), "
        f"{story['changes']} change(s), {story['unexplained']} unexplained"
    )
    print(f"\n  origin: {chain[0]['name']}  [{chain[0]['entry_id']}]")
    for s in story["steps"]:
        who = f" by {s['author']}" if s["author"] else ""
        print(f"\n  {s['relation']} → {s['name']}  [{s['to']}]{who}")
        if not s["changes"]:
            # A promotion, or a fork taken unchanged into another project. Not
            # nothing: the record of taking it unchanged is the point.
            print("    (the same system, kept under a new name)")
        # One reason usually covers several fields; print it once under them.
        for group in _group(s["changes"]):
            for change in group["changes"]:
                print(f"    · {change['text']}")
            if group["decision"]:
                print(_wrap(f"because {group['decision']['because']}", "        "))
            else:
                print("        (no reason recorded)")


def _group(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group the API's paired changes by the reason they share (see
    :func:`simura.library.diff.group_by_reason`, over dicts rather than objects)."""
    groups: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    for item in items:
        decision = item["decision"]
        key = f"{decision['question']}|{decision['at']}" if decision else ""
        group = index.get(key)
        if group is None:
            group = {"decision": decision, "changes": []}
            index[key] = group
            groups.append(group)
        group["changes"].append(item["change"])
    return groups


def _print_tree(nodes: list[dict[str, Any]], depth: int = 0) -> None:
    for node in nodes:
        entry = node["entry"]
        prefix = "  " * depth + ("└─ " if depth else "")
        kind = "template" if entry["kind"] == "template" else entry["relation"]
        print(f"{prefix}{entry['name']}  [{entry['entry_id']}]  ({kind})")
        _print_tree(node["children"], depth + 1)


# -- commands --------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    p = argparse.ArgumentParser(
        prog="python -m simura.library",
        description="The system library: saved systems, their reasons, and their lineage.",
    )
    p.add_argument("--library", default=DEFAULT_PATH, help=f"library file (default {DEFAULT_PATH})")
    p.add_argument("--seed", action="store_true", help="add the bundled starter systems")
    p.add_argument("--list", action="store_true", help="list entries")
    p.add_argument("--kind", choices=("system", "template"), help="filter --list by kind")
    p.add_argument("--tag", help="filter --list by tag")
    p.add_argument("--query", default="", help="search names, notes and reasons")
    p.add_argument("--show", metavar="ID", help="show one entry in full")
    p.add_argument("--trace", metavar="ID", help="how this system got here")
    p.add_argument("--tree", action="store_true", help="the whole library as a lineage tree")
    p.add_argument("--fork", metavar="ID", help="fork an entry")
    p.add_argument("--name", help="name for the fork")
    p.add_argument("--because", help="why (required for a fork)")
    p.add_argument("--set", action="append", default=[], metavar="PATH=VALUE",
                   help="change a spec field in the fork; repeatable")
    p.add_argument("--author", default="", help="who is doing this")
    p.add_argument("--note", metavar="ID", help="attach a note to an entry")
    p.add_argument("--text", help="the note's text")
    p.add_argument("--kind-of-note", dest="note_kind", default="note",
                   choices=("note", "gotcha", "result"))
    p.add_argument("--export", action="store_true", help="print the library as JSON")
    p.add_argument("--diff", nargs=2, metavar=("BEFORE", "AFTER"),
                   help="diff two spec JSON files (no library needed)")
    args = p.parse_args(argv)

    if args.diff:
        before = json.loads(Path(args.diff[0]).read_text(encoding="utf-8"))
        after = json.loads(Path(args.diff[1]).read_text(encoding="utf-8"))
        changes = diff_specs(before, after)
        if not changes:
            print("no differences")
        for c in changes:
            print(f"  · {c.text()}")
            if c.why:
                print(_wrap(c.why, "      "))
        return 0

    library = JsonFileLibrary(args.library)

    try:
        if args.seed:
            added = seed_bundled(library)
            print(f"seeded {len(added)} entr{'y' if len(added) == 1 else 'ies'} into {args.library}")

        if args.fork:
            if not args.name or not args.because:
                p.error("--fork needs --name and --because")
            parent = library.require(args.fork)
            spec = copy.deepcopy(parent.spec)
            for assignment in args.set:
                _apply(spec, assignment)
            # A fork gets its own identity inside the spec too: a running twin
            # called by its parent's name is the confusion this component exists
            # to end.
            spec["name"] = args.name
            spec["system_id"] = re.sub(r"[^a-z0-9]+", "-", args.name.lower()).strip("-") or "fork"
            child = library.save(
                fork(parent, spec, name=args.name, because=args.because, author=args.author)
            )
            print(f"forked {parent.entry_id} → {child.entry_id}")
            _print_entry(child, library)
            return 0

        if args.note:
            if not args.text:
                p.error("--note needs --text")
            entry = library.add_note(
                args.note, Note(text=args.text, kind=args.note_kind, author=args.author)
            )
            print(f"noted on {entry.entry_id} ({len(entry.notes)} note(s))")
            return 0

        if args.show:
            _print_entry(library.require(args.show), library)
            return 0

        if args.trace:
            _print_trace(library.trace(args.trace))
            return 0

        if args.tree:
            _print_tree(library.tree())
            return 0

        if args.export:
            print(json.dumps({"version": 1, "entries": library.to_dicts()}, indent=2))
            return 0

        if args.list or args.seed:
            entries = library.list(kind=args.kind, tag=args.tag, query=args.query)
            summary = library.summary()
            print(
                f"{summary['entries']} entries · {summary['templates']} templates · "
                f"{summary['forks']} forks · {summary['decisions']} decisions · "
                f"{summary['notes']} notes"
            )
            print("-" * 78)
            for entry in entries:
                print(_row(entry))
            return 0
    except LibraryError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2

    p.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
