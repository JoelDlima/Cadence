-- Phase 9d: RBI / NPCI circular ingestion store.
--
-- Each row is one ingested regulatory document. The text is the OCR /
-- pdfplumber-extracted plain text; the summary is a deterministic 1-sentence
-- extract; the rules JSON is a list of {section, paragraph, requires} dicts
-- pulled from the heuristic extractor in revive.policy.circulars.
--
-- The table is small (one row per circular) and the lookup is path-based, so
-- no special indexes are needed for the demo.
CREATE TABLE IF NOT EXISTS policy_circulars (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,                -- 'RBI' or 'NPCI' or 'other'
    title         TEXT NOT NULL,
    issued_on     TEXT,                          -- ISO date if found in the doc
    reference     TEXT,                          -- e.g. 'RBI/2021-22/123' if found
    path          TEXT NOT NULL UNIQUE,         -- absolute path to the source PDF
    text          TEXT NOT NULL,                 -- full plain text
    summary       TEXT NOT NULL,                 -- 1-sentence extract
    rules_json    TEXT NOT NULL DEFAULT '[]',    -- JSON list of rule dicts
    ingested_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
