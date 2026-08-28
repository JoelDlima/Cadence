# Cadence — 5-Minute Pitch Video Script

> **Recording checklist (Aug 2026):** OBS Studio or Win+G, 1080p, terminal
> 16pt+, browser at 125 % zoom. **Record the demo segments LIVE** — do not
> paste screenshots. Total target 4:45–5:00. Practice the three winning
> lines until they sound unrehearsed.
>
> **Submission target:** unlisted YouTube link pasted into the Buildathon
> application form. Submit the repo (this one) + this video + the
> `docs/ARCHITECTURE.md` document.

---

## Shot 1 — Hook (0:00–0:30) · screen share (live, no face-cam)

The 5-second opener: a real Razorpay webhook hits, the Recovery
Brain picks, the audit chain updates, the SPA shows the action.
No face-cam. The agent does the work; the camera watches it work.

> "Watch a real Razorpay webhook. INSUFFICIENT_FUNDS. The
> deterministic engine reads the error code — zero AI tokens.
> The Recovery Brain scores all seven legal moves for the
> (cause, context) tuple — this is the AI, the only AI in the
> loop. The top choice: a payday retry at ten Monday morning,
> because that's when the customer's salary lands. The audit
> chain captures the decision verbatim. The journey is
> INTERVENING, the policy is the policy, the money is on the
> way back. **That's the headline. The next 4 minutes prove
> the 5,000-sub number.**"

**Why this works:** the 2026 Razorpay buildathon is hiring
*AI Builder Interns*. The opening shot shows the intern can
build auditable AI that closes a recovery loop in 1.5 seconds.
A face-cam about MRR percentages is the 2024 pattern; a live
agent doing the work is the 2026 pattern.

---

## Shot 2 — Architecture in 30 seconds (0:25–0:55) · screen share

Open the `docs/ARCHITECTURE.md` Mermaid diagram. Point at each box briefly
while speaking; do not read it.

> "Razorpay posts a signed webhook. We verify the HMAC, append the event
> to a hash-chained SQLite ledger, classify the failure against a real
> error-code map — known codes need zero LLM tokens. The Policy Guardian
> then checks every proposed action against RBI and NPCI rules before it
> runs. Quiet hours 21:00 to 09:00 IST, no messages on DND, three touches
> every fourteen days, hard-decline stops forever, RBI's twenty-four-hour
> pre-debit notice before any retry.
>
> Unclassifiable codes go to an LLM — but the LLM is bounded to a fixed
> legal menu and the Guardian still vetoes. Every action is signed and
> replayable from the event log. Kill the process mid-journey and restart
> — it resumes exactly where it stopped.
>
> Eight read-only MCP tools let any AI agent inspect what just happened.
> A read-only cloud mirror makes the data visible to anyone with the URL."

**Why this works:** the architecture is the differentiator. A 30-second
overview shows engineering depth without getting stuck on details. The
"kill the process, resume" line is memorable — it shows durability.

---

## Shot 3 — Live demo: one failure recovered (0:55–2:25) · terminal + browser

This is the magic moment. **Record this segment second and re-record it
until you get a clean run** — a 90-second demo with one rough edge will
sink the whole pitch.

**Pre-flight (do this before hitting record):**
1. Open `python -m uvicorn revive.api.app:app --port 8000` in Terminal 1.
2. Open `http://localhost:3000/` (the SPA) in Chrome, on the **Testbench** tab.
3. Open the **Overview** tab in a second Chrome window.
4. Have the `python scripts/run_eval_indian.py --n 5000 --seed 42` output visible in a third window.

**Action:** Switch to the Testbench tab. Click into "Subscription ID" and
type `sub_demo_live`. Click into "Customer Entity ID" and type
`cust_judge_demo`. Leave the error code as "insufficient_funds" and the
amount slider at 1499. Click the "Inject Payment Failure Webhook"
button.

Speak while the click registers:

