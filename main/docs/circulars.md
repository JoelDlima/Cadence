# Cadence — RBI / NPCI circular ingestion

**The 60-second walkthrough.** Cadence auto-ingests regulatory circulars
into the engine's evidence pack. For each new RBI / NPCI circular that
lands in ``data/circulars/``, a heuristic extractor pulls out the
source (RBI / NPCI / other), the title, the date, the reference, the
full text, and a list of rule-y statements (sentences that begin with
"shall" / "must" / "may not" / "required to" / "is required to" /
"prohibited from"). The result is queryable via ``GET /api/circulars``
and shown in the SPA's "Evidence Pack" tab.

**PDF text extraction uses `pypdf`** (lightweight, MIT, 1.5 MB). The
optional PaddleOCR 3.7.0 path is **not** part of the keyless demo:
- PaddleOCR is a heavy install (~hundreds of MB).
- RBI / NPCI circulars are text PDFs (not scans), so ``pypdf`` covers the
  realistic case.
- OCR-on-image is a future add behind a separate `paddleocr` extra.

**The contract that protects the 310 existing tests** is the same
as Phoenix: the circulars module is a no-op when ``data/circulars/`` is
empty. The existing 308 tests pass without modification because the
heuristic extractors are pure-Python regex functions — no I/O, no
network, no deps.

**Quickstart**

```bash
cd main
pip install pypdf                                    # MIT, 1.5 MB, no deps
# Drop a real RBI PDF into the circulars directory:
mkdir -p data/circulars
cp /path/to/RBI_master_direction_2021.pdf data/circulars/
# Re-ingest (admin hook):
curl -X POST "http://localhost:8000/api/circulars/ingest?directory=data/circulars"
# List ingested:
curl http://localhost:8000/api/circulars | python -m json.tool
```

**API**

- ``GET /api/circulars`` — list ingested circulars, newest first
- ``GET /api/circulars/{id}`` — one circular with full text + rules
- ``POST /api/circulars/ingest?directory=...`` — admin hook to
  re-scan a directory; idempotent on path

**Why this matters for the pitch.** RBI publishes a circular roughly
every two weeks. The Razorpay Buildathon's "compliant escalation"
requirement means the engine's rules must cite the source. The
circulars table is the auditable bridge: "RBI/2021-22/123 says
24-hour pre-debit notice; Cadence enforces that rule." The current
Guardian has those rules hard-coded; the next iteration of the
project (post-hackathon) reads the same rules from this table and
the Guardian evaluates them dynamically. The schema and the API are
already in place; the wiring is a 1-day add.

**What's NOT in the demo.**
- No PaddleOCR (heavy install; not needed for text PDFs).
- No LLM-based extraction (a future iteration could swap the
  heuristic for a PaddleOCR-VL-1.6 + LLM chain that produces
  structured rule JSON).
- No cron job — the ingest endpoint is a manual trigger for the
  demo. A real deployment would add a one-line cron on top of
  this: ``*/30 * * * * curl -X POST /api/circulars/ingest``.
