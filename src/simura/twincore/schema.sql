-- Simura twin-core schema (TimescaleDB / PostgreSQL).
-- Idempotent: safe to run on every startup.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Twin registry: one row per battery system the twin core knows about.
CREATE TABLE IF NOT EXISTS systems (
    system_id   TEXT PRIMARY KEY,
    name        TEXT,
    config      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Component 10: source ('realtime' external feed vs 'simulation' run by the twin
-- core), the SystemSpec for simulations, and the desired run state. Added via
-- ALTER so existing databases upgrade in place; external publishers keep
-- auto-registering as 'realtime' (the default).
ALTER TABLE systems ADD COLUMN IF NOT EXISTS source    TEXT NOT NULL DEFAULT 'realtime';
ALTER TABLE systems ADD COLUMN IF NOT EXISTS spec      JSONB;
ALTER TABLE systems ADD COLUMN IF NOT EXISTS run_state TEXT NOT NULL DEFAULT 'running';
-- Component 17: which library entry this system was started from, if any. It is
-- what lets a system that has been tuned while running be captured back as the
-- *next version* of the design it came from, rather than as another orphan spec
-- in the folder -- which is the loop the whole component exists to close.
ALTER TABLE systems ADD COLUMN IF NOT EXISTS library_entry_id TEXT;

-- Pack-level time series (one row per telemetry frame).
CREATE TABLE IF NOT EXISTS pack_telemetry (
    time                 TIMESTAMPTZ NOT NULL,
    system_id            TEXT NOT NULL,
    sim_time_s           DOUBLE PRECISION,
    pack_voltage_v       DOUBLE PRECISION,
    pack_current_a       DOUBLE PRECISION,
    pack_power_w         DOUBLE PRECISION,
    pack_soc             DOUBLE PRECISION,
    max_temp_c           DOUBLE PRECISION,
    min_cell_voltage_v   DOUBLE PRECISION,
    max_cell_voltage_v   DOUBLE PRECISION,
    voltage_imbalance_v  DOUBLE PRECISION
);
SELECT create_hypertable('pack_telemetry', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_pack_telemetry_system_time
    ON pack_telemetry (system_id, time DESC);

-- Cell-level time series (one row per cell per frame).
CREATE TABLE IF NOT EXISTS cell_telemetry (
    time            TIMESTAMPTZ NOT NULL,
    system_id       TEXT NOT NULL,
    series_index    INTEGER NOT NULL,
    parallel_index  INTEGER NOT NULL,
    voltage_v       DOUBLE PRECISION,
    current_a       DOUBLE PRECISION,
    temp_c          DOUBLE PRECISION,
    soc             DOUBLE PRECISION
);
SELECT create_hypertable('cell_telemetry', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_cell_telemetry_system_time
    ON cell_telemetry (system_id, time DESC);

-- Anomaly summary time series (pack-level; full per-cell report is kept live in
-- memory and served from the /anomaly endpoint).
CREATE TABLE IF NOT EXISTS anomaly_summary (
    time            TIMESTAMPTZ NOT NULL,
    system_id       TEXT NOT NULL,
    sim_time_s      DOUBLE PRECISION,
    max_score       DOUBLE PRECISION,
    flagged_count   INTEGER,
    worst_series    INTEGER,
    worst_parallel  INTEGER,
    worst_driver    TEXT
);
SELECT create_hypertable('anomaly_summary', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_anomaly_summary_system_time
    ON anomaly_summary (system_id, time DESC);

-- Assessment summary time series (SoH, diagnosis, safety; full per-cell health
-- report is kept live in memory and served from the /assessment endpoint).
CREATE TABLE IF NOT EXISTS assessment_summary (
    time                     TIMESTAMPTZ NOT NULL,
    system_id                TEXT NOT NULL,
    sim_time_s               DOUBLE PRECISION,
    pack_soh                 DOUBLE PRECISION,
    worst_cell_soh           DOUBLE PRECISION,
    fault_type               TEXT,
    confidence               DOUBLE PRECISION,
    safety_state             TEXT,
    min_time_to_critical_s   DOUBLE PRECISION
);
SELECT create_hypertable('assessment_summary', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_assessment_summary_system_time
    ON assessment_summary (system_id, time DESC);

-- ------------------------------------------------------------------------
-- Component 17: the system library -- memory that survives the project.
--
-- Plain relational tables, not hypertables: these are documents somebody wrote,
-- not a time series. The one thing worth noticing is what is *not* here -- no
-- column stores how an entry differs from its parent, because that is computed
-- from the two specs on read (simura.library.diff). A stored diff is a second
-- copy of the truth, and the second copy is the one that goes wrong.
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS library_entries (
    entry_id          TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    spec              JSONB NOT NULL,
    kind              TEXT NOT NULL DEFAULT 'system',   -- system | template
    version           INTEGER NOT NULL DEFAULT 1,
    parent_id         TEXT,            -- deliberately no FK: deleting a design
                                       -- must not delete somebody else's fork
    relation          TEXT NOT NULL DEFAULT 'origin',   -- origin|revision|fork|promotion
    source            TEXT NOT NULL DEFAULT 'builder',  -- builder|twin|import|bundled
    source_system_id  TEXT,
    author            TEXT NOT NULL DEFAULT '',
    summary           TEXT NOT NULL DEFAULT '',
    tags              TEXT[] NOT NULL DEFAULT '{}',
    validated         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_library_entries_parent ON library_entries (parent_id);
CREATE INDEX IF NOT EXISTS idx_library_entries_kind   ON library_entries (kind, created_at DESC);

-- Notes and decisions are appended over time, by people who are not the author
-- of the entry, so they are rows rather than columns on it: adding a note six
-- months later must not rewrite somebody's system.
CREATE TABLE IF NOT EXISTS library_notes (
    id         BIGSERIAL PRIMARY KEY,
    entry_id   TEXT NOT NULL REFERENCES library_entries(entry_id) ON DELETE CASCADE,
    text       TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'note',   -- note | gotcha | result
    author     TEXT NOT NULL DEFAULT '',
    at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_library_notes_entry ON library_notes (entry_id, at);

CREATE TABLE IF NOT EXISTS library_decisions (
    id         BIGSERIAL PRIMARY KEY,
    entry_id   TEXT NOT NULL REFERENCES library_entries(entry_id) ON DELETE CASCADE,
    question   TEXT NOT NULL,
    choice     TEXT NOT NULL DEFAULT '',
    because    TEXT NOT NULL,
    params     TEXT[] NOT NULL DEFAULT '{}',   -- the spec keys this reason covers
    rejected   TEXT[] NOT NULL DEFAULT '{}',
    author     TEXT NOT NULL DEFAULT '',
    at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_library_decisions_entry ON library_decisions (entry_id, at);
