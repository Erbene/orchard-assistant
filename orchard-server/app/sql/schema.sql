CREATE TABLE IF NOT EXISTS zone (
    zone_id         INTEGER PRIMARY KEY,   -- auto-incrementing rowid alias
    name            TEXT NOT NULL,
    soil_drainage   TEXT,                  -- free text; canonicalized by the validation agent
    water_source    TEXT                   -- free text; irrigation water source for the zone (well, canal, municipal, …)
);

CREATE TABLE IF NOT EXISTS tree (
    tree_id         INTEGER PRIMARY KEY,
    species         TEXT NOT NULL,     -- free text; canonicalized by the validation agent
    variety         TEXT NOT NULL,     -- free text; canonicalized by the validation agent
    zone_id         INTEGER REFERENCES zone(zone_id),
    planted_date    TEXT,              -- ISO date; age derived on read, never stored
    additional_context TEXT,           -- free-text tier, RAG-sourced; NULL until resolved
    notes           TEXT
);

-- JIT scheduling model: no user_context table (dropped below for old DBs).
DROP TABLE IF EXISTS user_context;

CREATE TABLE IF NOT EXISTS task (
    id                  INTEGER PRIMARY KEY,
    tree_id             INTEGER NOT NULL
                            REFERENCES tree(tree_id) ON DELETE CASCADE,
    action_type         TEXT NOT NULL,                     -- free text, e.g. 'prune', 'fertilize'
    status              TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'completed', 'deferred')),
    priority_score      REAL NOT NULL DEFAULT 0.0,         -- higher = more urgent
    scheduled_date      TEXT,                              -- ISO 8601 datetime; NULL until scheduled
    frequency_days      INTEGER,                           -- NULL = one-off; N = repeats every N days
    estimated_minutes   INTEGER,                           -- LLM-estimated labor time for JIT fit
    required_resources  TEXT NOT NULL DEFAULT '[]',        -- JSON array of free-text resource names
    created_at          TEXT NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at        TEXT                               -- set when status -> 'completed'
);

CREATE INDEX IF NOT EXISTS idx_task_status_priority
    ON task (status, priority_score DESC);

-- Knowledge Base for the Consensus Fusion RAG pipeline -----------------------

CREATE TABLE IF NOT EXISTS sources (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    source_type  TEXT NOT NULL CHECK (source_type IN ('file', 'text')),
    file_path    TEXT,                                     -- set for source_type='file'
    raw_content  TEXT NOT NULL,                            -- extracted/plain text used for chunking
    upload_date  TEXT NOT NULL
                     DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS tree_sources (
    tree_id    INTEGER NOT NULL REFERENCES tree(tree_id) ON DELETE CASCADE,
    source_id  INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    PRIMARY KEY (tree_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_tree_sources_source ON tree_sources (source_id);
