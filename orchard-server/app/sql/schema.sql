CREATE TABLE IF NOT EXISTS zone (
    zone_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    soil_drainage   TEXT               -- free text; canonicalized by the validation agent
);

CREATE TABLE IF NOT EXISTS tree (
    tree_id         INTEGER PRIMARY KEY,
    species         TEXT NOT NULL,     -- free text; canonicalized by the validation agent
    variety         TEXT NOT NULL,     -- free text; canonicalized by the validation agent
    zone_id         TEXT REFERENCES zone(zone_id),
    planted_date    TEXT,              -- ISO date; age derived on read, never stored
    additional_context TEXT,           -- free-text tier, RAG-sourced; NULL until resolved
    notes           TEXT
);