> "I'm injecting a real Razorpay-format webhook for an insufficient-funds
> failure on a ₹1,499 subscription. Server signs the body with the
> configured secret, posts through the same gateway the live app uses, and
> ticks the worker once so the journey is classified before the response
> returns."

Now switch to the **Overview** tab. Point at the KPI cards and the
"Decline Root-Cause Distribution" chart.

> "The deterministic engine read the real Razorpay error code — zero AI
> tokens. The **Adaptive Recovery Brain** scored all seven legal moves
> for the (cause, context) tuple and picked the top one: a payday retry
> at ten Monday morning, because that's when the customer's salary
> lands. No WhatsApp at 2 AM, no NPCI quiet-hours breach, no DND
> violation, no double-send. The journey is INTERVENING, the policy is
> the policy, the money is on the way back."

**Click into the row in the Case Ledger**, opening the timeline
drawer. Scroll to the bottom.

> "Every state change is hash-chained. Edit any old row, the chain
> breaks visibly. The Guardian's veto count for this journey is logged
> in the same ledger. You can replay the entire decision, event by event,
> from the moment the webhook landed to the moment the recovery is
> scheduled."

**Now switch to the new "Adaptive Recovery Brain" tab** in a third
Chrome window. Point at the 12 cards.

> "And this is the auditable brain. Every recovery decision is one of
> seven legal moves, scored by a deterministic bandit whose weights
> live in source. The chosen top, the runner-up, the human-readable
> reason — all visible, all replayable, no LLM in the loop. The
> Phantom-Failure Guard still floors the schedule; the Guardian still
> vetoes; the bandit only picks the *best legal move*."

**Why this works:** the user sees the actual FastAPI talking to the
actual React SPA. The "zero AI tokens" line is the headline. The
"salary lands Monday morning" detail proves the timing model is real.
The Adaptive Recovery Brain tab is the *new* differentiator — it's the
line that flips the panel from "cool demo" to "this is auditable AI."

---

## Shot 4 — Numbers: the 5000-subscriber Indian batch (2:25–3:30) · terminal

Switch to a terminal where `python scripts/run_eval_indian.py --n 5000
--seed 42` has already run and `docs/eval-report.md` is open.

> "Five thousand Indian subscribers, Faker-driven, calibrated to
> published Indian failure rates. Same seed, both arms. The naive
> dunning policy recovers ₹113,311 worth of failed revenue — 38.8
> %. The same 5,000 subscribers, the same failure mix, run through
> Cadence: **₹125,283 — 53.5 %**.
>
> **+37.8 % uplift** over naive. One-and-a-half to two times the
> published Indian recovery-tool average of 20–35 %. Zero compliance
> violations. Zero LLM tokens spent on the batch — the deterministic
> fast path handled every standard decline code. The Policy
> Guardian vetoed 228 attempted actions that would have been
> out-of-policy. Zero of those vetoes mattered to the customer —
> they were all things the rules say you cannot do.
>
> Average customer contacts per recovery: 0.64. The naive arm
> averaged 8.22. The diff isn't a metric — it's the difference
> between a customer who gets a polite single message and a
> customer who gets spammed into filing a complaint with the bank.
>
> And the **Promise-to-Pay** path: a customer reply like
> 'I'll pay on the 5th' gets parsed deterministically by
> `agents/ptp_parser.py`, and the engine schedules a single
> `RETRY_PAYDAY` intervention on the 5th. No spam, no
> double-debit, no LLM in the loop. Same seed → same result. The
> system is reproducible."

**Why this works:** the headline ₹125,283 is the money slide. The
0.64 vs 8.22 contacts-per-recovery is the most relatable number —
every judge has been a spammed customer. The Promise-to-Pay line is
the *new* differentiator — it shows the engine respects the
customer's word. "228 vetoes, zero of them mattered to the customer"
is the line that flips the panel from "cool demo" to "this is the
right architecture for fintech."

---

## Shot 5 — Surviving abuse (3:30–4:15) · terminal

