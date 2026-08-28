# Build Journal — Revive

Plain-English log of what went wrong, what we decided, and why. Newest entries at the
bottom. This file feeds the application form field "Build Challenges and Technical
Obstacles" and the panel stories.

---

## 2026-08-22 — Setup and foundation day

**Git repo created in the wrong folder.** The first `git init` ran in the home directory
instead of the project folder because the terminal was not pointed where I thought. An
empty `.git` appeared in the user folder. Removed it immediately and re-initialized
inside the project. Lesson: always confirm the working directory before commands that
create things.

**Missing packages on Windows.** The config file loads settings from a `.env` file and
handles Indian time zones. Both need helper libraries (`python-dotenv`, `tzdata`) that
were not installed. The first test run failed on import until they were added and pinned
in the project file. Lesson: Windows does not ship a timezone database; never assume.

**Parallel coding agents: trust but verify.** Four agents coded separate modules at
once. Three reported success with test counts. The fourth returned a completely empty
report — but checking the disk showed it had actually written every file correctly. The
opposite also happened once: two agent launches were cut off mid-run and produced
nothing, so they had to be relaunched in smaller batches. Lesson: an agent's report is
not evidence; the files and the test suite are.

**Contracts before parallel work.** Before letting agents write code at the same time,
one small file of shared data shapes was written by hand (the request/result formats
passed between the scheduler and the executors). This is why four independently written
modules fit together with almost no rework. Best decision of the day.

## 2026-08-22 — Making the loop real

**The state machine caught a design bug before it happened.** The plan said "when a
failure has an unknown cause, send it to human review." But the state machine only
allows entering human-review from the fresh state, not after classification. The engine
agent noticed the conflict and applied the jump at the earlier step instead, then
documented the deviation. Lesson: strict state machines are annoying exactly when they
are saving you.

**Razorpay's own docs exposed a gap in our gateway.** Their guide says duplicate
deliveries are normal and the event id in the request header is the proper way to spot
duplicates. Our gateway was deduplicating using an id inside the message body instead.
Fix queued as backlog item B-GATEWAY-1. Lesson: read the platform's integration guide
after building the integration, not only before.

**Free AI quotas were quietly cut.** Research showed Google reduced free Gemini limits
in December 2025 and 2026 sources disagree on exact numbers (some say 250 requests per
day for the good model, some say 1000+ for the lighter one). Response: plan for the
worst number, add a local offline model as a fallback brain, and keep a deterministic
path that needs no AI at all for most cases. The demo cannot be held hostage by a quota.

**Mock versus real, decided honestly.** Real WhatsApp business messaging needs company
verification that takes weeks — impossible for a student in two weeks. So the messaging
channel is built behind a proper replaceable interface with a mock inside, and the
payment side uses Razorpay's real test platform. Everything simulated is simulated on
purpose and labeled; everything real is really real. Lesson: judges respect honest
boundaries more than pretend integrations.

**Quiet hours defer instead of reject.** First draft of the guardian rejected actions
during night hours. That threw away recovery chances. Changed to: approve but postpone
to 9 AM Indian time. Customer is never disturbed; no revenue opportunity is dropped.

**Line-ending warnings on every commit.** Windows shows long CRLF warnings on `git add`.
Harmless noise; ignored after confirming nothing breaks.

## Open items

- B-GATEWAY-1: prefer the event-id header for duplicate detection (in progress today)
- C-LLM-1: add local Ollama model as a provider in the fallback chain
- Channels (WhatsApp mock + email), Hinglish reply understanding, simulator report,
  console — remaining phases

## 2026-08-22 (late) - The invisible bug: migrations never ran in production path

**What broke:** The one-command demo crashed with "no such table: journeys" while all
125 tests stayed green. Root cause: `Database.migrate()` searched for files named
`V*__*.sql` but our schema file was named plain `migrations.sql` - so production code
created empty databases forever. Tests never caught it because the test fixture
(applied by an earlier agent) had silently worked around it by applying the schema
itself, and even documented the upstream bug in a comment nobody read.

**Evidence:** SQLite probe showed fresh DBs contained only the `meta` table.
**Fix:** migrate() now loads `migrations.sql` plus any versioned files.
**Outcome:** quick_demo.py runs the full journey live: failure -> diagnosis ->
RBI pre-debit notice -> payday retry -> RECOVERED, audit chain verified True.
**Lesson:** green tests do not prove production paths work when fixtures replace the
code under test. Always keep one test that exercises the real constructor end-to-end.

## 2026-08-22 (finale) - Chaos night

