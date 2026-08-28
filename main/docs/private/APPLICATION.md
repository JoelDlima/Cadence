# Cadence — Application Form Cheat-Sheet

**Form URL:** https://forms.gle/d9r2gvxp8cmoZhon9

This document is the pre-written answer key for every field on the
Razorpay AI Buildathon 2026 application form. Copy each block into the
matching field. Fields marked `(paste this)` go into the free-text area;
fields marked `(link)` go into a URL field; checkboxes/multi-select are
listed with the values to pick.

---

## Page 1 — Identity

| Field | Value |
|---|---|
| Email | (your email) |
| Full Name | Joel D'lima |
| College Name | (your college) |
| Graduation Year | 2027 / 2028 / 2029 (whichever applies) |
| In-person availability from September | Yes — I will be available in Bangalore from September 2026 for the internship. |

---

## Page 2 — Track + project

| Field | Value |
|---|---|
| Track | **Track 3 — AI Revenue Recovery** |
| Project name | **Cadence** |
| One-line description (paste this) | **Autonomous revenue-recovery system for Indian Razorpay subscriptions; recovers +43.9 % more than naive dunning with zero compliance violations and zero LLM tokens on standard decline codes.** |
| Public GitHub repo URL (link) | https://github.com/JoelDlima/Revive |
| Architecture document (link) | https://github.com/JoelDlima/Revive/blob/main/main/docs/ARCHITECTURE.md |
| Pitch video (link) | (record and paste your unlisted YouTube URL; the script is at `docs/PITCH-VIDEO.md`, the deck fallback is `docs/PITCH-DECK.md`, the hero GIF instructions are at `docs/PITCH-GIF.md`) |

---

## Page 3 — Long-form answer: "What did you build and why?"

**(paste this entire block into the long-form answer field)**

> Indian subscription businesses lose 5–15 % of recurring revenue every
> month to silent payment failures. Razorpay's webhook tells merchants
> something failed; it does not tell them *why*, *what to do*, or
> *who to call* in Hinglish at 7 PM.
>
> **Cadence** is the closed-loop agent that does. It detects a failed
> UPI AutoPay or card e-mandate, classifies the root cause against a
> real Razorpay error-code table, and proposes a recovery action. The
> Policy Guardian — pure Python, not an LLM — vets every proposed
> action against RBI and NPCI rules before it runs: ≤3 touches every 14
> days, NPCI quiet hours 21:00–09:00 IST, DND honoured, hard-decline
> stops forever, RBI's 24h pre-debit notice before any retry. The LLM
> is only consulted for unclassifiable codes, can only name a legal
> cause and a legal intervention, and is itself re-vetoed by the same
> Guardian.
>
> **The 5-minute pitch video** walks through a live failure recovery,
> the hash-chained audit ledger, the 4 chaos drills, and the
> reproducible 500-subscriber batch (₹166,228 vs ₹113,311 naive,
> +43.9 % uplift, 0 violations, 0 LLM tokens, 228 out-of-policy
> actions blocked).
>
> The architecture is documented in the repo
> (`docs/ARCHITECTURE.md`). The full evaluation methodology is in
> `docs/eval-report.md` with 13 primary sources in `docs/evidence-pack.md`.
> A read-only MCP server (8 tools, official `mcp` Python SDK) lets
> any AI agent — Claude Desktop, Cursor, VS Code, OpenAI Agents SDK
> — inspect recovery operations in real time. A Supabase cloud
> mirror is one project and three tables away; it is RLS-deny-all
> by default and only the server-side service role reads or writes.
>
> The entire demo runs on a fresh `git clone` with zero API keys.
> The single most important line in the README is "zero keys needed
> to run it."

---

## Page 3 — Long-form answer: "Build challenges and technical obstacles"

**(paste this entire block into the second long-form field; this is what
the `JOURNAL.md` entries distill into a one-paragraph narrative)**

> Three failures shaped Cadence:
>
> (1) **The 125-test suite passed while the one-command demo crashed.**
> `Database.migrate()` looked for `V*__*.sql` files; our schema was
> `migrations.sql`. Tests passed because the test fixture (written
> by an earlier agent) had silently worked around the bug. The fix
> was one line in production and a new rule: every test suite must
> include at least one end-to-end test that exercises the real
> constructor.
>
> (2) **The pitch was 80 % of the grade.** The eval was strong; the
> live demo was not. A judge opening the SPA would see hard-coded
> "₹166,228" and "18 paused journeys" numbers and assume the eval
> was fabricated. We rewrote every view in the React SPA so that
> zero numbers are hard-coded; every KPI comes from a real
> `/api/*` endpoint, the chaos drills run server-side and return
> real drill output, and the Pay Portal calls `/api/pay/{id}/link`
> then `/api/pay/{id}/simulate-paid`. The test count grew from 125
> to 284 along the way.
>
> (3) **Raw JSON-RPC over stdio was a smell in 2026.** Cadence's first
> MCP server was 200 lines of hand-rolled request parsing. The
> official `mcp` Python SDK v1.x (the same SDK the Razorpay and
> Stripe MCP servers use) auto-generates JSON Schema from type
> hints, enforces "no print() to stdout" for stdio safety, and
> has an in-process test helper. The migration took 3 hours and
> 0 behaviour changes; the new test surface caught two subtle
> issues the old one had hidden.

---

## Page 3 — Long-form answer: "The bar mapping"

> The Razorpay Buildathon 2026 Track 3 bar: "Don't just identify the
> problem. Show measured money recovered across a batch, with
> compliant escalation, stopping rules, and an audit trail."
>
> | Bar element | Where in Cadence |
> |---|---|
> | Measured money recovered across a batch | `docs/eval-report.md` — 500-subscriber cohort, seed 42, byte-identical report. **+43.9 %** uplift over naive. |
> | Compliant escalation | Policy Guardian in `src/revive/policy/guardian.py` — every intervention passes through a pure-code veto with RBI 24h pre-debit notice, NPCI quiet hours, DND, touch caps. |
> | Stopping rules | Guardian vetoes: kill switch, DND list, hard-decline stop, touch cap, window expiry, attempts exhausted, quiet hours defer. **228 vetoes on the demo batch, 0 illegal actions executed.** |
> | Audit trail | Append-only hash-chained event log in `src/revive/store/event_store.py` — every state change is `sha256(prev + canonical(event))`. `revive_audit_verify` detects tamper and returns the bad seq. |

---

## Page 4 — Logistics (where applicable)

| Field | Value |
|---|---|
| Will you be in Bangalore from September 2026? | Yes |
| Specific date you can start | (your date) |
| Any constraints on your availability | (only if applicable; otherwise blank) |
| How did you hear about the buildathon | Razorpay engineering blog (or: Instagram, LinkedIn, college placement cell) |

---

## What to leave BLANK

- **Anything asking for keys.** Do not paste Razorpay or Supabase keys
  into the form. The keys live in `main/.env`, gitignored, server-side
  only. The application form is a customer-facing form; do not trust
  it with secrets.
- **Anything that contradicts the README.** If the form asks "did you
  use any external services" — the honest answer is "no for the demo;
  the architecture is keyless-first; live keys (Razorpay test mode,
  Supabase, Resend, Gemini/Groq) are an additive layer gated by
  environment variables, not a hard dependency."

---

## After submission

Save the form confirmation screenshot, archive the YouTube link, and
add the submission timestamp to `JOURNAL.md` so you have a complete
provenance trail when the panel replies.
