# Cadence — Complete UI Reference & Razorpay Impact Map

Autonomous AI Revenue Recovery for Indian Recurring Payments.

What each control on screen actually does, its operational role, and whether it modifies data on the live Razorpay Dashboard.

---

## 1. Live Recovery View (#/live)

### Step 1 - Create Real Customer
Calls Razorpay POST /v1/customers API with customer name, email, and phone contact.

> **Razorpay Dashboard:** Yes - A new customer appears immediately on Razorpay Dashboard > Customers.

### Step 2 - Create Link + Post Failure Webhook
Calls Razorpay POST /v1/payment_links to create a test link, then posts an HMAC-signed payment.failed event through Cadence webhook ingress to trigger the recovery engine.

> **Razorpay Dashboard:** Yes - A new Payment Link (plink_...) appears on Razorpay Dashboard > Payment Links with status 'Created'.

### Selected Journey Badge & Details
Shows the active journey ID, subscription ID, and real-time FSM state (e.g. INTERVENING, WAITING_OUTCOME, RECOVERED).

> **Razorpay Dashboard:** No - Internal Cadence finite state machine.

### Live Evidence Panel
Displays the verified Razorpay webhook ID, customer ID, payment link ID, and live hosted short URL.

> **Razorpay Dashboard:** No - Displays identifiers returned by Razorpay API.

### Hinglish Audio Player
Synthesizes the LLM recovery message into natural Indic Hinglish speech using Sarvam/ElevenLabs API, rendering an interactive waveform audio player.

> **Razorpay Dashboard:** No - Generated entirely on Cadence backend.

### Email Nudge Dispatcher
Sends the approved Hinglish recovery message with payment link to any entered email address via live Resend API.

> **Razorpay Dashboard:** No - Direct customer communication channel.

### Step 3 - Close Journey (Demo)
Submits an HMAC-signed payment_link.paid webhook to exercise Cadence's outcome handler, transitioning journey state to RECOVERED.

> **Razorpay Dashboard:** No - Razorpay status remains 'Created' until a real checkout occurs; Cadence never fakes upstream status.

### Smart Lifecycle Simulator
Simulates customer behavioral outcomes (Paid, Retry Failed, Expired) powered by LLM agent reasoning.

> **Razorpay Dashboard:** No - Evaluates downstream recovery paths within Cadence.

### Direct Razorpay Checkout Link
Clickable payment link URL directing the user to Razorpay's real hosted checkout page.

> **Razorpay Dashboard:** Yes - If payment is completed on the hosted checkout page, Razorpay changes status to 'Paid'.

## 2. Dashboard & Merchant Analytics (#/dashboard)

### Executive KPI Summary Cards
Displays aggregate metrics: Total Recovery Journeys, Total Recovered INR, Recovery Rate %, Value at Risk, and Avg Recovery Time.

> **Razorpay Dashboard:** No - Real-time projection from append-only SQLite event store.

### Payment Links & Recovery Table
Filterable ledger of all recovery journeys with customer details, classified root cause, recovery status, and risk badges.

> **Razorpay Dashboard:** No - Unified view combining Cadence state and Razorpay link data.

### Journey Drawer / Inspector
Slide-over panel showing complete lifecycle history, webhook delivery payloads, and agent execution timestamps.

> **Razorpay Dashboard:** No - In-depth diagnostic view.

### Cryptographic Audit Trail
Tamper-evident SHA-256 hash chain where each event embeds the preceding event's hash, proving zero ledger alteration.

> **Razorpay Dashboard:** No - Cadence cryptographic audit guarantee.

### AI Reasoning & Bandit Panel
Exposes the multi-agent decision chain: classifier taxonomy, contextual bandit arm selection, and LLM chain of thought.

> **Razorpay Dashboard:** No - Full transparency into autonomous recovery decisions.

### Calibrated Recovery Evidence
Multi-seed benchmark graph demonstrating Cadence (+25.8% lift) vs fixed retry baseline across 5 deterministic seeds.

> **Razorpay Dashboard:** No - Rigorous reproducible evaluation harness.

### Checkout Idle Recovery Scanner
Scans for payment links that remained idle beyond threshold and initiates drop-off recovery.

> **Razorpay Dashboard:** No - Proactive abandoned session scanner.

### Anomaly Alert Banner
Displays real-time warnings (e.g. WARN/ALERT) when failure rates spike across multiple subscriptions.

> **Razorpay Dashboard:** No - Operational health guardrail.

## 3. Mandate Retry Sequencer (#/mandate)

### Bank Degradation Matrix
Monitors real-time success rates across top-10 issuer banks (HDFC, SBI, ICICI, etc.) to identify widespread outages.

> **Razorpay Dashboard:** No - Intelligent bank routing intelligence.

### NPCI Window Retry Calendar
Calculates optimal debit re-attempt times aligning with NPCI clearing windows and salary credit cycles.

> **Razorpay Dashboard:** No - Replaces indiscriminate blind retries.

### Guardian 4-Attempt Lifetime Cap
Strict safety policy enforcing maximum 3 retries (4 attempts total) before permanent veto to protect merchant mandate validity.

> **Razorpay Dashboard:** No - Prevents mandate cancellation and customer churn.