Four disaster drills now pass against the real machinery: duplicate webhook replay
(frozen event log), kill-and-rebuild crash resume (idempotency key consumed once,
chain intact), every AI provider dead (deterministic fast path still recovered,
zero spend rows), and illegal proposals vetoed three ways (hard-decline stop,
illegality, finance tier). One more Windows-only lesson: SQLite handles owned by
FastAPI test state cannot be force-closed from cleanup code - TemporaryDirectory
now ignores those lock errors instead of masking drill results. Evidence pack
shipped so every pitch number can be opened live from regulator and rails docs.

## 2026-08-22 (late night) - The phantom-failure discovery

Deep research surfaced two things that change the story. First: NPCI has been
holding UPI AutoPay debits during peak hours since Aug 2025 and releasing them
later - meaning a "failed" debit may actually be QUEUED. Recovery logic that
cannot tell the difference harasses customers for payments that succeed on their
own and risks double-charges. Revive now detects hold-window failures and
silently waits past the release before any customer contact. Second: we shipped
a read-only MCP server, so any AI agent (Claude, Cursor, anything) can inspect
recovery journeys, metrics and dead letters through the same protocol Razorpay
itself ships. Also found: Livemint reported AutoPay failures up to 90 percent,
and Indian recovery-tool averages run 20-35 percent - our 54.4 percent is
1.5-2.5x the market. Lesson: the best features come from regulation changes,
not feature lists.

## 2026-08-27 - Phase 0-5: the real-data UI rebuild

**The pitch was 80 % of the grade.** The eval was already strong; the demo
was not. Judges opening the live SPA would see hard-coded "166,228" and
"18 paused journeys" numbers and assume the eval was fabricated. The
PyPortal's `setTimeout(1200) → paid: true` was the worst offender.

So we did a from-scratch rebuild of the demo surface. Every KPI now comes
from `/api/metrics` or `/api/guardian-stats`; the attention queue comes
from `/api/attention`; the bank list from `/api/banks`; the chaos drills
are real server-side runs returning real drill output. The Pay Portal
reads `?journey=<id>` from the URL and calls `/api/pay/{id}/link` then
`/api/pay/{id}/simulate-paid`. Eight backend endpoints were added; nine
endpoints the SPA actually calls; zero hard-coded numbers in the JSX.
Test count went from 125 to 284 along the way. Lesson: a beautiful
eval with a lying demo gets you exactly the rejection email.

## 2026-08-27 - Phase 3: the SDK conversation

**Raw JSON-RPC over stdio works. It is also the wrong move in 2026.** The
original MCP server was hand-rolled: a 200-line request dispatcher, hand-
written JSON Schemas, "no print() to stdout" discipline maintained by
hope. A research pass for Phase 3 confirmed the obvious — every official
2026 MCP quickstart, the Razorpay MCP server, the Stripe MCP server, the
Anthropic templates — they all use the `mcp` Python SDK. The SDK
auto-generates the JSON Schema from type hints, enforces the stdio rule,
supports protocol negotiation against the current spec (2026-07-28),
and has an in-process test helper that means we can run the full protocol
lifecycle in 11 unit tests without subprocess management. The migration
took 3 hours and 0 behavior changes; the new test surface caught two
subtle issues the old one had hidden. Lesson: writing a clean primitive
in 2026 is a smell. Use the SDK and ship more tools.

## 2026-08-27 - Phase 4: the cloud mirror

**The mirror had to be RLS-deny-all or it wasn't worth shipping.** The
supabase-schema.sql file referenced in the README did not exist. The
phase-4 commit wrote it (4 tables, RLS enabled, no policies, only the
service_role bypasses) and added a `/api/cloud/status` endpoint with
real sync state. The frontend sidebar got a Cloud Mirror indicator so
a judge can see at a glance whether the demo is connected. The research
that backed the decision is in `docs/cloud-mirror.md` — we evaluated
Turso, Neon, Cloudflare D1, SQLite Cloud, and PGlite and kept Supabase
for the documented reasons. Plan: ship the demo on Supabase; graduate
to Turso at post-hackathon scale. Lesson: the architectural decision
matters less than the documentation that lets a judge reconstruct it
in 30 seconds.

## 2026-08-28 - Phase 5: pitch assets

**Could not record a video in this environment, so the pitch assets
became three deliverables.** `docs/PITCH-VIDEO.md` is the shot-by-shot
5-minute script with "What NOT to say" table, recording budget, and
three winning lines to memorize. `docs/PITCH-DECK.md` is the same 5
minutes as a markdown slide deck; slide 1 pastes directly into the
application form's free-text summary field. `docs/PITCH-GIF.md` is the
10-second hero GIF capture instructions (Windows: OBS + ScreenToGif,
5 min total). The research pass confirmed what we already knew: a
public unlisted YouTube link is the de-facto expected format, and a
silent looping hero GIF in the README is now standard for 2026
hackathon submissions. Lesson: when you can't record, give the
reviewer every other form they might accept. The form has more than
one shape, and the application form accepts a Loom link *in addition*
to the 5-min video.
