-- Cadence schema v2: customer communication preferences (backlog item 9).
-- allowed_channels is a comma-separated ordered list ("whatsapp,email");
-- the preferred contact window uses IST hours in [0, 24), wrap-aware.

CREATE TABLE IF NOT EXISTS customer_preferences (
    customer_id           TEXT PRIMARY KEY,
    allowed_channels      TEXT NOT NULL DEFAULT 'whatsapp,email',
    preferred_window_start INTEGER NOT NULL DEFAULT 0,
    preferred_window_end   INTEGER NOT NULL DEFAULT 24,
    updated_at            TEXT
);
