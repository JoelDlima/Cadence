-- Phase checkout: checkout drop-off recovery store.
--
-- A checkout session is the customer-initiated but not-completed flow.
-- Razorpay's payment_link API creates a link; the webhook for the
-- completed link is `payment_link.paid`. The "abandon" path is
-- inferred: started a checkout, no payment_link.paid within a
-- window. The chaser is a soft reminder that respects the same
-- quiet-hours and touch-cap as the consumer recovery path.
--
-- All timestamps are ISO-8601 UTC strings (canonical via clock.utc_iso).

CREATE TABLE IF NOT EXISTS checkout_sessions (
    id                       TEXT PRIMARY KEY,
    customer_id              TEXT NOT NULL,
    subscription_id          TEXT,                 -- nullable: guest checkouts allowed
    amount_minor             INTEGER NOT NULL,
    currency                 TEXT NOT NULL DEFAULT 'INR',
    started_at               TEXT NOT NULL,        -- when the customer opened checkout
    abandoned_at             TEXT,                 -- first moment we noticed no pay
    last_nudge_at            TEXT,                 -- last nudge sent
    nudges_sent              INTEGER NOT NULL DEFAULT 0,
    status                   TEXT NOT NULL DEFAULT 'OPEN',  -- OPEN, ABANDONED, NUDGED, RECOVERED, EXPIRED
    payment_link_id          TEXT,                 -- Razorpay payment_link.id if created
    payment_link_short_url   TEXT,                 -- the share URL the customer sees
    recovered_at             TEXT,                 -- when the customer paid
    recovery_payment_id      TEXT,                 -- Razorpay payment.id on the recovered link
    notes                    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_checkout_sessions_status ON checkout_sessions(status);
CREATE INDEX IF NOT EXISTS idx_checkout_sessions_customer ON checkout_sessions(customer_id);
CREATE INDEX IF NOT EXISTS idx_checkout_sessions_abandoned ON checkout_sessions(abandoned_at);
