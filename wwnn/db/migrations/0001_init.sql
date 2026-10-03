-- WWNN schema v1. Applied by wwnn/db/migrate.py (tracked in schema_migrations).

CREATE TABLE IF NOT EXISTS archive_items (
  id              INTEGER PRIMARY KEY,
  slug            TEXT UNIQUE NOT NULL,
  title           TEXT NOT NULL,
  summary         TEXT NOT NULL,            -- 3-6 sentences, facts only, English
  event_date      TEXT,                     -- ISO date or 'c. 1897' (also used for the VHS OSD)
  place           TEXT,
  source_citation TEXT NOT NULL,            -- newspaper, date, page
  source_url      TEXT,
  rights_note     TEXT,
  tags            TEXT,                     -- JSON array
  absurdity       INTEGER CHECK (absurdity BETWEEN 0 AND 10),
  verified_by     TEXT NOT NULL,
  verified_at     TEXT NOT NULL,
  is_sample       INTEGER NOT NULL DEFAULT 0,  -- 1 = shipped sample data, replace before going live
  times_used      INTEGER NOT NULL DEFAULT 0,
  last_used_at    TEXT,
  active          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS live_items (
  id            INTEGER PRIMARY KEY,
  source        TEXT NOT NULL,
  url           TEXT NOT NULL,
  url_hash      TEXT UNIQUE NOT NULL,
  title_hash    TEXT NOT NULL,
  title         TEXT NOT NULL,
  description   TEXT,
  language      TEXT,
  published_at  TEXT,
  fetched_at    TEXT NOT NULL,
  absurdity     INTEGER,
  safe          INTEGER,                    -- 1 = passed taboo filter, 0 = excluded
  safety_reason TEXT,
  status        TEXT NOT NULL DEFAULT 'candidate'
                CHECK (status IN ('candidate','proposed','selected','used','rejected','expired'))
);
CREATE INDEX IF NOT EXISTS idx_live_status ON live_items(status, safe, absurdity DESC);

CREATE TABLE IF NOT EXISTS weekly_runs (
  id                  INTEGER PRIMARY KEY,
  iso_week            TEXT NOT NULL,
  state               TEXT NOT NULL,
  failed_stage        TEXT,
  error               TEXT,
  dry_run             INTEGER NOT NULL DEFAULT 0,
  script_version      INTEGER NOT NULL DEFAULT 0,
  pacing_rounds       INTEGER NOT NULL DEFAULT 0,
  context             TEXT NOT NULL DEFAULT '{}',   -- JSON scratch (wpm calibration, feedback)
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  selection_deadline  TEXT,
  reminded_at         TEXT,
  telegram_message_id INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_week ON weekly_runs(iso_week)
  WHERE state NOT IN ('CANCELLED','SKIPPED','FAILED');

CREATE TABLE IF NOT EXISTS run_proposals (
  run_id      INTEGER NOT NULL REFERENCES weekly_runs(id),
  slot        TEXT NOT NULL,                 -- 'N1'..'N5', 'A1'..'A3'
  kind        TEXT NOT NULL CHECK (kind IN ('live','archive')),
  live_id     INTEGER REFERENCES live_items(id),
  archive_id  INTEGER REFERENCES archive_items(id),
  PRIMARY KEY (run_id, slot)
);

CREATE TABLE IF NOT EXISTS selections (
  run_id      INTEGER NOT NULL,
  slot        TEXT NOT NULL,
  rank        INTEGER NOT NULL,              -- toggle order = priority
  selected_at TEXT NOT NULL,
  PRIMARY KEY (run_id, slot),
  FOREIGN KEY (run_id, slot) REFERENCES run_proposals(run_id, slot)
);

CREATE TABLE IF NOT EXISTS scripts (
  id           INTEGER PRIMARY KEY,
  run_id       INTEGER NOT NULL REFERENCES weekly_runs(id),
  version      INTEGER NOT NULL,
  model        TEXT NOT NULL,
  prompt_hash  TEXT NOT NULL,
  json         TEXT NOT NULL,
  est_seconds  REAL,
  real_seconds REAL,
  lint_warnings TEXT,
  approved     INTEGER NOT NULL DEFAULT 0,
  approved_at  TEXT,
  UNIQUE (run_id, version)
);

CREATE TABLE IF NOT EXISTS stage_checkpoints (
  run_id       INTEGER NOT NULL REFERENCES weekly_runs(id),
  stage        TEXT NOT NULL,
  inputs_hash  TEXT NOT NULL,
  outputs      TEXT NOT NULL,                -- JSON manifest of produced files
  finished_at  TEXT NOT NULL,
  seconds      REAL,
  PRIMARY KEY (run_id, stage)
);

CREATE TABLE IF NOT EXISTS shots (
  id             INTEGER PRIMARY KEY,
  run_id         INTEGER NOT NULL REFERENCES weekly_runs(id),
  shot_key       TEXT NOT NULL,              -- e.g. 'tom_03'
  anchor         TEXT NOT NULL CHECK (anchor IN ('tom','annika')),
  audio_seconds  REAL NOT NULL,
  num_segments   INTEGER NOT NULL,
  input_sha256   TEXT NOT NULL,
  mp4_path       TEXT,
  render_seconds REAL,
  status         TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','done','failed')),
  error          TEXT,
  updated_at     TEXT NOT NULL,
  UNIQUE (run_id, shot_key)
);

CREATE TABLE IF NOT EXISTS episodes (
  id          INTEGER PRIMARY KEY,
  run_id      INTEGER NOT NULL REFERENCES weekly_runs(id),
  video       TEXT NOT NULL CHECK (video IN ('A','B')),
  path        TEXT NOT NULL,
  sha256      TEXT NOT NULL,
  duration_s  REAL NOT NULL,
  width       INTEGER, height INTEGER,
  title       TEXT, description TEXT, tags TEXT,
  created_at  TEXT NOT NULL,
  UNIQUE (run_id, video)
);

CREATE TABLE IF NOT EXISTS uploads (
  id               INTEGER PRIMARY KEY,
  episode_id       INTEGER NOT NULL REFERENCES episodes(id),
  youtube_id       TEXT UNIQUE,
  privacy_sent     TEXT NOT NULL CHECK (privacy_sent = 'private'),   -- DB-level guard
  privacy_verified TEXT CHECK (privacy_verified IS NULL OR privacy_verified = 'private'),
  uploaded_at      TEXT,
  status           TEXT NOT NULL CHECK (status IN ('pending','uploading','done','failed')),
  error            TEXT
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  run_id INTEGER,
  ts TEXT NOT NULL,
  level TEXT NOT NULL,
  stage TEXT,
  message TEXT NOT NULL
);