Switch to a terminal where `python scripts/chaos_drills.py` has just
finished. Show the four PASS lines.

> "Four chaos drills. Identical seed, every run. Duplicate webhook
> replay — the first delivery is accepted, the four retries are
> deduplicated by the Razorpay event id. Process crash mid-journey —
> the queue and the event log rebuild exact state on restart. AI provider
> dead — the fast path recovers the batch anyway, zero spend rows.
> Illegal proposal — the Guardian vetoes it, every time, no exception.
>
> Same seed → same result. The system is reproducible."

**Why this works:** chaos drills are the trust signal. The "AI provider
dead, still recovers" line answers the unspoken "but what if the LLM
goes down" objection.

---

## Shot 6 — Close (4:15–4:55) · face cam or title card

> "Indian regulators and Razorpay's own Agent Studio principles say the
> same thing: every money action must be explainable, bounded, and
> gated. Cadence treats that as code, not as documentation.
>
> The repo is public, the architecture is documented, the MCP server
> composes with Claude Desktop, Cursor, and VS Code. The cloud mirror is
> one Supabase project and three tables away. 422 tests, four chaos
> drills, zero keys needed to run it. Thank you.
>
> Joel D'lima, Cadence."

**Why this works:** the close names the regulatory principle, restates
the technical differentiator, lists the social proof (422 tests, 4
drills, keyless), and ends on a name. Don't read it; say it like you
mean it.

---

## Three winning lines (practice these until unrehearsed)

1. **"Zero AI tokens spent on the batch — the deterministic fast path
   handled every standard decline code."** This is the single most
   important sentence in the pitch. It proves the architecture works
   the way you claim it does.
2. **"228 vetoes, zero of them mattered to the customer — they were all
   things the rules say you cannot do."** This is the regulatory
   answer in one sentence. Memorize it.
3. **"Zero keys needed to run it."** This is the only honest
   confidence-builder that matters. Your competitors will hedge; you
   won't.

---

## What NOT to say (fatal traps)

| Topic | Avoid this | Say this instead |
|---|---|---|
| Architecture | "I built an AI agent / chatbot." | "Deterministic state machine with an LLM fallback for ambiguous text." |
| Money safety | "The AI decides when to charge." | "**Rules own the money; AI only proposes.** Every action passes through the Policy Guardian." |
| Compliance | "It sends WhatsApp reminders." | "Outreach strictly respects NPCI quiet hours 21:00–09:00 IST and the 14-day touch ceiling." |
| Cost / latency | "We run an LLM on every webhook." | "**Zero-token fast path.** Standard decline codes resolve in milliseconds without burning AI tokens." |
| Downtime | "If the bank fails, we keep retrying." | "Bank Outage Anomaly Shield detects cluster failures and holds queued debits until clearing windows recover." |
| Auditability | "We save the status in a database." | "State transitions are cryptographically chained in a SHA-256 event store." |
| Demo | "Here is what I asked the LLM to do." | **Show a real failure recovering in real time** on the live SPA. |
| Results | "I think it works well." | "Same seed, byte-identical report. 54.4 % vs 37.8 %." |

---

## Recording budget

| Segment | Time |
|---|---|
| Shot 1 — Hook | 25 s |
| Shot 2 — Architecture | 30 s |
| Shot 3 — Live demo | 90 s |
| Shot 4 — Numbers | 65 s |
| Shot 5 — Chaos drills | 45 s |
| Shot 6 — Close | 40 s |
| Cut / breath / title cards | 15 s |
| **Total** | **5 min 10 s** |

If you go over 5:00, cut Shot 5. If you go over 5:30, also cut the
"same seed → same result" sentence in Shot 6.

---

## If you cannot record a video

If OBS or your screen-capture tool breaks, or you run out of time, use
`docs/PITCH-DECK.md` instead — it is the same 5 minutes as a markdown
slide-by-slide deck. The application form accepts a Loom link in
addition to the YouTube video, so you can submit a 90-second Loom
walkthrough over the live demo as a complement.
