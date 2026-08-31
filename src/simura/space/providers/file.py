"""The base every file-backed importer shares.

Two behaviours, both of which every importer would otherwise reimplement slightly
differently:

**Parse once.** :meth:`plan` is expected to be cheap to call twice -- the API
calls it per request, the dashboard calls it per render -- and parsing a large
model is not. So the parsed plan is cached on the instance, and the subclass only
implements :meth:`_parse`.

**Fingerprint the source.** Every plan records the SHA-256 of the bytes it came
from, which is what makes it traceable back to an exact file and what lets a
re-import of a changed model be recognised as a *different* plan rather than a
silent replacement.

Sources arrive either as a path or as bytes, because both callers are real: the
CLI has a file, and the HTTP upload endpoint has an in-memory body it should not
have to write to disk first.
"""

from __future__ import annotations

from pathlib import Path

from ..fidelity import FidelityLog
from ..plan import FloorPlan
from ..provider import PlanError


class FilePlanProvider:
    """A plan parsed from a file or a blob, cached after the first read."""

    #: Short format name, used in the fidelity record and by ``build_provider``.
    format: str = "file"

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        data: bytes | None = None,
        name: str = "",
        encoding: str = "utf-8",
    ) -> None:
        if path is None and data is None:
            raise PlanError(f"{self.format} provider needs a 'path' or 'data'")
        self.path = str(path) if path is not None else ""
        self._data = data
        self.name = name or (Path(self.path).name if self.path else f"<{self.format}>")
        self.encoding = encoding
        self._plan: FloorPlan | None = None

    # -- reading ----------------------------------------------------------
    def raw(self) -> bytes:
        """The source bytes, read from disk on first use."""
        if self._data is None:
            try:
                self._data = Path(self.path).read_bytes()
            except OSError as exc:
                raise PlanError(f"cannot read {self.path}: {exc}") from None
        return self._data

    def text(self) -> str:
        """The source decoded as text, tolerating the mojibake models arrive with.

        ``errors="replace"`` rather than a raise: a stray byte in a room name is
        not a reason to refuse a building, and the replacement character shows up
        in the name where somebody can see it.
        """
        return self.raw().decode(self.encoding, errors="replace")

    # -- the contract -----------------------------------------------------
    def plan(self) -> FloorPlan:
        if self._plan is None:
            log = FidelityLog(self.format, self.name)
            log.hash_bytes(self.raw())
            self._plan = self._parse(log)
        return self._plan

    def _parse(self, log: FidelityLog) -> FloorPlan:  # pragma: no cover - abstract
        raise NotImplementedError
