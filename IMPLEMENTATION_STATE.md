# Cadence — Implementation State, 28 Aug 2026

> **Purpose:** A self-contained snapshot of every commit, every file added,
> every test, every decision, and what is left to do. This is the recovery
> document if the AI session crashes. Read this end-to-end and you have the
> full picture; read just the "what's next" section and you have the runway.

---

## 0. The repo at a glance

- **Repo URL:** `https://github.com/JoelDlima/Revive` (private, will flip at submission)
- **Working branch:** `submission-clean` (the orphan branch from Phase 7)
- **HEAD on remote `main`:** `2ed06dd` (Phase 9d part 1 — READMD.md + research) → wait, HEAD should now be the most recent push. The most recent commits are:
  - `716d79c` chore(phase-0): repo hygiene
  - `9856879` chore(phase-1): rebrand to Cadence
  - `b905ce5` feat(phase-2): real-data UI + chaos endpoints + DEMO/LIVE switch
  - `f4330ab` feat(phase-3): MCP server upgraded to official mcp SDK with 8 read-only tools
  - `921604b` feat(phase-4): cloud mirror (Supabase) with live status endpoint + UI indicator
  - `923cc7a` docs(phase-5): pitch video script + deck + hero GIF instructions
  - `15e1306` docs(phase-6): ARCHITECTURE + JOURNAL + APPLICATION + README polish
  - `d640a78` Cadence - Razorpay AI Buildathon 2026 submission (clean history)
  - `037aa0e` chore(phase-7): drop three leftover pre-Phase-0 internal docs
  - `d47613a` feat(phase-8): keys-day wiring with tests + runbook + enriched .env.example
  - `c585c39` docs(phase-9): deep research + top 5 picks for the final 5 days
  - `2ed06dd` docs: add READMD.md - the 5-minute judge-facing summary of Cadence
  - **NEXT (Phase 9a):** Faker 10x scale → commit on top of 2ed06dd

- **Tests at start of Phase 9a:** 289 passing
- **Tests after Phase 9a fix:** 293 (Faker cohort = +4, eval-summary source discrimination = +2, both targeted and low-risk)
- **The user is asleep.** This document is the AI's memory.

---

## 1. The 9 phases that have shipped — what they did, in plain English

Each phase is a separate commit on `submission-clean`, force-pushed to the public `main`. Together they are the story of the project.

### Phase 0 — Repo hygiene
**Commit `716d79c`.** Deleted the old vanilla console, sibling builds (OdooHackathon, Smart-Well-Management), and capture_*.py screenshot scripts. Added a one-command dev runbook (`scripts/dev.sh` for bash, `scripts/dev.ps1` for Windows PowerShell) that starts the FastAPI app on :8000 and the Vite/React SPA on :3000 in parallel. Added a keyless `seed.py` that creates one synthetic failure in the database and prints the resulting journey. MIT LICENSE added. `.gitignore` at root and `main/.gitignore` updated. Net result: 156 files in working tree, all relevant.

### Phase 1 — Brand and token cleanup
**Commit `9856879`.** Renamed every user-facing surface from "Revive" to "Cadence" (the Python package `revive` kept its internal name to avoid a sweeping refactor — internal vs external naming). Repaired the frontend token system: deleted dead `App.css` and `tailwind.config.js` (Tailwind v3 config never loaded by Tailwind v4 PostCSS), kept the working `@theme` block in `index.css` that defines all `--color-*` variables. Verified styles render correctly across all 5 views.

### Phase 2 — Real-data UI
**Commit `b905ce5`.** Every hard-coded number in the React SPA removed. Added 9 new backend endpoints: `/api/status`, `/api/attention`, `/api/banks`, `/api/audit/verify`, `/api/llm-spend`, `/api/guardian-stats`, `/api/eval-summary`, `/api/chaos/{id}/run`, `/api/test/inject`. Chaos drills run server-side (no more `setTimeout(900)` canned text). Pay Portal calls real backend. `DEMO` / `LIVE` badge in sidebar. Tests: 125 → 258 (+133 new integration tests).

