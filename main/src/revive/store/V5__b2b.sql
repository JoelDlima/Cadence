-- Phase B2B: B2B receivables chaser store.
--
-- Razorpay's invoice API has these statuses (per the Python SDK docs):
--   draft, issued, paid, cancelled, expired
-- We extend the model with an IN_DISPUTE state for the chaser ladder.
--
-- The b2b_invoices table is one row per invoice. chases_sent is a
-- monotonic counter; the chaser reads it + days_past_due to decide
-- the next action.

CREATE TABLE IF NOT EXISTS b2b_invoices (
    id                      TEXT PRIMARY KEY,
    invoice_number          TEXT,
    org_id                  TEXT NOT NULL,         -- the buyer org
    contact_id              TEXT,                  -- primary contact at the org
    contact_email           TEXT,
    contact_phone           TEXT,
    amount_minor            INTEGER NOT NULL,
    currency                TEXT NOT NULL DEFAULT 'INR',
    issued_at               TEXT NOT NULL,         -- ISO UTC
    due_date                TEXT NOT NULL,         -- ISO UTC
    paid_at                 TEXT,
    status                  TEXT NOT NULL DEFAULT 'issued',  -- issued, paid, cancelled, expired, in_dispute
    chases_sent             INTEGER NOT NULL DEFAULT 0,
    last_chase_at           TEXT,
    last_chase_action       TEXT,                  -- friendly, firmer, manager, written, writeoff
    escalated_to_manager    INTEGER NOT NULL DEFAULT 0,
    writeoff_at             TEXT,
    notes                   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_b2b_invoices_status ON b2b_invoices(status);
CREATE INDEX IF NOT EXISTS idx_b2b_invoices_due_date ON b2b_invoices(due_date);
CREATE INDEX IF NOT EXISTS idx_b2b_invoices_org ON b2b_invoices(org_id);

CREATE TABLE IF NOT EXISTS b2b_orgs (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    contact_email TEXT,
    contact_phone TEXT,
    notes       TEXT NOT NULL DEFAULT ''
);