## 4. Pre-Debit Preventive Notice (#/predebit)

### 24-Hour Pre-Debit Scheduler
Schedules proactive pre-debit notices 24-48 hours before execution in full compliance with RBI/NPCI recurring mandate rules.

> **Razorpay Dashboard:** No - Preventive compliance workflow.

### Multi-Channel Reminder Router
Dispatches preventive notifications across WhatsApp, SMS, or Email based on customer responsiveness.

> **Razorpay Dashboard:** No - Customer engagement layer.

### Guardian Suppression Checks
Automatically suppresses pre-debit notices for opted-out users, quiet hours, or active customer disputes.

> **Razorpay Dashboard:** No - Policy enforcement.

## 5. Checkout Drop-Off Recovery (#/checkout)

### Abandoned Checkout Detector
Monitors created payment links and flags sessions that stalled before completing checkout.

> **Razorpay Dashboard:** No - Session state tracker.

### High-Intent Recovery Nudge
Dispatches a single personalized nudge offering alternative payment methods (UPI, Card, Netbanking) before link expiry.

> **Razorpay Dashboard:** No - Revenue rescue workflow.

### Drop-Off Conversion Analytics
Measures recovered revenue and drop-off salvage rates across customer cohorts.

> **Razorpay Dashboard:** No - Performance reporting.

## 6. B2B Receivables & Invoicing (#/b2b)

### B2B Invoice Ledger
Tracks high-ticket enterprise subscriptions, corporate billing cycles, and invoice aging buckets.

> **Razorpay Dashboard:** No - Enterprise account management.

### Tiered Escalation Workflows
Progresses from soft reminders to finance team alerts as payment grace periods elapse.

> **Razorpay Dashboard:** No - Automated account chasing.

### Dynamic B2B Payment Links
Generates custom Razorpay links supporting enterprise GST invoicing and partial payments.

> **Razorpay Dashboard:** Yes - Creates corresponding Payment Links on Razorpay.

## 7. Customer Self-Service Pay Portal (#/pay)

### Branded Recovery Portal (/pay/:id)
Customer-facing mobile responsive landing page for self-service payment recovery.

> **Razorpay Dashboard:** No - Hosted by Cadence.

### Alternative Payment Rail Switcher
Allows the subscriber to switch from a failing UPI AutoPay account to Cards, Netbanking, or another UPI app.

> **Razorpay Dashboard:** Yes - Initializes Razorpay Checkout with the new payment instrument.

### Promise-to-Pay Date Selector
Allows the customer to pick a future date when funds will be available, immediately pausing automated retries.

> **Razorpay Dashboard:** No - Records customer commitment in Cadence PTP engine.

## 8. Test Lab Reliability Drills (#/testlab)

### Drill 1 - Schedule Preventive Notice
Schedules a mock pre-debit notification to verify Guardian suppression rules and audit trail logging.

> **Razorpay Dashboard:** No - Tests preventive scheduling without touching Razorpay.

### Drill 2 - Simulate Customer Reply (PTP)
Feeds Hinglish text commitments (e.g. 'kal pay karunga') into the NLP date parser to test automatic retry postponement.

> **Razorpay Dashboard:** No - Tests promise-to-pay parsing logic.

### Drill 3 - Send the Same Webhook Twice
Fires duplicate webhook payloads to prove idempotency: accepted on first arrival, rejected as replay on second.

> **Razorpay Dashboard:** No - Proves replay-attack and duplicate delivery protection.

### Drill 4 - Three Failures at Once (Burst)
Simultaneously fires 3 failure events to trip the Anomaly Detector into WARN status and log an operator recommendation.

> **Razorpay Dashboard:** No - Proves batch revenue-risk detection.

### Drill 5 - Send Webhooks Out of Order
Replays an older event after a newer state to prove late arrivals cannot corrupt the journey state machine.

> **Razorpay Dashboard:** No - Validates causal event ordering.

### Drill 6 - Pull the Kill Switch
Flips the emergency global circuit breaker; proves Guardian blocks all outbound actions and records vetoes in the audit trail.

> **Razorpay Dashboard:** No - Internal safety circuit breaker.

### Drill 7 - The 24-Hour Window Closes (Expiry)
Executes a real Razorpay API call POST /v1/payment_links/{id}/cancel to cancel the active link, then closes the journey unrecovered.

> **Razorpay Dashboard:** Yes - Payment Link status immediately changes to 'Cancelled' on the real Razorpay Dashboard.

## 9. Global Shell & System Controls

### Mode Badge (LIVE / SIMULATED)
Indicates whether real Razorpay, Resend, ElevenLabs, and Supabase credentials are authenticated.

> **Razorpay Dashboard:** No - Environment indicator.

### Supabase Cloud Sync Status
Shows background sync state (ONLINE / OFFLINE) and last sync timestamp for cloud ledger mirroring.

> **Razorpay Dashboard:** No - Cloud sync telemetry.

### Port 8000 API Health Indicator
Monitors FastAPI backend responsiveness and SQLite event database connectivity.

> **Razorpay Dashboard:** No - System health check.

### Emergency Kill Switch Banner
Prominent red banner displayed across all views when the global kill switch is active.

> **Razorpay Dashboard:** No - High-visibility safety indicator.