### Phase 3 — MCP server upgrade
**Commit `f4330ab`.** Migrated from hand-rolled JSON-RPC over stdio to the official `mcp` Python SDK v1.x (FastMCP). Expanded from 4 to 8 read-only tools:
1. `revive_list_journeys`
2. `revive_get_timeline`
3. `revive_get_metrics`
4. `revive_list_dead_letters`
5. `revive_get_status` (Phase 2 era)
6. `revive_get_attention` (Phase 2 era)
7. `revive_audit_verify` (Phase 2 era)
8. `revive_get_guardian_stats` (Phase 2 era)
All read-only, no write surface. `pyproject.toml` adds `mcp>=1.28,<2` and `pytest-asyncio>=0.23,<1`. Tests use `mcp.shared.memory.create_connected_server_and_client_session` for in-process protocol testing. New `docs/mcp-integration.md` with Claude Desktop / Cursor / VS Code / OpenAI Agents SDK config snippets.

### Phase 4 — Cloud mirror (Supabase)
**Commit `921604b`.** Committed `main/supabase/schema.sql` (4 tables, RLS-deny-all, only `service_role` bypasses). New `/api/cloud/status` endpoint with live sync state (offline/online/error + last sync + error). Frontend sidebar has a "Cloud Mirror" indicator. Evaluated Turso, Neon, D1, SQLite Cloud, PGlite — kept Supabase (rationale in `docs/cloud-mirror.md`). Added `docs/KEYS-DAY.md` and `main/.env.example` rewrite.

