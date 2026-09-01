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

-- Phase 1: Task State Foundation --------------------------------------------

CREATE TABLE IF NOT EXISTS task (
    id              INTEGER PRIMARY KEY,                       -- auto-incrementing
    tree_id         INTEGER NOT NULL
                        REFERENCES tree(tree_id) ON DELETE CASCADE,
    action_type     TEXT NOT NULL,                             -- free text, e.g. 'prune', 'fertilize'
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'completed', 'deferred')),
    priority_score  REAL NOT NULL DEFAULT 0.0,                 -- higher = more urgent
    scheduled_date  TEXT,                                      -- ISO 8601 datetime; NULL until scheduled
    frequency_days  INTEGER,                                   -- NULL = one-off; N = repeats every N days
    created_at      TEXT NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at    TEXT                                       -- set when status -> 'completed'
);

CREATE INDEX IF NOT EXISTS idx_task_status_priority
    ON task (status, priority_score DESC);

-- Singleton scheduling constraints for the Foreman agent.
CREATE TABLE IF NOT EXISTS user_context (
    id                            INTEGER PRIMARY KEY CHECK (id = 1),
    available_labor_hours_per_day REAL NOT NULL DEFAULT 8.0,
    available_products            TEXT NOT NULL DEFAULT '[]',  -- JSON array of strings
    updated_at                    TEXT NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
