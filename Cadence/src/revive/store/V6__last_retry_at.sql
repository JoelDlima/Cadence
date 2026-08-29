-- Revive schema v6: UPI 18h cooling timer (PHASE 5).
-- Tracks the most recent successful mandate retry so the Guardian
-- can enforce the NPCI 18-hour cooling rule between retries on the
-- same VPA. Null means no retry has happened yet.

ALTER TABLE journeys ADD COLUMN last_retry_at TEXT;