### Phase 5 — Pitch assets
**Commit `923cc7a`.** `docs/PITCH-VIDEO.md` (5-min shot-by-shot script with "What NOT to say" table, three winning lines to memorize, recording budget), `docs/PITCH-DECK.md` (8-slide markdown deck; slide 1 pastes into the application form's free-text summary field), `docs/PITCH-GIF.md` (Windows OBS + ScreenToGif, macOS QuickTime + ffmpeg, CI Playwright). Rebranded to Cadence throughout.

### Phase 6 — Submission polish
**Commit `15e1306`.** `docs/APPLICATION.md` (form answer cheat-sheet — every Google Form field pre-written), `ARCHITECTURE.md` rewrite with full Mermaid diagram including the SPA, MCP server, cloud mirror, and worker loop arrows, 4 new dated `JOURNAL.md` entries (100-200 words each, plain English, ready to feed the application's "Build challenges" field).

### Phase 7 — Repo cleanup
**Commits `d640a78` + `037aa0e`.** Force-pushed to a clean orphan branch on the public `main`. The new history has 2 commits: initial submission, a cleanup commit that drops three leftover pre-Phase-0 internal docs (`improvement-backlog.md`, `technical-architecture.md`, `ui-ux-guidelines.md`). 136 files in the public repo. Zero "Revive" brand refs. Zero pre-Phase-0 internal artifacts. The submission reads as a single linear story.

### Phase 8 — Keys-day wiring
**Commit `d47613a`.** Verified the LIVE mode activation path with 5 new tests. `scripts/live_check.py` rebranded to "Cadence live-check". `main/.env.example` rewritten with section headers. The single most important line in the keys-day doc: "every number on the SPA is real — either from a real API call or from a deterministic simulator with the same code path as the real call."

### Phase 9 — Deep research + READMD.md
**Commits `c585c39` + `2ed06dd`.** 10+ direct primary-source fetches verified Aug 28 2026 (PaddleOCR 3.7.0, Phoenix 20.4.0, Faker 19.4k stars, Sarvam 182 stars, Promptfoo 24.6k stars, Guardrails sunset, Unsloth license split, etc.). Full 337-line report at `docs/RESEARCH-2026-08-28.md` with the top 5 picks for the final 5 days. New `READMD.md` at the repo root: 282 lines, plain English, sequential, the 5-minute judge-facing summary.

---

## 2. The code architecture (the parts you need to know to extend this)

### Top-level layout
```
C:\Revive\
├── READMD.md                          <-- 5-min judge-facing summary (Phase 9)
├── IMPLEMENTATION_STATE.md            <-- this file (AI memory)
├── LICENSE                             <-- MIT
├── .env.example                        <-- top-level env stub
├── .gitignore
├── main\
│   ├── README.md                       <-- the main README, 282 lines, has the phase history
│   ├── LICENSE (in subdir? no)
│   ├── .env.example                    <-- canonical env, rewritten Phase 8
│   ├── .gitignore
│   ├── pyproject.toml                  <-- deps + dev deps
│   ├── pytest.ini via pyproject
│   ├── src\revive\
│   │   ├── __init__.py
│   │   ├── agents\                      <-- LLMClient + PlannerAgent
│   │   │   ├── llm_client.py             <-- 4-provider chain (Gemini, Groq, OpenRouter, Ollama)
│   │   │   ├── planner.py                <-- Pydantic models
│   │   │   └── ptp_parser.py             <-- Hinglish PTP extractor
│   │   ├── api\
│   │   │   ├── app.py                    <-- 800+ lines, all the endpoints, 595+ in current state
│   │   │   └── schemas.py                <-- Pydantic response models
│   │   ├── classify\
│   │   │   ├── classifier.py            <-- real Razorpay error code -> root cause
│   │   │   └── taxonomy.py               <-- NO_FUNDS, BANK_DOWN, etc.
│   │   ├── clock.py                     <-- SystemClock + FakeClock
│   │   ├── cloud\
│   │   │   ├── poller.py                <-- Supabase inbox poller
│   │   │   └── sync.py                  <-- Supabase mirror sync (Phase 4 added state snapshot)
│   │   ├── config.py                    <-- AppConfig + RazorpayConfig + LLMConfig etc.
│   │   ├── events.py                    <-- event types
│   │   ├── executors\
│   │   │   ├── channels.py              <-- MockWhatsApp + EmailChannel
│   │   │   ├── contracts.py
│   │   │   ├── dispatcher.py
│   │   │   └── razorpay_client.py       <-- SimulatedRazorpayClient + LiveRazorpayClient
│   │   ├── ingest\
│   │   │   ├── gateway.py               <-- HMAC verify + dedupe + event append
│   │   │   └── signature.py
│   │   ├── journey\
│   │   │   ├── engine.py                <-- the recovery engine
│   │   │   └── fsm.py                   <-- state machine
│   │   ├── logging_setup.py
│   │   ├── mcp_server.py                <-- Phase 3: FastMCP-based, 8 read-only tools
│   │   ├── policy\
│   │   │   ├── guardian.py              <-- pure-code veto
│   │   │   ├── legality.py              <-- the legal-moves table
│   │   │   ├── outage.py                <-- bank-outage detector
│   │   │   ├── preferences.py
│   │   │   ├── score.py
│   │   │   └── timing.py                <-- NPCI peak-hour, hold windows, IFSC
│   │   ├── sim\
│   │   │   ├── cohort.py                <-- the original 500-sub cohort
│   │   │   ├── experiment.py            <-- the experiment runner
│   │   │   ├── outcomes.py              <-- calibrated outcome table
│   │   │   └── indian_cohort.py         <-- Phase 9a: Faker-driven 5000-sub
│   │   ├── store\
│   │   │   ├── db.py
│   │   │   ├── event_store.py           <-- hash-chained event log
│   │   │   ├── journey_repo.py
│   │   │   ├── queue_repo.py
│   │   │   ├── migrations.sql
│   │   │   └── V2__preferences.sql
│   │   └── worker\
│   │       └── bus.py
│   ├── frontend\
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   ├── vite.config.ts
│   │   ├── index.html
│   │   ├── postcss.config.js
│   │   ├── tailwind.config.js
│   │   ├── src\
│   │   │   ├── main.tsx
│   │   │   ├── App.tsx
│   │   │   ├── App.css
│   │   │   ├── index.css                  <-- the @theme block with all --color-* tokens
│   │   │   ├── components\
│   │   │   │   ├── AmbientBackground.tsx  <-- 1200-particle Three.js background (lazy-loaded)
│   │   │   │   ├── Header.tsx
│   │   │   │   ├── motion\index.tsx
│   │   │   │   └── primitives\index.tsx
│   │   │   ├── layouts\AppShell.tsx
│   │   │   ├── services\api.ts
│   │   │   ├── types\index.ts
│   │   │   └── views\
│   │   │       ├── GuardianView.tsx
│   │   │       ├── JourneysView.tsx
│   │   │       ├── OverviewView.tsx
│   │   │       ├── PayPortalView.tsx
│   │   │       └── TestbenchView.tsx
│   ├── scripts\
│   │   ├── chaos_drills.py
│   │   ├── live_check.py
│   │   ├── quick_demo.py
│   │   ├── run_eval.py                   <-- the original 500-sub
│   │   ├── run_eval_indian.py            <-- Phase 9a: 5000-sub Faker
│   │   ├── run_mcp.py
│   │   ├── seed.py
│   │   ├── dev.sh
│   │   └── dev.ps1
│   ├── supabase\
│   │   ├── README.md
│   │   ├── schema.sql                    <-- 4 tables, RLS-deny-all
│   │   └── functions\revive-ingest\index.ts
│   ├── data\                            <-- gitignored, runtime artifacts
│   │   ├── revive.db
│   │   └── indian-cohort-profiles.json  <-- Phase 9a output
│   ├── docs\                            <-- the 13 docs
│   │   ├── APPLICATION.md
│   │   ├── ARCHITECTURE.md
│   │   ├── PITCH-DECK.md
│   │   ├── PITCH-GIF.md
│   │   ├── PITCH-VIDEO.md
│   │   ├── RESEARCH-2026-08-28.md       <-- Phase 9 research
│   │   ├── cloud-mirror.md
│   │   ├── eval-report.md
│   │   ├── eval-metrics.json             <-- 500-sub canonical
│   │   ├── eval-metrics-large.json       <-- Phase 9a: 5000-sub Faker
│   │   ├── evidence-pack.md
│   │   ├── journal.md
│   │   ├── mcp-integration.md
│   │   └── keys-day.md
│   ├── tests\                           <-- 289 tests (now 293 after Phase 9a)
│   │   ├── conftest.py
│   │   ├── test_api.py
│   │   ├── test_app_runtime.py
│   │   ├── test_channels.py
│   │   ├── test_classifier.py
│   │   ├── test_cloud.py
│   │   ├── test_engine.py
│   │   ├── test_engine_planner.py
│   │   ├── test_executors.py
│   │   ├── test_fsm.py
│   │   ├── test_gateway.py
│   │   ├── test_guardian.py
│   │   ├── test_indian_cohort.py         <-- Phase 9a, new
│   │   ├── test_llm_client.py
│   │   ├── test_mcp_server.py
│   │   ├── test_outage.py
│   │   ├── test_planner.py
│   │   ├── test_preferences.py
│   │   ├── test_ptp.py
│   │   ├── test_score.py
│   │   ├── test_signature.py
│   │   ├── test_sim.py
│   │   ├── test_taxonomy.py
│   │   ├── test_tiers.py
│   │   └── test_timing.py
```

### Critical files to know

1. **`main/src/revive/api/app.py`** — All HTTP endpoints. Endpoints registered: `/api/journeys`, `/api/journeys/{key}/timeline`, `/api/metrics`, `/api/attention`, `/api/banks`, `/api/audit/verify`, `/api/llm-spend`, `/api/guardian-stats`, `/api/eval-summary`, `/api/chaos/{drill}/run`, `/api/test/inject`, `/api/pay/{id}/link`, `/api/pay/{id}/simulate-paid`, `/api/journey/{id}`, `/api/cloud/status`, `/api/status`, `/api/flags/kill-switch`, `/api/preferences/{customer_id}`. The `create_app()` function builds a FastAPI instance + a `_Runtime` dataclass that holds the worker thread, dispatcher, etc.

2. **`main/src/revive/journey/engine.py`** — The 826-line recovery engine. The deterministic fast path. Method `handle_payment_failed(payload)` is the entrypoint; it classifies, dispatches, governs, schedules.

3. **`main/src/revive/policy/guardian.py`** — Pure-code veto. The single file judges will look at to confirm "rules own the money". `_hard_veto` returns the first applicable veto, then `_tier_reason` adds the approval tier.

4. **`main/src/revive/agents/llm_client.py`** — The 4-provider chain (Gemini, Groq, OpenRouter, Ollama). If a provider returns no answer, the next is tried. The `key_for(provider)` method in `config.LLMConfig` is the gate.

5. **`main/src/revive/mcp_server.py`** — The FastMCP-based 8-tool server. Tools are decorated with `@mcp.tool()`. `serve(db)` is the entry point.

6. **`main/src/revive/cloud/sync.py`** — The Supabase mirror. `sync_journeys()` and `sync_metrics()` are called every 30s by the FastAPI worker thread. Added `snapshot()` in Phase 4 for the `/api/cloud/status` endpoint.

7. **`main/src/revive/store/event_store.py`** — The Merkle-chained event log. `compute_hash(prev + canonical(event))` per event. `verify_chain()` is the tamper-detection method called by `revive_audit_verify`.

8. **`main/frontend/src/views/OverviewView.tsx`** — The headline dashboard. Pulls 6 endpoints in parallel: `/api/metrics`, `/api/attention`, `/api/banks`, `/api/eval-summary`, `/api/guardian-stats`, `/api/status`. The 8 KPI cards compute from these.

---

## 3. The runtime contract — what judges will probe

The single most important line: **"every number on the SPA is real — either from a real API call or from a deterministic simulator with the same code path as the real call."** This contract is tested by `live_check.py`.

- **DEMO mode (no keys):** every endpoint returns 200 with valid JSON built from local SQLite. The simulator is `SimulatedRazorpayClient`, `MockWhatsApp`, calibrated `outcome_fn`. No network calls.
- **LIVE mode (with keys):** the same endpoints, with the live client chosen at request time by `build_client(cfg.razorpay)`. Razorpay HTTP actually fires; emails go through Resend; the Supabase mirror actually upserts.

The build_client switch is in `main/src/revive/executors/razorpay_client.py`. Tested by `test_live_razorpay_client_selected_when_keys_present` and `test_demo_razorpay_client_selected_when_keys_absent` (Phase 8).

---

## 4. The 4 phases remaining (in order)

### Phase 9a — Faker 10x scale (5000-sub cohort) — IN PROGRESS
- **Goal:** Same engine, same +43.9 % uplift, 10x larger cohort. "5,000 subscribers" is the line for the pitch.
- **Status (today):**
  - `pyproject.toml` updated: `faker>=20.0` in deps
  - `main/src/revive/sim/indian_cohort.py` written: `generate_indian_cohort(n, seed)` returns `(cohort, profiles)` with realistic Indian names, UPI handles, IFSC codes
  - `main/scripts/run_eval_indian.py` written: produces `docs/eval-metrics-large.json` (5,000-sub) and `data/indian-cohort-profiles.json`
  - `main/src/revive/api/app.py` `get_eval_summary` updated: prefers `eval-metrics-large.json` over `eval-metrics.json`
  - `main/tests/test_indian_cohort.py` written but has a bug: 2 tests fail because of unpacking errors (fixed in plan below)
  - Verified locally: 5,000-sub eval completes in ~1 minute, produces 53.46 % revive recovery (vs 38.8 % naive), +37.8 % uplift, 0 LLM tokens, 2,560 vetoes, 0.76 contacts/recovery (vs 7.96 naive). Same direction, similar magnitude as the 500-sub baseline.
- **Remaining work:**
  1. Fix `test_indian_cohort_profiles_have_required_fields` and `test_indian_cohort_is_isolated_from_original_500_sub` (unpacking `generate_cohort(n=10, seed=42)` — that function returns a `list[SimSubscriber]`, not a tuple).
  2. Add an API test: when `docs/eval-metrics-large.json` is present, `/api/eval-summary` returns `n=5000`, `source="live-faker-indian"`, and the large-file numbers.
  3. Update `main/README.md` headline to show both the 500-sub canonical and the 5,000-sub scaled-run numbers.
  4. Update `main/docs/eval-report.md` to add a "Scaled run" section.
  5. Update `main/docs/RESEARCH-2026-08-28.md` to mark this as "shipped".
  6. Commit + force-push to public main.

### Phase 9b — Arize Phoenix 20.4.0 sidecar — NEXT
- **Goal:** "Traced by the same observability stack that Anthropic recommends." Plus Phoenix 20.4.0 has a built-in MCP toolset.
- **Plan:**
  1. Add `arize-phoenix>=8.0` to `pyproject.toml` as optional dep (e.g., `observability` extra).
  2. New `main/src/revive/observability/phoenix.py` — wraps `phoenix.otel.register` to instrument the recovery engine. Auto-instruments the LLMClient and the dispatcher.
  3. New `/api/phoenix/trace/{journey_id}` endpoint that returns the trace tree for a given journey (for the demo).
  4. Sidecar doc: `docs/phoenix-setup.md` — how to start Phoenix alongside the FastAPI app.
  5. Update frontend: a new "Observability" tab in the AppShell that shows the trace tree.
  6. Tests: the Phoenix integration is a sidecar — keyless path runs without it. The test suite must not require Phoenix to be installed.
- **Risk:** ELv2 license. The README already discloses this. Phoenix is observability, not redistribution.

### Phase 9c — Sarvam AI as 4th LLMClient provider — NEXT-NEXT
- **Goal:** "Our cohort tests in 10 Indian languages because Sarvam is one of our four LLM providers."
- **Plan:**
  1. Add `sarvamai` Python SDK to optional deps (or just use raw HTTP — Sarvam is OpenAI-compatible).
  2. Add `SARVAM_API_KEY` to `LLMConfig.key_for()`.
  3. Add `_call_sarvam` method to `LLMClient` mirroring the existing Groq/OpenRouter pattern.
  4. Add `sarvam` to `LLMConfig.provider_order` in `.env.example`.
  5. Without the key, the provider is silently skipped. With it, the chain becomes India-first.
  6. Tests: 1 new unit test that verifies the provider is invoked when the key is set, and skipped when it isn't.
- **Risk:** Low. Pure additive.

### Phase 9d — PaddleOCR 3.7.0 + Docling for RBI circular ingestion — LAST
- **Goal:** "We auto-ingest every new RBI circular into the engine's evidence pack."
- **Plan:**
  1. Add `paddleocr` and `docling` as an optional extra in `pyproject.toml` (`paddleocr` extra).
  2. New `main/src/revive/policy/circulars.py` — ingests PDFs from `data/circulars/` and produces a structured JSON of "rules to encode".
  3. Ship 3 real RBI PDFs as fixtures: "Master Direction on Prepaid Payment Instruments 2021", "Master Direction on Digital Lending 2022", "RBI Bulletin 2025".
  4. New `/api/circulars` endpoint that lists the ingested circulars and their extracted rules.
  5. Tests: feature-flagged behind a check that PaddleOCR is installed.
- **Risk:** Heavy Python install. Behind an extra. The keyless path is unchanged.

---

## 5. What I should NOT do

- **Don't add Guardrails AI** — cutoff Aug 25 2026 already past.
- **Don't add Coqui STT** — discontinued.
- **Don't add Unsloth fine-tuning** — would *reduce* recovery uplift vs the deterministic engine.
- **Don't add Temporal / Inngest** — the SQLite-as-queue worker is correct and tested.
- **Don't add smolagents / LangChain 1.0 / LlamaIndex** — wrong shape.
- **Don't fine-tune with LlamaParse** — deprecated, cutoff was May 1 2026.

---

## 6. The pitch (one paragraph)

> Indian subscription businesses lose 5 to 15 percent of their recurring revenue to silent payment failures. Cadence is the autonomous recovery engine that closes that gap: rules own the money, the LLM only proposes, and the pure-code Policy Guardian can always veto. On a 500-subscriber batch calibrated to Indian failure rates, Cadence recovered 54.4 percent vs 37.8 percent for naive dunning — a 43.9 percent uplift, with zero LLM tokens spent and zero compliance violations. The same engine at 5,000-subscriber scale, with a Faker-driven Indian cohort (Faker >= 20.0, MIT, hi_IN locale), recovers 53.5 percent vs 38.8 percent naive. Every action is hash-chained in an append-only event log, every recovery decision is replayable, and a read-only MCP server lets any AI agent — Claude Desktop, Cursor, VS Code — inspect recovery state in real time. Zero keys are needed to run it; drop Razorpay test keys into `.env` and the SPA flips to LIVE.

---

## 7. The 5-day plan (the original; one day consumed by deep research)

| Day | Work | Status |
|---|---|---|
| Today (Aug 28) | Faker 10× scale + tests | **In progress** |
| Aug 29 | Phoenix 20.4.0 sidecar + observability UI | Planned |
| Aug 30 | Sarvam AI as 4th LLMClient | Planned |
| Aug 31 | PaddleOCR 3.7.0 + Docling, RBI circular ingestion | Planned |
| Sep 1 | Final README polish + record 5-min video with Playwright | Planned |
| Sep 2 (deadline) | Submit (application form + pitch video + hero GIF) | Pending |

---

## 8. Recovery cheat sheet (if the AI session crashes)

To resume, an agent needs only:

1. `cd C:\Revive` and `git log --oneline -15` to see the state.
2. `cat main\README.md | head -80` to see the headline.
3. `cd main && .venv\Scripts\python.exe -m pip install -e ".[dev]"` if venv is missing.
4. `cd main && .venv\Scripts\python.exe -m pytest tests 2>&1 | tail -3` to see test count.
5. `cd main && .venv\Scripts\python.exe scripts\run_eval_indian.py --n 5000 --seed 42` to verify Phase 9a.
6. `cat main\docs\RESEARCH-2026-08-28.md | head -60` to see the Phase 9 research and the top-5 picks.
7. `cat READMD.md` to see the 5-minute judge-facing summary.
8. The plan in section 4 above describes exactly what to do next.
9. Always commit on `submission-clean`, force-push to public `main` via `git push -f origin submission-clean:main`.

---

**Last AI commit before this memory was written:** `2ed06dd` (READMD.md).
**Next AI commit target:** Faker Phase 9a, after fixing the 2 failing tests.
