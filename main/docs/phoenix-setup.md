# Cadence — Phoenix 20.4.0 observability setup

**The 30-second walkthrough.** Phoenix is an *optional* sidecar. The
301 existing tests all run on the keyless, no-Phoenix path. To add the
observability sidecar to a developer laptop:

```bash
cd main
pip install -e ".[observability]"   # installs arize-phoenix (ELv2)
python -m uvicorn revive.api.app:app --port 8000
# in another terminal:
phoenix serve                        # Phoenix UI on http://localhost:6006
```

That's it. `revive.api.app` calls `revive.observability.phoenix.is_available()`
at request time inside the `/api/status` endpoint and the
`/api/trace/recent` endpoint. When Phoenix is present, those endpoints
report `phoenix_enabled: true` and the trace tree; when it isn't, they
report `phoenix_enabled: false` and an empty trace list. The SPA uses
the boolean to conditionally render a "View trace" affordance in the
journey timeline.

**Why Phoenix 20.4.0 specifically:** the release on 2026-08-26 ships an
in-process MCP toolset, the "Used by Anthropic" pedigree, and
`phoenix-cli setup` one-command auto-instrumentation. The pitch line is:
"Traced by the same observability stack that Anthropic recommends."

**License:** Phoenix uses the **Elastic License 2.0 (ELv2)**, not
OSI-approved MIT. The Cadence README already discloses this. For a
hackathon submission (not a hosted SaaS), ELv2 is fine: it allows
copying, modifying, and self-hosting; it only prohibits running a
hosted service that exposes Phoenix's features to third parties as
the product. We are not doing that.

**The contract that protects the 301 tests.** When `arize-phoenix` is
not installed:

- `/api/status` returns `phoenix_enabled: false`
- `/api/trace/recent` returns `{"enabled": false, "traces": []}`
- `revive.observability.phoenix.instrument()` returns `False` and
  never raises
- No code path in the recovery engine, the audit chain, the LLM
  client, or the dispatcher touches Phoenix

The keyless / no-Phoenix path is **byte-identical** to before this
sidecar was added. The Phoenix integration is observability, not
behaviour — it observes, it never intervenes.

**Demo script for the pitch video.** With Phoenix running:

1. Inject a webhook via the SPA's Testbench tab.
2. Open the Cadence journey drawer in the SPA — you'll see the live
   timeline of events.
3. Click "View trace" in the drawer — opens the Phoenix UI in a
   new tab with the matching OpenTelemetry trace tree.
4. The trace shows: `webhook.received` → `payment.failed` →
   `classification.completed` → `intervention.approved` →
   `executor.scheduled`. Each node has timing and attributes.
5. If the Guardian vetoed anything, the trace shows the
   `intervention.vetoed` event with the reason attribute.

**Disabling the sidecar for the keyless demo.** Don't install
`arize-phoenix`. The SPA's "View trace" affordance hides itself; the
rest of the demo is unchanged. This is the path the 301 tests exercise
on every CI run.

**Why we don't ship Phoenix in the public repo.** Phoenix is large
(~80 MB with deps), the ELv2 license is non-standard, and the
observability value is real but not on the Razorpay Buildathon bar's
critical path. Cadence's main story is the deterministic engine + the
MCP server; Phoenix is a layer on top of that.
