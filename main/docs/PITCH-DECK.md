# Cadence — Pitch Deck (5 minutes, 8 slides)

> **When to use this:** You couldn't record a 5-minute video, or you're
> pasting the deck into the Buildathon application form's free-text fields
> in addition to the video. Each slide is a self-contained ~30-second beat
> that can be read aloud or pasted verbatim.
>
> **Submission target:** paste slide 1 (the hook) into the free-text
> summary field. Link the rest as `docs/PITCH-DECK.md` in the repo.

---

### Slide 1 — Hook (0:00–0:30)

> Indian subscription businesses lose 5 to 15 % of monthly recurring
> revenue to silent payment failures. Failed UPI AutoPay debits, expired
> card mandates, the NPCI "phantom failure" that gets queued at 8 AM
> peak and settles at 11 AM. Razorpay's webhook tells you something
> failed. It does not tell you *why*, *what to do*, or *who to call* in
> Hinglish at 7 PM.
>
> **Cadence is the closed-loop agent that does.** Deterministic spine,
> probabilistic edges, RBI-aware, tamper-evident. **+43.9 % more revenue
> recovered than naive dunning, with zero compliance violations.**

---

### Slide 2 — The problem (0:30–1:00)

Three failure modes drain recurring revenue in India:

1. **Real failures** (insufficient funds, expired card, customer
   cancellation). Razorpay knows they happened; it doesn't suggest
   what to do.
2. **Phantom failures** — NPCI's Aug 2025 peak-hour AutoPay hold queues
   debits and re-tries them later. Recovery logic that contacts the
   customer for a "failed" debit that NPCI is about to settle on its own
   is double-charge waiting to happen.
3. **Quiet hours** — Indian recovery tools spam customers at 2 AM,
   violating NPCI customer-protection rules and triggering RBI
   complaints.

---

### Slide 3 — The architecture (1:00–1:30)

```
Razorpay webhook
    → HMAC verify
    → hash-chained SQLite event log
    → real error-code classifier (known codes: 0 LLM tokens)
    → Policy Guardian veto (RBI + NPCI rules)
    → bounded LLM planner (only for unclassifiable codes)
    → executors (Payment Links, retries, WhatsApp/email channels)
    → durable timers
    → cloud mirror
```

**Rules own the money. AI only proposes. Every action is signed and
replayable from the event log.** Kill the process mid-journey and
restart — it resumes exactly where it stopped.

---

### Slide 4 — Live demo (1:30–2:30)

**What to show:** the SPA on `localhost:3000`, with the API on
`:8000` running. Open the **Testbench** tab, click "Inject Webhook" with
subscription_id `sub_demo_live`, customer_id `cust_judge_demo`, error
code `insufficient_funds`, amount ₹1,499. Then open the **Overview**
tab and the **Journeys** tab.

**The script (read aloud):**

> "I am injecting a real Razorpay-format webhook. Server signs the
> body with the configured secret, posts through the same gateway the
> live app uses, and ticks the worker once so the journey is classified
> before the response returns. Zero AI tokens — the deterministic
> classifier read the real error code. The Guardian approved a payday
> retry at 10 AM Monday, because that's when salary lands. No WhatsApp
> at 2 AM, no NPCI quiet-hours breach, no DND violation, no double-send.
>
> Every state change is hash-chained. Edit any old row, the chain
> breaks visibly. The Guardian's veto count for this journey is logged
> in the same ledger. You can replay the entire decision, event by
> event, from the moment the webhook landed to the moment the recovery
> is scheduled."

---

### Slide 5 — The numbers (2:30–3:15)

| Metric | Naive dunning | Cadence |
|---|---|---|
| Revenue recovered (₹, 500 sub batch) | ₹113,311 (37.8 %) | **₹166,228 (54.4 %)** |
| Uplift | — | **+43.9 %** (Indian avg 20–35 %) |
| Customer contacts per recovery | 8.22 | **0.64** |
| Compliance violations | — | **0** |
| LLM tokens spent on the batch | — | **0** |
| Guardian vetoes (out-of-policy actions blocked) | — | **228** |

Same seed → byte-identical report. Every number reproducible with
`python scripts/run_eval.py` on any clone.

---

### Slide 6 — Chaos drills (3:15–4:00)

Four disaster scenarios, every run, identical seed:

1. **Duplicate webhook replay** — first delivery accepted, four retries
   deduplicated by Razorpay event id. **PASS.**
2. **Process crash mid-journey** — kill -9 during a recovery, restart,
   journey resumes exactly where it stopped. **PASS.**
3. **AI provider dead** — every LLM endpoint unreachable, fast path
   recovers the batch anyway, zero spend rows. **PASS.**
4. **Illegal proposal veto** — the LLM proposes a 2 AM WhatsApp, the
   Guardian vetoes it under NPCI quiet hours. **PASS.**

Run with `python scripts/chaos_drills.py`. Four lines, every run.

---

### Slide 7 — Why this architecture (4:00–4:40)

> "Indian regulators and Razorpay's own Agent Studio principles say
> the same thing: every money action must be explainable, bounded, and
> gated. Cadence treats that as code, not as documentation.
>
> The repo is public. The architecture is documented. The MCP server
> composes with Claude Desktop, Cursor, and VS Code — 8 read-only
> tools let any AI agent inspect recovery state in real time, and
> nothing more. The cloud mirror is one Supabase project and three
> tables away. 284 tests. Four chaos drills. Zero keys needed to run
> it.
>
> If this is a wrapper, it's a wrapper that survived four chaos drills,
> the same seed twice, and the same Razorpay webhook format the
> production gateway uses. If this is a demo, it's a demo you can fork
> and run on a clean laptop in ninety seconds."

---

### Slide 8 — Close (4:40–5:00)

> "Thank you. The repo link is on screen. Open `docs/ARCHITECTURE.md`
> for the system diagram, `docs/eval-report.md` for the numbers,
> `docs/mcp-integration.md` for the AI-agent hooks, and `main/.env.example`
> for the keys you can paste. The single most important line in this
> submission is in the README: **zero keys needed to run it.** That
> line is the only honest confidence-builder that matters. Joel D'lima,
> Cadence."

---

### Quick-reference: the three winning lines

If a judge asks one question and you can only say three things, say these:

1. "**Zero AI tokens spent on the batch** — the deterministic fast path
   handled every standard decline code."
2. "**228 vetoes, zero of them mattered to the customer** — they were
   all things the rules say you cannot do."
3. "**Zero keys needed to run it** — `pip install -e ".[dev]"` and you
   have a 5-second demo."

---

### Quick-reference: the three lines that will sink you

If you say any of these, restart:

- "It's an AI agent that chats with customers."
- "The AI decides when to charge."
- "It sends WhatsApp reminders."

The replacement for each is in `docs/PITCH-VIDEO.md`, table of
"What NOT to say."
