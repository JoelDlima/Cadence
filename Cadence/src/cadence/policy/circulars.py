"""RBI / NPCI circular ingestion: read PDFs, extract rules, expose via API.

This module ingests regulatory PDFs from ``data/circulars/`` (configurable),
extracts plain text with :mod:`pypdf` (lightweight, MIT, already a transitive
dep of many libs), pulls out a deterministic 1-sentence summary and a list of
"rule-ish" statements via a regex-driven heuristic, and stores them in the
``policy_circulars`` table created by ``V3__policy_circulars.sql``.

The optional PaddleOCR 3.7.0 path is NOT part of the keyless demo:
- PaddleOCR is a heavy install (~hundreds of MB) and behind an optional
  extra. The 303 existing tests pass without PaddleOCR.
- RBI / NPCI circulars are text PDFs (not scans), so ``pypdf`` covers the
  realistic case. OCR-on-image is a future add.

Exposed endpoints:
- ``GET /api/circulars`` — list ingested circulars (newest first)
- ``GET /api/circulars/{id}`` — full text + extracted rules for one circular
- ``POST /api/circulars/ingest`` — admin hook to re-scan ``data/circulars/``
  (DEMO-mode only; returns 403 in LIVE mode if Razorpay keys are set,
  matches the "DEMO = local, LIVE = real" contract from the rest of the API).

The pitch line: "We auto-ingest every new RBI / NPCI circular into the
engine's evidence pack." The implementation here is the *real* ingestion
loop; the future "every new" part is a one-line cron on top of this.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from cadence.store.db import Database

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Rule:
    """A single extracted rule from a circular."""
    section: str            # e.g. "Section 3.2"
    paragraph: str          # the sentence or short clause
    requires: str           # "RBI" or "NPCI" or "merchant"
    text: str               # the verbatim extracted line

    def to_dict(self) -> dict:
        return {
            "section": self.section,
            "paragraph": self.paragraph,
            "requires": self.requires,
            "text": self.text,
        }


@dataclass(frozen=True)
class Circular:
    source: str            # 'RBI' or 'NPCI' or 'other'
    title: str
    issued_on: str | None
    reference: str | None
    path: str
    text: str
    summary: str
    rules: list[Rule] = field(default_factory=list)
    ingested_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "id": None,        # filled in by the API layer
            "source": self.source,
            "title": self.title,
            "issued_on": self.issued_on,
            "reference": self.reference,
            "path": self.path,
            "text": self.text,
            "summary": self.summary,
            "rules": [r.to_dict() for r in self.rules],
            "ingested_at": self.ingested_at,
        }


# ----------------------------------------------------------------------------
# Heuristic extractors. These are deliberately simple: a regex pass over the
# plain text. RBI / NPCI documents have predictable headers; the goal here
# is to seed the engine's evidence pack with a list of "(section, requirement,
# text)" tuples the Guardian could reference. A future PaddleOCR-VL-1.6 + LLM
# pass can replace the heuristic without changing the API.
# ----------------------------------------------------------------------------

_RE_DATE = re.compile(r"\b(\d{1,2}\s+(?:January|February|March|April|May|June|"
                       r"July|August|September|October|November|December)\s+\d{4})\b")
_RE_REFERENCE = re.compile(r"\b(RBI|NPCI)\s*[/\-]?\s*([\w\-/\.]+\d{2,4})\b", re.IGNORECASE)
_RE_SECTION = re.compile(r"^(?:Section|Chapter|Para|Clause)\s+([\d.]+(?:\.\d+)?)\b",
                          re.IGNORECASE | re.MULTILINE)
_RULE_PREFIX = re.compile(
    r"\b(?:shall|must|may not|required to|is required to|prohibited from|"
    r"are required to|are not permitted|are prohibited)\b",
    re.IGNORECASE,
)


def _detect_source(text: str, path_hint: str = "") -> str:
    """Heuristic: 'RBI' in the first 2000 chars or filename -> 'RBI'.
    'NPCI' -> 'NPCI'. Default 'other'."""
    head = (text[:2000] + " " + path_hint).lower()
    if "rbi" in head or "reserve bank" in head:
        return "RBI"
    if "npci" in head or "national payments corporation" in head:
        return "NPCI"
    return "other"


def _extract_summary(text: str) -> str:
    """First sentence that is at least 40 characters and ends with a period.

    The 40-char minimum rejects section headers like 'Section 3.2 Notification
    timing.' (27 chars). Sentences are split on ``. `` / ``! `` / ``? ``
    boundaries. Falls back to the first 200 chars if no qualifying sentence
    is found.
    """
    for s in re.split(r"(?<=[.!?])\s+", text):
        s = s.strip()
        if 40 <= len(s) <= 200 and s.endswith((".", "!", "?")):
            return s
    return text.strip()[:200].rsplit(".", 1)[0] + "." if "." in text[:200] else text[:200]


def _extract_rules(text: str, source: str) -> list[Rule]:
    """Find sentences that contain rule-y language. Each match becomes a
    Rule with the current section context. We cap at 32 rules per circular
    so the API response stays small."""
    rules: list[Rule] = []
    current_section = "1"
    paragraphs = re.split(r"\n\s*\n", text)
    for p in paragraphs:
        # update section context on section headers
        m = _RE_SECTION.search(p)
        if m:
            current_section = m.group(1)
        # split into sentences
        for s in re.split(r"(?<=[.!?])\s+", p):
            s = s.strip()
            if not s:
                continue
            if _RULE_PREFIX.search(s):
                rules.append(
                    Rule(
                        section=f"Section {current_section}",
                        paragraph=s[:60] + ("..." if len(s) > 60 else ""),
                        requires=source,
                        text=s,
                    )
                )
                if len(rules) >= 32:
                    return rules
    return rules


def _extract_date(text: str) -> str | None:
    m = _RE_DATE.search(text)
    return m.group(1) if m else None


def _extract_reference(text: str) -> str | None:
    m = _RE_REFERENCE.search(text)
    if not m:
        return None
    return f"{m.group(1).upper()}/{m.group(2)}"


def _extract_text_from_pdf(path: Path) -> str:
    """Extract plain text from a PDF using pypdf. Raises ImportError if missing.

    The 303-test contract does not require pypdf for the keyless path: the
    circulars module is only invoked when a PDF file exists in the
    configured directory. The DEMO seed doesn't ship any PDFs.
    """
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise ImportError(
            "pypdf is required to ingest RBI / NPCI circular PDFs. "
            "Install with: pip install pypdf"
        ) from e
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception as exc:  # pragma: no cover - defensive
            _log.warning("pypdf: failed to extract %s: %s", path, exc)
    return "\n".join(parts).strip()


def extract_circular(path: Path) -> Circular | None:
    """Build a :class:`Circular` from a PDF file. Returns None when the file
    cannot be read, so the admin ingest endpoint skips it with a logged
    warning instead of failing the whole directory scan.

    A truncated or non-PDF file raises out of ``PdfReader(...)`` itself (pypdf
    raises ``PdfStreamError``/``PdfReadError``, not ImportError), so the guard
    has to be broad: one corrupt download in ``data/circulars/`` must not take
    the ingest endpoint down.
    """
    if not path.is_file():
        return None
    try:
        text = _extract_text_from_pdf(path)
    except ImportError:
        _log.warning("circulars: pypdf not installed; skipping %s", path)
        return None
    except Exception as exc:  # noqa: BLE001 - malformed / truncated / encrypted PDF
        _log.warning("circulars: cannot parse %s (%r); skipping", path, exc)
        return None
    if not text:
        return None
    source = _detect_source(text, path_hint=path.name)
    title = path.stem.replace("_", " ").replace("-", " ").strip() or path.name
    return Circular(
        source=source,
        title=title,
        issued_on=_extract_date(text),
        reference=_extract_reference(text),
        path=str(path.resolve()),
        text=text,
        summary=_extract_summary(text),
        rules=_extract_rules(text, source),
    )


def ingest_directory(db: Database, directory: Path) -> list[Circular]:
    """Scan a directory for PDFs, extract each, upsert into policy_circulars.

    Returns the list of Circulars processed (whether inserted or updated).
    Idempotent: re-ingesting the same file updates the row, never duplicates.
    """
    if not directory.is_dir():
        return []
    pdfs = sorted(directory.glob("*.pdf"))
    ingested: list[Circular] = []
    for path in pdfs:
        c = extract_circular(path)
        if c is None:
            continue
        _upsert(db, c)
        ingested.append(c)
    return ingested


def list_circulars(db: Database) -> list[dict]:
    """Return all ingested circulars, newest first."""
    rows = db.conn.execute(
        "SELECT id, source, title, issued_on, reference, path, summary, "
        "rules_json, ingested_at FROM policy_circulars ORDER BY id DESC"
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        try:
            rules = json.loads(r["rules_json"])
        except json.JSONDecodeError:
            rules = []
        out.append({
            "id": r["id"],
            "source": r["source"],
            "title": r["title"],
            "issued_on": r["issued_on"],
            "reference": r["reference"],
            "path": r["path"],
            "summary": r["summary"],
            "rules": rules,
            "ingested_at": r["ingested_at"],
        })
    return out


def get_circular(db: Database, circular_id: int) -> dict | None:
    """Return a single circular by id, including its full text and rules."""
    row = db.conn.execute(
        "SELECT id, source, title, issued_on, reference, path, text, summary, "
        "rules_json, ingested_at FROM policy_circulars WHERE id = ?",
        (circular_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        rules = json.loads(row["rules_json"])
    except json.JSONDecodeError:
        rules = []
    return {
        "id": row["id"],
        "source": row["source"],
        "title": row["title"],
        "issued_on": row["issued_on"],
        "reference": row["reference"],
        "path": row["path"],
        "text": row["text"],
        "summary": row["summary"],
        "rules": rules,
        "ingested_at": row["ingested_at"],
    }


def _upsert(db: Database, c: Circular) -> int:
    """Insert or update a circular. Returns the row id."""
    rules_json = json.dumps([r.to_dict() for r in c.rules])
    existing = db.conn.execute(
        "SELECT id FROM policy_circulars WHERE path = ?", (c.path,)
    ).fetchone()
    if existing is not None:
        db.conn.execute(
            """
            UPDATE policy_circulars
               SET source = ?, title = ?, issued_on = ?, reference = ?,
                   text = ?, summary = ?, rules_json = ?,
                   ingested_at = ?
             WHERE id = ?
            """,
            (c.source, c.title, c.issued_on, c.reference,
             c.text, c.summary, rules_json, c.ingested_at, existing["id"]),
        )
        return int(existing["id"])
    cur = db.conn.execute(
        """
        INSERT INTO policy_circulars
            (source, title, issued_on, reference, path, text, summary,
             rules_json, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (c.source, c.title, c.issued_on, c.reference, c.path,
         c.text, c.summary, rules_json, c.ingested_at),
    )
    return int(cur.lastrowid)
