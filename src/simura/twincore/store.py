"""TimescaleStore: persistence for the twin, backed by TimescaleDB via asyncpg.

Kept deliberately thin and SQL-first -- the queries are the interesting part and
should be readable at a glance. TimescaleDB is just PostgreSQL, so the hypertable
DDL lives in ``schema.sql`` and everything else is plain parameterized SQL.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import asyncpg

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class TimescaleStore:
    def __init__(self, dsn: str, min_pool: int = 1, max_pool: int = 5) -> None:
        self._dsn = dsn
        self._min_pool = min_pool
        self._max_pool = max_pool
        self._pool: Optional[asyncpg.Pool] = None

    # -- lifecycle --------------------------------------------------------
    async def connect(self, retries: int = 30, retry_s: float = 2.0) -> None:
        """Create the connection pool, retrying while the DB comes up.

        Under docker compose the database may still be starting when the twin
        core launches, so we retry rather than crash-loop.
        """
        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                self._pool = await asyncpg.create_pool(
                    self._dsn, min_size=self._min_pool, max_size=self._max_pool
                )
                return
            except (OSError, asyncpg.PostgresError) as err:  # not ready yet
                last_err = err
                await asyncio.sleep(retry_s)
        raise RuntimeError(f"could not connect to database after {retries} attempts") from last_err

    async def init_schema(self) -> None:
        sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        async with self._pool.acquire() as conn:
            # No args => simple query protocol, which allows multiple statements.
            await conn.execute(sql)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()

    # -- registry ---------------------------------------------------------
    async def upsert_system(
        self, system_id: str, name: str | None, config: dict | None
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO systems (system_id, name, config, updated_at)
                VALUES ($1, $2, $3, now())
                ON CONFLICT (system_id) DO UPDATE
                    SET name = COALESCE(EXCLUDED.name, systems.name),
                        config = COALESCE(EXCLUDED.config, systems.config),
                        updated_at = now()
                """,
                system_id,
                name,
                json.dumps(config) if config is not None else None,
            )

    async def list_systems(self) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT system_id, name, config, source, spec, run_state, "
                "library_entry_id, created_at, updated_at FROM systems ORDER BY system_id"
            )
        return [_system_row(r) for r in rows]

    async def get_system(self, system_id: str) -> Optional[dict[str, Any]]:
        """One registry row, or ``None``. Used where only the spec is wanted."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT system_id, name, config, source, spec, run_state, "
                "library_entry_id, created_at, updated_at FROM systems WHERE system_id = $1",
                system_id,
            )
        return _system_row(row) if row else None

    async def create_system(
        self,
        system_id: str,
        name: str | None,
        source: str,
        spec: dict | None,
        run_state: str,
        library_entry_id: str | None = None,
    ) -> None:
        """Register a system with its source/spec/run_state (create or replace).

        Used by ``POST /api/systems``. Unlike :meth:`upsert_system` (the ingest
        path, which only touches name/config), this owns the lifecycle columns.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO systems (
                    system_id, name, source, spec, run_state, library_entry_id, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, now())
                ON CONFLICT (system_id) DO UPDATE
                    SET name = COALESCE(EXCLUDED.name, systems.name),
                        source = EXCLUDED.source,
                        spec = EXCLUDED.spec,
                        run_state = EXCLUDED.run_state,
                        library_entry_id = EXCLUDED.library_entry_id,
                        updated_at = now()
                """,
                system_id,
                name,
                source,
                json.dumps(spec) if spec is not None else None,
                run_state,
                library_entry_id,
            )

    async def set_run_state(self, system_id: str, run_state: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE systems SET run_state = $2, updated_at = now() WHERE system_id = $1",
                system_id,
                run_state,
            )

    async def delete_system(self, system_id: str) -> None:
        """Purge a system: the registry row and all of its time-series history."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for table in (
                    "pack_telemetry",
                    "cell_telemetry",
                    "anomaly_summary",
                    "assessment_summary",
                ):
                    await conn.execute(f"DELETE FROM {table} WHERE system_id = $1", system_id)
                await conn.execute("DELETE FROM systems WHERE system_id = $1", system_id)

    # -- library (Component 17) -------------------------------------------
    # Persistence only. Every rule about what an entry is -- when a reason is
    # required, what a fork means, how a lineage is walked -- lives in
    # ``simura.library`` and is not repeated here; these methods move
    # ``Entry.to_dict()`` shaped rows in and out.

    async def library_save(self, entry: dict[str, Any]) -> bool:
        """Insert an entry with its notes and decisions. False if it already exists.

        Ids are content hashes, so a conflict means the identical entry is
        already stored: nothing is overwritten, and in particular the notes
        somebody has since written on it are left alone.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                inserted = await conn.fetchval(
                    """
                    INSERT INTO library_entries (
                        entry_id, name, spec, kind, version, parent_id, relation,
                        source, source_system_id, author, summary, tags, validated,
                        created_at
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                    ON CONFLICT (entry_id) DO NOTHING
                    RETURNING entry_id
                    """,
                    entry["entry_id"],
                    entry["name"],
                    json.dumps(entry["spec"]),
                    entry.get("kind", "system"),
                    int(entry.get("version", 1)),
                    entry.get("parent_id"),
                    entry.get("relation", "origin"),
                    entry.get("source", "builder"),
                    entry.get("source_system_id"),
                    entry.get("author", ""),
                    entry.get("summary", ""),
                    list(entry.get("tags") or []),
                    bool(entry.get("validated", False)),
                    _ts(entry.get("created_at")),
                )
                if inserted is None:
                    return False
                for note in entry.get("notes") or []:
                    await _insert_note(conn, entry["entry_id"], note)
                for decision in entry.get("decisions") or []:
                    await _insert_decision(conn, entry["entry_id"], decision)
                return True

    async def library_add_note(self, entry_id: str, note: dict[str, Any]) -> None:
        async with self._pool.acquire() as conn:
            await _insert_note(conn, entry_id, note)

    async def library_add_decision(self, entry_id: str, decision: dict[str, Any]) -> None:
        async with self._pool.acquire() as conn:
            await _insert_decision(conn, entry_id, decision)

    async def library_set_validated(self, entry_id: str, validated: bool) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE library_entries SET validated = $2 WHERE entry_id = $1",
                entry_id,
                bool(validated),
            )

    async def library_delete(self, entry_id: str) -> bool:
        """Delete one entry (its notes and decisions cascade).

        Children are left pointing at an id that is gone, on purpose: a fork is
        somebody else's system and must survive the tidying of the design it
        came from.
        """
        async with self._pool.acquire() as conn:
            tag = await conn.execute("DELETE FROM library_entries WHERE entry_id = $1", entry_id)
        return tag.endswith("1")

    async def library_list(self) -> list[dict[str, Any]]:
        """Every entry, with its notes and decisions attached.

        The whole library in one call rather than a page of it: lineage is a
        walk over the entries, so a partial view would answer "how did this get
        here" with a partial story. A library is documents, not telemetry -- it
        does not grow the way a hypertable does.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM library_entries ORDER BY created_at, entry_id"
            )
            notes = await conn.fetch(
                "SELECT entry_id, text, kind, author, at FROM library_notes ORDER BY at, id"
            )
            decisions = await conn.fetch(
                "SELECT entry_id, question, choice, because, params, rejected, author, at "
                "FROM library_decisions ORDER BY at, id"
            )
        by_entry_notes: dict[str, list[dict[str, Any]]] = {}
        for n in notes:
            by_entry_notes.setdefault(n["entry_id"], []).append(
                {"text": n["text"], "kind": n["kind"], "author": n["author"],
                 "at": _iso(n["at"])}
            )
        by_entry_decisions: dict[str, list[dict[str, Any]]] = {}
        for d in decisions:
            by_entry_decisions.setdefault(d["entry_id"], []).append(
                {"question": d["question"], "choice": d["choice"], "because": d["because"],
                 "params": list(d["params"] or []), "rejected": list(d["rejected"] or []),
                 "author": d["author"], "at": _iso(d["at"])}
            )
        out = []
        for r in rows:
            entry = dict(r)
            if isinstance(entry.get("spec"), str):
                entry["spec"] = json.loads(entry["spec"])
            entry["tags"] = list(entry.get("tags") or [])
            entry["created_at"] = _iso(entry["created_at"])
            entry["notes"] = by_entry_notes.get(entry["entry_id"], [])
            entry["decisions"] = by_entry_decisions.get(entry["entry_id"], [])
            out.append(entry)
        return out

    # -- writes -----------------------------------------------------------
    async def insert_pack(self, system_id: str, ts: datetime, tel: dict[str, Any]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO pack_telemetry (
                    time, system_id, sim_time_s, pack_voltage_v, pack_current_a,
                    pack_power_w, pack_soc, max_temp_c, min_cell_voltage_v,
                    max_cell_voltage_v, voltage_imbalance_v
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                """,
                ts,
                system_id,
                tel.get("time_s"),
                tel.get("pack_voltage_v"),
                tel.get("pack_current_a"),
                tel.get("pack_power_w"),
                tel.get("pack_soc"),
                tel.get("max_temp_c"),
                tel.get("min_cell_voltage_v"),
                tel.get("max_cell_voltage_v"),
                tel.get("voltage_imbalance_v"),
            )

    async def insert_cells(
        self, system_id: str, ts: datetime, cells: list[dict[str, Any]]
    ) -> None:
        if not cells:
            return
        records = [
            (
                ts,
                system_id,
                c["series_index"],
                c["parallel_index"],
                c.get("voltage_v"),
                c.get("current_a"),
                c.get("temp_c"),
                c.get("soc"),
            )
            for c in cells
        ]
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO cell_telemetry (
                    time, system_id, series_index, parallel_index,
                    voltage_v, current_a, temp_c, soc
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                """,
                records,
            )

    async def insert_anomaly_summary(
        self, system_id: str, ts: datetime, report: dict[str, Any]
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO anomaly_summary (
                    time, system_id, sim_time_s, max_score, flagged_count,
                    worst_series, worst_parallel, worst_driver
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                """,
                ts,
                system_id,
                report.get("time_s"),
                report.get("max_score"),
                report.get("flagged_count"),
                report.get("worst_series"),
                report.get("worst_parallel"),
                report.get("worst_driver"),
            )

    async def anomaly_history(
        self,
        system_id: str,
        start: datetime,
        end: datetime,
        bucket_s: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Anomaly score history, optionally downsampled (max score per bucket)."""
        async with self._pool.acquire() as conn:
            if bucket_s and bucket_s > 0:
                rows = await conn.fetch(
                    """
                    SELECT time_bucket(make_interval(secs => $4), time) AS bucket,
                           max(max_score)     AS max_score,
                           max(flagged_count) AS flagged_count
                    FROM anomaly_summary
                    WHERE system_id = $1 AND time >= $2 AND time <= $3
                    GROUP BY bucket
                    ORDER BY bucket
                    """,
                    system_id,
                    start,
                    end,
                    bucket_s,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT time AS bucket, max_score, flagged_count
                    FROM anomaly_summary
                    WHERE system_id = $1 AND time >= $2 AND time <= $3
                    ORDER BY time
                    """,
                    system_id,
                    start,
                    end,
                )
        return [dict(r) for r in rows]

    async def insert_assessment_summary(
        self, system_id: str, ts: datetime, report: dict[str, Any]
    ) -> None:
        diag = report.get("diagnosis") or {}
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO assessment_summary (
                    time, system_id, sim_time_s, pack_soh, worst_cell_soh,
                    fault_type, confidence, safety_state, min_time_to_critical_s
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                """,
                ts,
                system_id,
                report.get("time_s"),
                report.get("pack_soh"),
                report.get("worst_cell_soh"),
                diag.get("fault_type"),
                diag.get("confidence"),
                report.get("safety_state"),
                report.get("min_time_to_critical_s"),
            )

    async def assessment_history(
        self,
        system_id: str,
        start: datetime,
        end: datetime,
        bucket_s: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """State-of-health history, optionally downsampled (min SoH per bucket)."""
        async with self._pool.acquire() as conn:
            if bucket_s and bucket_s > 0:
                rows = await conn.fetch(
                    """
                    SELECT time_bucket(make_interval(secs => $4), time) AS bucket,
                           avg(pack_soh)       AS pack_soh,
                           min(worst_cell_soh) AS worst_cell_soh
                    FROM assessment_summary
                    WHERE system_id = $1 AND time >= $2 AND time <= $3
                    GROUP BY bucket
                    ORDER BY bucket
                    """,
                    system_id,
                    start,
                    end,
                    bucket_s,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT time AS bucket, pack_soh, worst_cell_soh
                    FROM assessment_summary
                    WHERE system_id = $1 AND time >= $2 AND time <= $3
                    ORDER BY time
                    """,
                    system_id,
                    start,
                    end,
                )
        return [dict(r) for r in rows]

    # -- reads ------------------------------------------------------------
    async def latest_pack(self, system_id: str) -> Optional[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM pack_telemetry WHERE system_id = $1 "
                "ORDER BY time DESC LIMIT 1",
                system_id,
            )
        return dict(row) if row else None

    async def latest_cells(self, system_id: str) -> list[dict[str, Any]]:
        """Most recent row for each (series, parallel) cell position."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (series_index, parallel_index)
                       time, series_index, parallel_index,
                       voltage_v, current_a, temp_c, soc
                FROM cell_telemetry
                WHERE system_id = $1
                ORDER BY series_index, parallel_index, time DESC
                """,
                system_id,
            )
        return [dict(r) for r in rows]

    async def pack_history(
        self,
        system_id: str,
        start: datetime,
        end: datetime,
        bucket_s: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Pack-level history, optionally downsampled into ``bucket_s`` buckets.

        Downsampling with ``time_bucket`` keeps a wide time range cheap to plot --
        exactly what a dashboard needs and what raw SQL over Postgres cannot do
        as ergonomically. Aggregates: mean SoC/voltage, and *max* temperature and
        imbalance (you never want to average away a hot cell).
        """
        async with self._pool.acquire() as conn:
            if bucket_s and bucket_s > 0:
                rows = await conn.fetch(
                    """
                    SELECT time_bucket(make_interval(secs => $4), time) AS bucket,
                           avg(pack_voltage_v)      AS pack_voltage_v,
                           avg(pack_current_a)      AS pack_current_a,
                           avg(pack_power_w)        AS pack_power_w,
                           avg(pack_soc)            AS pack_soc,
                           max(max_temp_c)          AS max_temp_c,
                           max(voltage_imbalance_v) AS voltage_imbalance_v
                    FROM pack_telemetry
                    WHERE system_id = $1 AND time >= $2 AND time <= $3
                    GROUP BY bucket
                    ORDER BY bucket
                    """,
                    system_id,
                    start,
                    end,
                    bucket_s,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT time AS bucket, pack_voltage_v, pack_current_a,
                           pack_power_w, pack_soc, max_temp_c, voltage_imbalance_v
                    FROM pack_telemetry
                    WHERE system_id = $1 AND time >= $2 AND time <= $3
                    ORDER BY time
                    """,
                    system_id,
                    start,
                    end,
                )
        return [dict(r) for r in rows]


def _ts(value: Any) -> datetime:
    """An ISO string from the library into a timestamptz, defaulting to now."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str:
    return value.isoformat(timespec="seconds") if isinstance(value, datetime) else str(value)


async def _insert_note(conn, entry_id: str, note: dict[str, Any]) -> None:
    await conn.execute(
        "INSERT INTO library_notes (entry_id, text, kind, author, at) VALUES ($1,$2,$3,$4,$5)",
        entry_id,
        note.get("text", ""),
        note.get("kind", "note"),
        note.get("author", ""),
        _ts(note.get("at")),
    )


async def _insert_decision(conn, entry_id: str, decision: dict[str, Any]) -> None:
    await conn.execute(
        """
        INSERT INTO library_decisions
            (entry_id, question, choice, because, params, rejected, author, at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        """,
        entry_id,
        decision.get("question", ""),
        decision.get("choice", ""),
        decision.get("because", ""),
        list(decision.get("params") or []),
        list(decision.get("rejected") or []),
        decision.get("author", ""),
        _ts(decision.get("at")),
    )


def _system_row(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for key in ("config", "spec"):
        if isinstance(d.get(key), str):
            d[key] = json.loads(d[key])
    return d
