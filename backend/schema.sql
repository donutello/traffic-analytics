-- Tables for the data contract (docs/contract.md): what the import (backend/load.py) writes
-- and the API (issues #5-#7) reads. Apply them with one idempotent command:
--
--     uv run python -m backend.db

-- How time is stored
--
-- Contract times arrive as ISO 8601 with an offset, in practice Moscow +03:00. The import
-- converts each one to Moscow time (fixed UTC+3, Russia has no DST) and stores it naive:
-- ts, starts_at and ends_at as text 'YYYY-MM-DD HH:MM:SS', event dates as 'YYYY-MM-DD'.
-- The offset is dropped on purpose: the wall-clock time in the columns IS the Moscow one,
-- so date(ts) and strftime('%Y-%W', ts) group the hours into Moscow calendar days and
-- weeks on every machine, whatever timezone that machine itself runs in. The conversion
-- happens only in backend/load.py; the database never stores UTC or an offset.

CREATE TABLE IF NOT EXISTS sensors (
    id                  TEXT PRIMARY KEY,  -- <road>-<something>, unique across all roads
    road                TEXT NOT NULL,     -- directory name under analysis/output/
    road_name           TEXT NOT NULL,
    name                TEXT NOT NULL,
    km                  REAL NOT NULL,
    lat                 REAL NOT NULL,
    lon                 REAL NOT NULL,
    direction_direct    TEXT NOT NULL,
    direction_reverse   TEXT NOT NULL
);

-- Outside events from events.json. The road column (and the one in anomalies) keeps the
-- ?road= filters of the API and the "reload replaces one road's data" of the import to
-- one plain WHERE road = ?.
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    road        TEXT NOT NULL,
    date        TEXT NOT NULL,  -- 'YYYY-MM-DD'
    category    TEXT NOT NULL CHECK (category IN
                ('accident', 'roadworks', 'weather', 'holiday', 'outage', 'other')),
    title       TEXT NOT NULL,
    description TEXT,
    source_url  TEXT NOT NULL
);

-- One row per series.csv line. PRIMARY KEY (sensor_id, ts) is the (sensor_id, ts) index
-- the API needs: /api/series reads one sensor's hours of a period and groups them by day
-- and week in key order, and the key is also the contract rule that a sensor cannot have
-- the same hour twice. WITHOUT ROWID keeps the table in that one key tree.
CREATE TABLE IF NOT EXISTS measurements (
    sensor_id         TEXT NOT NULL REFERENCES sensors(id) ON DELETE CASCADE,
    ts                TEXT NOT NULL,  -- start of the hour, Moscow time
    volume            INTEGER NOT NULL,
    volume_direct     INTEGER NOT NULL,
    volume_reverse    INTEGER NOT NULL,
    cars              INTEGER,
    small_trucks      INTEGER,
    medium_trucks     INTEGER,
    large_trucks      INTEGER,
    road_trains       INTEGER,
    buses             INTEGER,
    motorcycles       INTEGER,
    speed_direct      REAL,
    speed_reverse     REAL,
    load_direct       REAL,
    load_reverse      REAL,
    state             TEXT NOT NULL CHECK (state IN ('normal', 'anomaly', 'imputed')),
    imputation_method TEXT CHECK (imputation_method IN ('interpolation', 'profile')),
    PRIMARY KEY (sensor_id, ts)
) WITHOUT ROWID;

-- anomalies.json (source='ours') and corporate_anomalies.json (source='corporate') share
-- a table: the only difference between the two files is which one a row was read from.
CREATE TABLE IF NOT EXISTS anomalies (
    id            TEXT PRIMARY KEY,
    source        TEXT NOT NULL CHECK (source IN ('ours', 'corporate')),
    road          TEXT NOT NULL,
    sensor_id     TEXT NOT NULL REFERENCES sensors(id) ON DELETE CASCADE,
    starts_at     TEXT NOT NULL,  -- half-open interval [starts_at, ends_at), Moscow time
    ends_at       TEXT NOT NULL,
    category      TEXT NOT NULL CHECK (category IN ('traffic', 'technical')),
    type          TEXT NOT NULL,
    detector      TEXT NOT NULL,
    level         TEXT NOT NULL CHECK (level IN ('low', 'medium', 'high', 'critical')),
    metric        TEXT NOT NULL,
    actual        REAL,
    expected      REAL,
    deviation_pct REAL,
    score         REAL,
    is_mega       INTEGER NOT NULL CHECK (is_mega IN (0, 1)),
    event_id      TEXT REFERENCES events(id),
    description   TEXT
);

-- /api/anomalies sorts one sensor's interval overlaps, /api/comparison matches ours
-- against corporate per sensor, and /api/series marks the hours of a sensor that a
-- traffic anomaly covers: all of them walk one sensor's anomalies in starts_at order.
CREATE INDEX IF NOT EXISTS idx_anomalies_sensor_starts ON anomalies (sensor_id, starts_at);
