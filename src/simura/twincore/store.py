"""TimescaleStore: persistence for the twin, backed by TimescaleDB via asyncpg.

Kept deliberately thin and SQL-first -- the queries are the interesting part and
should be readable at a glance. TimescaleDB is just PostgreSQL, so the hypertable
DDL lives in ``schema.sql`` and everything else is plain parameterized SQL.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
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
                "created_at, updated_at FROM systems ORDER BY system_id"
            )
        return [_system_row(r) for r in rows]

    async def create_system(
        self,
        system_id: str,
        name: str | None,
        source: str,
        spec: dict | None,
        run_state: str,
    ) -> None:
        """Register a system with its source/spec/run_state (create or replace).

        Used by ``POST /api/systems``. Unlike :meth:`upsert_system` (the ingest
        path, which only touches name/config), this owns the lifecycle columns.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO systems (system_id, name, source, spec, run_state, updated_at)
                VALUES ($1, $2, $3, $4, $5, now())
                ON CONFLICT (system_id) DO UPDATE
                    SET name = COALESCE(EXCLUDED.name, systems.name),
                        source = EXCLUDED.source,
                        spec = EXCLUDED.spec,
                        run_state = EXCLUDED.run_state,
                        updated_at = now()
                """,
                system_id,
                name,
                source,
                json.dumps(spec) if spec is not None else None,
                run_state,
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


def _system_row(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for key in ("config", "spec"):
        if isinstance(d.get(key), str):
            d[key] = json.loads(d[key])
    return d
