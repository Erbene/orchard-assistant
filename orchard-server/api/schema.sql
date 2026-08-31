CREATE TABLE IF NOT EXISTS zone (
    zone_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    soil_drainage   TEXT               -- 'sandy_fast_draining' | 'loamy' | NULL (unknown)
);

CREATE TABLE IF NOT EXISTS tree (
    tree_id         INTEGER PRIMARY KEY,
    species         TEXT NOT NULL,     -- 'mango' | 'sapodilla' | 'sugar_apple'
    variety         TEXT NOT NULL,
    zone_id         TEXT REFERENCES zone(zone_id),
    planted_date    TEXT,              -- ISO date; age derived, not stored redundantly
    additional_context TEXT,           -- free-text tier, RAG-sourced; NULL until resolved
    notes           TEXT
);
