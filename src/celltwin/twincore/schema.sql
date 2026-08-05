-- CellTwin twin-core schema (TimescaleDB / PostgreSQL).
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
