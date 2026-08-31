CREATE TABLE IF NOT EXISTS zone (
    zone_id         INTEGER PRIMARY KEY,   -- auto-incrementing rowid alias
    name            TEXT NOT NULL,
    soil_drainage   TEXT,                  -- free text; canonicalized by the validation agent
    source          TEXT                   -- free text; provenance of the zone record (survey, grower notes, …)
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
