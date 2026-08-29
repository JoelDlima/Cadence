# Cadence — in plain English

> A 5-minute read for anyone who wants to understand the project
> without reading code. No jargon. No diagrams. Just the story.

## The problem you're solving

You run a subscription business in India. Maybe streaming, maybe
ed-tech, maybe SaaS. Every month, **5 to 15 percent** of your customers
who *try* to pay you **don't end up paying you**.

It is not their fault. Their UPI app was offline. Their card hit a
daily limit. Their auto-pay mandate was paused by the bank. The money
*would* have been in your account, but the technical plumbing
between the customer's bank and your bank stumbled.

So the payment **fails silently**. Razorpay tells you it failed (a
webhook arrives in your dashboard). But if you don't *do* something
about it, that customer just… never pays. Their subscription sits in
limbo. You lose the ₹499. They lose the service. Everyone forgets
about it.

Indian businesses lose **billions of rupees** to this every year.

## The dumb way to fix it (and why it backfires)

The obvious fix: **just retry the payment**. A script that says "if
the payment failed, try it again tomorrow."

This works *partially* — it gets you maybe 30 to 40 percent of the
failed money back. But it also:

- Spams the customer (the regulator does **not** like this)
- Sends messages at 2 a.m. (RBI does **not** like this either)
- Treats every customer the same (the card-failed customer gets a
  UPI nudge that doesn't help them)
- Never explains *why* a payment failed, so the retry is sometimes
  bound to fail the exact same way

The Indian recovery-tool industry average is **20 to 35 percent**
of failed money recovered. That's the dumb-retry ceiling.

## The smart fix (what Cadence does)

Cadence is a small Python program that watches every failed
payment and decides, per customer, what to do next. The decisions
are made by:

1. **A classifier** that reads Razorpay's error code (like
   `INSUFFICIENT_FUNDS` or `UPI_TIMED_OUT`) and figures out
   *why* it failed.
2. **A small AI** (we call it the Recovery Brain) that picks the
   best next action from a short legal menu — "send a WhatsApp
   nudge", "wait until payday", "send a payment link", "give up
   on this customer", etc. It picks based on the cause, the
   customer's history, the time of day, and the day of the month.
3. **A policy guardian** that double-checks every decision against
   RBI and NPCI rules. "No messages between 9 p.m. and 9 a.m." "No
   more than 3 messages in 14 days." "If the customer is on the
   DND list, don't message them at all." If the action breaks a
   rule, the Guardian vetoes it. **No exceptions.**
4. **An executor** that actually sends the message (via WhatsApp
   or email) or creates the payment link (via Razorpay).

Every step is logged in an **append-only ledger** where each entry
is cryptographically chained to the one before it. If anyone
changes a single row, the chain breaks visibly.

## What happened when we tested it

We ran the same 5,000 Indian subscribers, same failure mix, through
two systems:

- The "naive" system: just retry every 24 hours. **₹1.15M recovered.**
- Cadence: figure out why, pick the right action, follow the rules.
  **₹1.61M recovered.**

That's **37.8 percent more money** recovered, with **zero LLM
tokens** (the AI is just a math function with no language model in
the loop), and **zero compliance violations**.

## How the flow works, in plain English

A customer's auto-debit fails. Razorpay sends a webhook to
Cadence. Inside Cadence:

1. **Check the signature.** Razorpay signs every webhook with a
   shared secret. Cadence verifies the signature is real. (If
   someone is trying to fake a payment failure, this rejects them.)
2. **Figure out why.** The classifier reads the error code
   (`INSUFFICIENT_FUNDS` is a "wait until payday" situation.
   `BAD_REQUEST_ERROR` might be a card that needs to be replaced.
   `UPI_TIMED_OUT` is a "try again in an hour" situation.)
3. **Pick the right action.** The Recovery Brain looks at seven
   legal next steps and picks the best one for this specific
   customer at this specific time.
4. **Check the rules.** The Guardian says "yes, that's allowed"
   or "no, that breaks quiet hours" or "no, that customer is
   already on the DND list."
5. **Send it (or schedule it).** If it's a WhatsApp now, it gets
   sent. If it's a "wait until payday" reminder, it gets
   scheduled for Friday at 10 a.m. (right when the salary
   lands).
6. **Log everything.** Every step is written to the audit chain.
   If a regulator ever asks "why did this customer get this email
   on this date?", the answer is one SQL query away.

The **B2B version** does the same thing for invoices. A B2B
customer hasn't paid in 30 days → the chaser sends a friendly
reminder. 60 days → firmer reminder with a UPI deep-link. 90 days
→ escalation to the customer's boss. 120 days → legal notice. 180
days → write it off.

The **checkout version** does the same thing for abandoned
shopping carts. A customer started a payment but didn't finish. 30
minutes later, a gentle nudge. 24 hours later, a second nudge. 7
days later, a third nudge with a 5 percent discount.

The **mandate version** does the same thing for UPI auto-pay
mandates that keep failing. If 3 of them fail in a week, the
customer is told "your bank is having trouble, please try a
different one."

The **voice version** takes the Hinglish text and turns it into a
15-second voice note using Sarvam (an Indian AI company).

All five share the same engine, the same Guardian, the same audit
chain. The only thing that changes is the ladder.

## What's actually running

Right now, on a single laptop:

- **One Python process** that holds the entire engine. It opens
  one SQLite file for the queue, the event store, the
  projections, the audit chain, all in one.
- **One React app** (the SPA) that shows you the dashboard. Nine
  tabs: live counters, journeys & audit, policy guardian,
  simulation & chaos, payment portal, the recovery brain, and
  one tab per parallel state machine (checkout, B2B, mandate).
- **No cloud required.** The app runs on a fresh `git clone`
  with zero API keys. The keys just turn DEMO mode into LIVE
  mode.

The Supabase mirror is one-way only: SQLite → Supabase, for
dashboards and reporting. The local SQLite stays the source of
truth.

## How to demo it (for someone who has 5 minutes)

1. **Open the SPA at http://127.0.0.1:3000** — you'll see the
   command room. Live counters, ₹1.61M recovered, 0 violations.
2. **Go to the Testbench tab.** Type a fake payment ID, click
   "Inject Payment Failure". Watch the engine:
   - Classify the error
   - Pick an action (the bandit decides)
   - Get guardian approval
   - Enqueue a WhatsApp nudge
3. **Go to the Journeys & Audit tab.** Click the new row. You see
   the full timeline. Every event is hash-chained. The audit tab
   has a "Verify" button — click it, get `chain_ok: true` and the
   total event count.
4. **Go to the Recovery Brain tab.** See the deterministic bandit
   pick, the reason it picked, the feature importances. No LLM.
   No tokens. Just math.
5. **Go to the Cloud Mirror tab.** See "online". That's your
   real Razorpay key, real Resend key, real Supabase sync, all
   running.

## The headline (for a 1-sentence summary)

> Cadence is a small Python program that watches every failed
> Indian subscription payment, figures out *why* it failed, picks
> the *right* next action from a legal menu, and runs that action
> through a policy guardian that enforces RBI and NPCI rules. The
> result: **+37.8 percent more money recovered** than the
> industry-average blind-retry system, with **zero compliance
> violations** and **zero LLM tokens** spent.

That's the whole story.
