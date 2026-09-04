"""R2: add /api/live/* endpoints for the Live Recovery page.

POST /api/live/customer         - create a real (or sim) Razorpay customer
POST /api/live/failure          - create a real (or sim) payment link +
                                  post a HMAC-signed payment.failed webhook
                                  into our own /webhooks/razorpay endpoint
POST /api/live/payment-paid     - close-the-loop: post a real
                                  payment_link.paid webhook so the SPA
                                  polling flips the journey to RECOVERED

If RZP_KEY_ID is set, every call goes to the real Razorpay test-mode
API; otherwise the simulator is used and the response is labelled
simulated=True so the SPA can show that to the operator.
"""
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel

from cadence.clock import utc_iso
from cadence.logging_setup import get_logger

log = get_logger("cadence.api.live")


class LiveCustomerIn(BaseModel):
    name: str = "Buildathon Judge"
    email: str = "judge@buildathon.local"
    contact: str = "+919999900000"


class LiveCustomerOut(BaseModel):
    id: str
    email: str
    contact: str
    simulated: bool


class LiveFailureIn(BaseModel):
    customer_id: str


class LivePaymentLinkOut(BaseModel):
    id: str
    short_url: str
    reference_id: str
    amount_minor: int
    status: str
    simulated: bool


class LiveFailureOut(BaseModel):
    journey_id: str
    event_id: str
    subscription_id: str
    payment_link: LivePaymentLinkOut




class LiveSendEmailIn(BaseModel):
    reference_id: str
    to: str
    subject: str | None = None
    text: str | None = None
    attach_pdf: bool = False

class LivePaymentPaidIn(BaseModel):
    reference_id: str
    # B-fix: the previous default of 'pay_LIVE_DEMO' deduplicated the
    # capture task on the second call (the queue's idempotency_key was
    # built from payment_id) so the worker silently dropped the task
    # and the journey stayed INTERVENING forever. The route now
    # generates a unique id when the caller does not supply one.
    payment_id: str | None = None


class LiveLifecycleForceIn(BaseModel):
    """A lifecycle drill targets one journey attempt: '<journey_id>:<attempt_no>'."""

    reference_id: str


class LiveLifecycleSmartIn(BaseModel):
    """Smart orchestrator input. `customer_hint` is free text the operator
    types (e.g. "this customer always pays after a nudge"); the LLM weighs
    it against the audit chain before choosing an outcome."""

    reference_id: str
    customer_hint: str | None = None
    timeout_seconds: int = 30


def create_live_router(*, app: FastAPI, db, runtime) -> APIRouter:
    """Build a /api/live/* router bound to the same dependencies the
    rest of the engine uses. Returns 501 with a clear message when
    Razorpay keys are absent; otherwise the simulator path is used
    and the response is labelled simulated=True.
    """
    router = APIRouter()

    @router.post("/api/live/customer", response_model=LiveCustomerOut)
    def create_live_customer(body: LiveCustomerIn) -> LiveCustomerOut:
        cfg = runtime.config.razorpay if runtime and runtime.config else None
        live = bool(cfg and cfg.is_live)
        cli = runtime.client if runtime else None
        if live and cli is not None:
            try:
                c = cli.create_customer(
                    name=body.name, email=body.email, contact=body.contact,
                )
                return LiveCustomerOut(id=c["id"], email=body.email,
                                       contact=body.contact, simulated=False)
            except Exception as exc:  # noqa: BLE001
                log.warning("live create_customer failed: %r", exc)
                raise HTTPException(
                    status_code=502,
                    detail=f"razorpay create_customer failed: {exc!r}",
                )
        # Simulated path.
        seed = f"{body.email}:{body.contact}"
        cid = f"cust_sim_{hashlib.sha1(seed.encode()).hexdigest()[:10]}"
        return LiveCustomerOut(id=cid, email=body.email, contact=body.contact, simulated=True)

    @router.post("/api/live/failure", response_model=LiveFailureOut)
    def create_live_failure(body: LiveFailureIn) -> LiveFailureOut:
        cfg = runtime.config.razorpay if runtime and runtime.config else None
        live = bool(cfg and cfg.is_live)
        cli = runtime.client if runtime else None

        # 1) Find-or-create a journey to attach the failure to.
        jr = runtime.journeys
        es = runtime.store
        # Open a fresh journey for this demo.
        journey_id = f"j_live_{uuid.uuid4().hex[:10]}"
        subscription_id = f"sub_live_{uuid.uuid4().hex[:8]}"
        amount_minor = 49900
        now = utc_iso(datetime.now(timezone.utc))
        jr.create(
            journey_id=journey_id, subscription_id=subscription_id,
            customer_id=body.customer_id, amount_minor=amount_minor,
            currency="INR", failure_code="NO_FUNDS", opened_at=now,
        )

        # 2) Create the payment link (live or sim).
        reference_id = f"{journey_id}:1"
        if live and cli is not None:
            try:
                link = cli.create_payment_link(
                    amount_minor=amount_minor, currency="INR",
                    customer_id=body.customer_id,
                    description="Cadence: complete your pending subscription payment",
                    reference_id=reference_id,
                )
                plink = LivePaymentLinkOut(
                    id=link["id"], short_url=link.get("short_url", ""),
                    reference_id=reference_id, amount_minor=amount_minor,
                    status=link.get("status", "created"), simulated=False,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("live create_payment_link failed: %r", exc)
                raise HTTPException(
                    status_code=502,
                    detail=f"razorpay create_payment_link failed: {exc!r}",
                )
        else:
            link_id = f"plink_sim_{hashlib.sha1(reference_id.encode()).hexdigest()[:12]}"
            short = f"https://rzp.io/i/sim_{hashlib.sha1(reference_id.encode()).hexdigest()[:8]}"
            plink = LivePaymentLinkOut(
                id=link_id, short_url=short, reference_id=reference_id,
                amount_minor=amount_minor, status="created", simulated=True,
            )

        # 3) Post a HMAC-signed payment.failed webhook to our own gateway.
        # Build the body in the same shape Razorpay would.
        event_id = f"evt_live_{uuid.uuid4().hex[:12]}"
        body_dict = {
            "id": event_id,
            "event": "payment.failed",
            "payload": {
                "subscription": {"entity": {"id": subscription_id, "customer_id": body.customer_id}},
                "payment": {"entity": {
                    "id": f"pay_failed_{uuid.uuid4().hex[:10]}",
                    "order_id": f"order_{uuid.uuid4().hex[:8]}",
                    "amount": amount_minor, "currency": "INR",
                    "error_code": "insufficient_funds",
                    "error_description": "Insufficient funds in bank account",
                }},
            },
        }
        raw = json.dumps(body_dict).encode("utf-8")
        secret = cfg.webhook_secret if cfg else ""
        signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest() if secret else "no-secret"
        # 4) Record the known payment-link reference, then send the controlled
        # failure through the same signed ingress and worker path as a Razorpay
        # delivery. The pre-created journey keeps the link reference stable;
        # the worker supplies classification, bandit, Guardian and writer events.
        try:
            es.append(
                event_type="journey.opened", aggregate_type="journey",
                aggregate_id=subscription_id,
                payload={"journey_id": journey_id, "source": "live.failure"},
                occurred_at=now, recorded_at=now,
                event_id=f"open_live_{uuid.uuid4().hex[:12]}",
            )
            from cadence.ingest.gateway import process_delivery
            status, body_out = process_delivery(
                db=db,
                webhook_secret=secret,
                clock=runtime.clock,
                raw=raw,
                signature=signature,
                event_id=event_id,
            )
            if status != 200 or body_out.get("status") != "accepted":
                raise HTTPException(
                    status_code=502,
                    detail=f"controlled webhook was not accepted: {body_out}",
                )
            # Store the actual Razorpay link in the same action shape used by
            # the dispatcher so Dashboard projections and lifecycle drills can
            # resolve it without a demo-only side channel.
            es.append(
                event_type="action.executed", aggregate_type="journey",
                aggregate_id=journey_id,
                payload={
                    "kind": "PAYMENT_LINK",
                    "status": "EXECUTED",
                    "ref": plink.id,
                    "payment_link_id": plink.id,
                    "plink_id": plink.id,
                    "short_url": plink.short_url,
                    "reference_id": reference_id,
                    "amount_minor": amount_minor,
                    "currency": "INR",
                    "customer_id": body.customer_id,
                    "attempt_no": 1,
                    "simulated": plink.simulated,
                    "source": "live.failure",
                },
                occurred_at=now, recorded_at=now,
                event_id=f"act_live_{uuid.uuid4().hex[:12]}",
            )
            # First tick handles the failure; a second drains the resulting
            # approved intervention so the message and reasoning are visible
            # immediately in the Live Recovery screen. Minimal route tests
            # provide an engine but not the worker wrapper, so they invoke the
            # same handler directly.
            if hasattr(runtime, "worker") and hasattr(runtime, "handlers"):
                runtime.worker.run_once(runtime.handlers, max_tasks=5)
                runtime.worker.run_once(runtime.handlers, max_tasks=5)
            elif hasattr(runtime, "engine"):
                runtime.engine.handle_payment_failed({
                    "subscription_id": subscription_id,
                    "customer_id": body.customer_id,
                    "amount_minor": amount_minor,
                    "currency": "INR",
                    "failure_code": "insufficient_funds",
                    "error_description": "Insufficient funds in bank account",
                })
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("live failure ingress/worker failed: %r", exc)
            raise HTTPException(status_code=500, detail=f"recovery worker failed: {exc!r}")        # Mirror the new link to Supabase so the cloud table matches the
        # local chain from the moment the link exists. Best effort.
        try:
            from cadence.cloud.plink_mirror import get_plink_mirror
            get_plink_mirror(runtime.config).upsert_plink(
                plink_id=plink.id, journey_id=journey_id,
                subscription_id=subscription_id, customer_id=body.customer_id,
                amount_minor=amount_minor, currency="INR",
                status="created", short_url=plink.short_url,
                reference_id=reference_id, created_at=now,
            )
        except Exception as exc:  # noqa: BLE001
            log.info("plink mirror skipped for %s: %r", plink.id, exc)
        return LiveFailureOut(
            journey_id=journey_id, event_id=event_id,
            subscription_id=subscription_id, payment_link=plink,
        )

    @router.post("/api/live/payment-paid", response_model=dict)
    def post_payment_paid(body: LivePaymentPaidIn) -> dict:
        """Close-the-loop helper: posts a payment_link.paid webhook for
        the given reference_id. The dispatcher will (a) write the
        E_PAYMENT_RECOVERED event on the journey aggregate, (b) enqueue
        a capture task, and (c) on the next worker tick flip the
        journey state to RECOVERED.
        """
        cfg = runtime.config.razorpay if runtime and runtime.config else None
        event_id = f"evt_live_paid_{uuid.uuid4().hex[:10]}"
        # Parse the reference_id into journey_id + attempt.
        if ":" not in body.reference_id:
            raise HTTPException(status_code=400, detail="reference_id must be '{journey_id}:{attempt_no}'")
        journey_id, _, attempt_str = body.reference_id.rpartition(":")
        # Look up the journey so we can pull its subscription_id.
        jr = runtime.journeys
        j = jr.get(journey_id)
        if j is None:
            raise HTTPException(status_code=404, detail=f"unknown journey {journey_id}")
        subscription_id = j.subscription_id
        # B-fix: a fresh payment id per call prevents the queue's
        # idempotency_key (which is built from payment_id) from
        # suppressing a second-run capture task.
        payment_id = body.payment_id or f"pay_live_{uuid.uuid4().hex[:12]}"
        body_dict = {
            "id": event_id,
            "event": "payment_link.paid",
            "payload": {
                "payment_link": {"entity": {
                    "id": f"plink_{uuid.uuid4().hex[:8]}",
                    "reference_id": body.reference_id,
                }},
                "payment": {"entity": {
                    "id": payment_id,
                    "amount": 49900, "currency": "INR", "status": "captured",
                }},
            },
        }
        raw = json.dumps(body_dict).encode("utf-8")
        secret = cfg.webhook_secret if cfg else ""
        signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest() if secret else "no-secret"
        # Call process_delivery directly with our raw body + signature.
        try:
            from cadence.ingest.gateway import process_delivery
            status, body_out = process_delivery(
                db=db, webhook_secret=secret,
                clock=runtime.clock, raw=raw, signature=signature,
                event_id=event_id,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("post_payment_paid process_delivery failed: %r", exc)
            raise HTTPException(status_code=500, detail=f"webhook ingest failed: {exc!r}")
        # B-fix: echo the generated payment_id so the SPA + verify
        # script can assert two calls produced distinct ids.
        return {"status": body_out.get("status", "unknown"), "http": status, "event_id": event_id,
                "journey_id": journey_id, "subscription_id": subscription_id,
                "payment_id_used": payment_id}



    @router.post("/api/live/send-email")
    def send_live_email(body: LiveSendEmailIn):
        # Defensive: ensure .env is loaded so RESEND/ELEVENLABS keys are visible
        from dotenv import load_dotenv as _ld
        from pathlib import Path as _P
        _ld(_P(__file__).resolve().parents[2] / ".env", override=False)
        import os as _os
        """Send the LLM-written Hinglish nudge to a real inbox via Resend.

        This is the 'Gmail proof' for the demo: the user types their
        email, clicks Send, switches to their Gmail tab, and sees the
        Hinglish message Cadence would send to the customer. If
        RESEND_API_KEY is not configured, the route returns a clear
        501 with a SKIP message; the SPA falls back to a toast that
        says '(demo mode — no Resend key set, would have sent to <to>)'.

        When `attach_pdf=true` the route also looks up the journey,
        pulls its last 24h of audit events, and renders a one-page
        PDF summary that is (a) returned in the JSON response as
        base64 and (b) sent to Resend as an attachment.
        """
        cfg = runtime.config.razorpay if runtime and runtime.config else None
        import os as _os
        # Optionally build the PDF attachment from the journey's last
        # 24h of audit events. reportlab is optional: when the user
        # asked for a PDF but reportlab is missing we fall through
        # to sending the email without the attachment (and surface
        # the reason in the response).
        pdf_b64: str | None = None
        pdf_filename: str | None = None
        pdf_size_bytes: int | None = None
        pdf_skipped_reason: str | None = None
        if body.attach_pdf:
            try:
                from reportlab.lib.pagesizes import LETTER
                from reportlab.lib import colors
                from reportlab.lib.styles import getSampleStyleSheet
                from reportlab.lib.units import inch
                from reportlab.platypus import (
                    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                )
                from io import BytesIO
                import base64 as _b64
                from datetime import datetime as _dt, timedelta as _td, timezone as _tz

                # Parse reference_id ("journey_id:attempt") and fetch the journey.
                journey_id = body.reference_id.split(":", 1)[0]
                jr = runtime.journeys
                es = runtime.store
                journey = jr.get(journey_id)
                if journey is None:
                    pdf_skipped_reason = f"unknown journey {journey_id}"
                else:
                    all_events = es.get_by_aggregate("journey", journey.subscription_id)
                    cutoff = _dt.now(_tz.utc) - _td(hours=24)
                    recent: list = []
                    for ev in all_events:
                        try:
                            ts = _dt.fromisoformat(ev.occurred_at.replace("Z", "+00:00"))
                        except Exception:
                            continue
                        if ts >= cutoff:
                            recent.append(ev)

                    buf = BytesIO()
                    doc = SimpleDocTemplate(
                        buf, pagesize=LETTER,
                        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                        title=f"Cadence journey {journey.journey_id}",
                    )
                    styles = getSampleStyleSheet()
                    story = []
                    story.append(Paragraph(
                        f"Cadence recovery journey {journey.journey_id}",
                        styles["Title"],
                    ))
                    story.append(Paragraph(
                        f"Last 24 hours — {len(recent)} event(s)",
                        styles["Normal"],
                    ))
                    story.append(Spacer(1, 0.2 * inch))

                    def _trunc(payload: dict, limit: int = 80) -> str:
                        try:
                            s = json.dumps(payload, sort_keys=True, default=str)
                        except Exception:
                            s = str(payload)
                        return s if len(s) <= limit else s[: limit - 1] + "\u2026"

                    rows = [["time (UTC)", "type", "summary"]]
                    for ev in recent:
                        rows.append([
                            ev.occurred_at,
                            ev.type,
                            _trunc(ev.payload),
                        ])
                    if len(rows) == 1:
                        rows.append(["\u2014", "(no events in last 24h)", "\u2014"])
                    tbl = Table(
                        rows,
                        colWidths=[2.0 * inch, 1.8 * inch, 3.4 * inch],
                        repeatRows=1,
                    )
                    tbl.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 10),
                        ("FONTSIZE", (0, 1), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                         [colors.whitesmoke, colors.HexColor("#e2e8f0")]),
                        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]))
                    story.append(tbl)
                    story.append(Spacer(1, 0.3 * inch))
                    story.append(Paragraph(
                        "Generated by Cadence (Razorpay Buildathon Track 3)",
                        styles["Italic"],
                    ))
                    doc.build(story)
                    raw_pdf = buf.getvalue()
                    pdf_bytes = len(raw_pdf)
                    pdf_b64 = _b64.b64encode(raw_pdf).decode("ascii")
                    pdf_filename = f"cadence-journey-{journey.journey_id}.pdf"
                    pdf_size_bytes = pdf_bytes
            except ImportError as exc:
                pdf_skipped_reason = f"reportlab not installed: {exc!r}"
            except Exception as exc:  # noqa: BLE001
                pdf_skipped_reason = f"pdf generation failed: {exc!r}"
                log.warning("live send-email pdf generation failed: %r", exc)

        if not (_os.environ.get("RESEND_API_KEY") or (cfg and getattr(cfg, "resend_api_key", None))):
            resp = {"status": "skipped", "http": 200,
                    "detail": "RESEND_API_KEY not set; bubble shown in SPA but no real send",
                    "to": body.to}
            if pdf_b64:
                resp["pdf_filename"] = pdf_filename
                resp["pdf_size_bytes"] = pdf_size_bytes
                resp["pdf_base64"] = pdf_b64
            elif pdf_skipped_reason:
                resp["pdf_skipped_reason"] = pdf_skipped_reason
            return resp
        # Build subject + body
        from cadence.agents.message_writer import _NUDGE_SYSTEM
        text = body.text or (
            "Namaste! Aapka subscription ka payment abhi pending hai. "
            "Jab convenient ho, neeche diye gaye link se pay kar dijiye. "
            "Madad ke liye yahan reply karein. - Cadence"
        )
        subject = body.subject or "Action needed: complete your Cadence subscription"
        # POST to Resend
        import httpx as _httpx
        rzp = _os.environ.get("RESEND_API_KEY")
        payload: dict = {
            "from": "Cadence <onboarding@resend.dev>",
            "to": [body.to],
            "subject": subject,
            "text": text,
        }
        if pdf_b64 and pdf_filename:
            payload["attachments"] = [
                {"filename": pdf_filename, "content": pdf_b64},
            ]
        try:
            r = _httpx.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {rzp}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=10.0,
            )
            resp = {"status": "sent" if r.status_code in (200, 201) else "error",
                    "http": r.status_code,
                    "to": body.to,
                    "subject": subject,
                    "body_chars": len(text),
                    "detail": r.text[:200] if r.status_code not in (200, 201) else "ok"}
            if pdf_b64:
                resp["pdf_filename"] = pdf_filename
                resp["pdf_size_bytes"] = pdf_size_bytes
                resp["pdf_base64"] = pdf_b64
            elif pdf_skipped_reason:
                resp["pdf_skipped_reason"] = pdf_skipped_reason
            return resp
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "http": 0, "detail": f"{e!r}", "to": body.to}

    # -----------------------------------------------------------------
    # Phase 1: payment-link lifecycle drills + the smart orchestrator.
    #
    # Razorpay's sandbox will not move a payment link from `created` to
    # `paid` without a real customer payment, so a live demo needs a
    # deterministic way to drive the rest of the lifecycle. These five
    # routes do it through the SAME ingest path a real webhook takes
    # (HMAC-signed body -> process_delivery -> queue -> worker), so
    # neither the audit chain nor the journey FSM is special-cased.
    #
    # What is genuinely live vs. locally driven:
    #   force-paid    -> Cadence closes RECOVERED; the Razorpay link stays
    #                    `created` (no API exists to mark a link paid). The
    #                    response carries the real fetched Razorpay status.
    #   force-failed  -> a real payment.failed shape is ingested; the
    #                    Razorpay link is untouched (it waits for retry).
    #   force-expired -> a REAL Razorpay POST /payment_links/{id}/cancel;
    #                    the link really does flip to `cancelled` upstream.
    # -----------------------------------------------------------------
    _LC_FALLBACK_SECRET = "cadence-lifecycle-local"

    def _lc_secret() -> str:
        cfg = runtime.config.razorpay if runtime and runtime.config else None
        return (getattr(cfg, "webhook_secret", "") or "") or _LC_FALLBACK_SECRET

    def _lc_ingest(body_dict: dict) -> tuple[int, dict]:
        """Sign + ingest a webhook body through the real gateway.

        Signed with the configured webhook secret when one exists and with
        a local fallback otherwise. Because we sign and verify with the
        same secret, the keyless path still exercises the real HMAC check
        rather than skipping verification.
        """
        from cadence.ingest.gateway import process_delivery
        secret = _lc_secret()
        raw = json.dumps(body_dict).encode("utf-8")
        signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        return process_delivery(
            db=db, webhook_secret=secret, clock=runtime.clock,
            raw=raw, signature=signature, event_id=body_dict["id"],
        )

    def _lc_tick(max_tasks: int = 12) -> None:
        """Drain the queue once so the SPA sees the new state on its next
        poll instead of waiting up to 2s for the background worker."""
        worker = getattr(runtime, "worker", None)
        handlers = getattr(runtime, "handlers", None)
        if worker is None or handlers is None:
            return
        try:
            worker.run_once(handlers, max_tasks=max_tasks)
        except Exception:  # noqa: BLE001
            log.exception("lifecycle: post-ingest worker tick failed")

    def _lc_plink_for(journey) -> dict | None:
        """The most recent Razorpay payment link recorded for a journey.

        Reads the hash chain rather than a side table: the dispatcher and
        /api/live/failure both emit action.executed{kind=PAYMENT_LINK}
        carrying payment_link_id + short_url.
        """
        es = runtime.store
        for aggregate_id in (journey.journey_id, journey.subscription_id):
            events = sorted(es.get_by_aggregate("journey", aggregate_id), key=lambda e: e.seq)
            for ev in reversed(events):
                payload = ev.payload or {}
                if ev.type != "action.executed" or payload.get("kind") != "PAYMENT_LINK":
                    continue
                plink_id = (
                    payload.get("payment_link_id")
                    or payload.get("plink_id")
                    or payload.get("ref")
                )
                if not plink_id:
                    continue
                return {
                    "id": str(plink_id),
                    "short_url": str(payload.get("short_url") or ""),
                    "reference_id": str(
                        payload.get("reference_id") or f"{journey.journey_id}:1"
                    ),
                    "amount_minor": int(
                        payload.get("amount_minor") or journey.amount_minor or 49900
                    ),
                }
        return None

    def _lc_resolve(reference_id: str):
        """'j_xxx:1' -> (journey, plink|None, error_detail|None)."""
        if ":" not in reference_id:
            return None, None, "reference_id must be '{journey_id}:{attempt_no}'"
        journey_id, _, _ = reference_id.rpartition(":")
        journey = runtime.journeys.get(journey_id)
        if journey is None:
            return None, None, f"unknown journey {journey_id}"
        return journey, _lc_plink_for(journey), None

    def _lc_require(reference_id: str):
        """_lc_resolve, but raises the HTTP errors the SPA expects."""
        journey, plink, err = _lc_resolve(reference_id)
        if err:
            raise HTTPException(status_code=404, detail=err)
        if plink is None:
            raise HTTPException(
                status_code=409,
                detail=f"no payment link recorded on journey {journey.journey_id}; "
                       "run /api/live/failure first",
            )
        return journey, plink

    def _lc_state(journey_id: str) -> str:
        j = runtime.journeys.get(journey_id)
        return j.state if j is not None else "unknown"

    def _lc_razorpay_status(plink_id: str) -> str:
        """Razorpay's own view of the link. Never raises: a transport
        error must not fail the drill, it just means 'unknown'."""
        cli = getattr(runtime, "client", None)
        if cli is None or not hasattr(cli, "fetch_payment_link"):
            return "unknown"
        try:
            return str(cli.fetch_payment_link(payment_link_id=plink_id).get("status") or "unknown")
        except Exception as exc:  # noqa: BLE001
            log.info("lifecycle: fetch_payment_link(%s) failed: %r", plink_id, exc)
            return "unknown"

    def _lc_record(
        *, journey, plink: dict, to_status: str, source: str,
        detail: dict | None = None,
    ) -> None:
        """Append the lifecycle transition to the hash chain, then mirror it
        to Supabase. The mirror is best-effort: a cloud outage must never
        fail a drill or break the audit chain."""
        now = utc_iso(datetime.now(timezone.utc))
        payload = {
            "plink_id": plink["id"],
            "payment_link_id": plink["id"],
            "journey_id": journey.journey_id,
            "subscription_id": journey.subscription_id,
            "customer_id": journey.customer_id,
            "amount_minor": plink.get("amount_minor") or journey.amount_minor or 0,
            "currency": journey.currency or "INR",
            "short_url": plink.get("short_url") or "",
            "reference_id": plink.get("reference_id") or "",
            "to_status": to_status,
            "source": source,
        }
        if detail:
            payload["detail"] = detail
        runtime.store.append(
            event_type="plink.lifecycle", aggregate_type="journey",
            aggregate_id=journey.journey_id, payload=payload,
            occurred_at=now, recorded_at=now,
            event_id=f"lc_{uuid.uuid4().hex[:12]}",
        )
        try:
            from cadence.cloud.plink_mirror import get_plink_mirror
            get_plink_mirror(runtime.config).record_lifecycle_event(
                plink_id=plink["id"], event_type=source,
                status=to_status, payload=payload,
            )
        except Exception as exc:  # noqa: BLE001
            log.info("plink mirror skipped (%s -> %s): %r", plink["id"], to_status, exc)

    @router.post("/api/live/lifecycle/force-paid")
    def lifecycle_force_paid(body: LiveLifecycleForceIn) -> dict:
        """Drill: the customer pays the link.

        Ingests a real-shaped `payment_link.paid` webhook for the journey's
        actual plink id, drains the queue once, and reports both Cadence's
        state and Razorpay's own (unchanged) link status.
        """
        journey, plink = _lc_require(body.reference_id)
        # Idempotent: a second click on an already-recovered journey must not
        # append another 'paid' transition (it would clutter the Dashboard's
        # lifecycle trail and re-run the capture path for nothing).
        if journey.state == "RECOVERED":
            return {
                "status": "ok",
                "http": 200,
                "ingest": "already_recovered",
                "already": True,
                "journey_id": journey.journey_id,
                "plink_id": plink["id"],
                "short_url": plink["short_url"],
                "plink_state": "paid",
                "cadence_state": journey.state,
                "razorpay_state": _lc_razorpay_status(plink["id"]),
                "razorpay_note": "journey was already closed RECOVERED; nothing to do.",
            }
        amount_minor = plink["amount_minor"]
        payment_id = f"pay_lc_{uuid.uuid4().hex[:12]}"
        event_id = f"evt_lc_paid_{uuid.uuid4().hex[:10]}"
        status, body_out = _lc_ingest({
            "id": event_id,
            "event": "payment_link.paid",
            "payload": {
                "payment_link": {"entity": {
                    "id": plink["id"],
                    "reference_id": body.reference_id,
                    "status": "paid",
                    "amount": amount_minor,
                    "amount_paid": amount_minor,
                }},
                "payment": {"entity": {
                    "id": payment_id,
                    "amount": amount_minor,
                    "currency": journey.currency or "INR",
                    "status": "captured",
                }},
            },
        })
        _lc_tick()
        _lc_record(
            journey=journey, plink=plink, to_status="paid",
            source="lifecycle.force_paid",
            detail={"payment_id": payment_id, "ingest_http": status},
        )
        return {
            "status": "ok",
            "http": status,
            "ingest": body_out.get("status", "unknown"),
            "journey_id": journey.journey_id,
            "plink_id": plink["id"],
            "short_url": plink["short_url"],
            "payment_id_used": payment_id,
            "plink_state": "paid",
            "cadence_state": _lc_state(journey.journey_id),
            "razorpay_state": _lc_razorpay_status(plink["id"]),
            "razorpay_note": (
                "Razorpay exposes no API to mark a link paid; upstream status "
                "only flips when a customer actually pays the short_url."
            ),
        }

    @router.post("/api/live/lifecycle/force-failed")
    def lifecycle_force_failed(body: LiveLifecycleForceIn) -> dict:
        """Drill: another debit attempt fails on the same journey.

        Razorpay leaves the link `created` (it waits for a retry); Cadence
        re-enters the recovery loop, and the 9-rule Guardian still applies.
        """
        journey, plink = _lc_require(body.reference_id)
        amount_minor = plink["amount_minor"]
        event_id = f"evt_lc_failed_{uuid.uuid4().hex[:10]}"
        status, body_out = _lc_ingest({
            "id": event_id,
            "event": "payment.failed",
            "payload": {
                "subscription": {"entity": {
                    "id": journey.subscription_id,
                    "customer_id": journey.customer_id,
                }},
                "payment": {"entity": {
                    "id": f"pay_lc_fail_{uuid.uuid4().hex[:10]}",
                    "amount": amount_minor,
                    "currency": journey.currency or "INR",
                    "error_code": "insufficient_funds",
                    "error_description": "Lifecycle drill: forced failure",
                }},
            },
        })
        _lc_tick()
        _lc_record(
            journey=journey, plink=plink, to_status="failed_attempt",
            source="lifecycle.force_failed",
            detail={"error_code": "insufficient_funds", "ingest_http": status},
        )
        return {
            "status": "ok",
            "http": status,
            "ingest": body_out.get("status", "unknown"),
            "journey_id": journey.journey_id,
            "plink_id": plink["id"],
            "short_url": plink["short_url"],
            "plink_state": "created",
            "cadence_state": _lc_state(journey.journey_id),
            "razorpay_state": _lc_razorpay_status(plink["id"]),
            "razorpay_note": "a failed debit does not change the link; it stays payable.",
        }

    @router.post("/api/live/lifecycle/force-expired")
    def lifecycle_force_expired(body: LiveLifecycleForceIn) -> dict:
        """Drill: the 24-hour mandate window closes unrecovered.

        This one is fully live: POST /v1/payment_links/{id}/cancel really
        does move the link to `cancelled` on Razorpay (the sandbox has no
        explicit 'expire' endpoint). Cadence closes the journey
        CLOSED_UNRECOVERED.
        """
        journey, plink = _lc_require(body.reference_id)
        cancelled = False
        cancel_detail = "razorpay client unavailable (simulated path)"
        cli = getattr(runtime, "client", None)
        if cli is not None and hasattr(cli, "cancel_payment_link"):
            try:
                cli.cancel_payment_link(payment_link_id=plink["id"])
                cancelled = True
                cancel_detail = "razorpay cancel accepted"
            except Exception as exc:  # noqa: BLE001
                cancel_detail = f"razorpay cancel failed: {exc!r}"
                log.info("lifecycle force_expired cancel failed: %r", exc)
        now = utc_iso(datetime.now(timezone.utc))
        previous_state = journey.state
        if previous_state != "CLOSED_UNRECOVERED":
            runtime.journeys.update_fields(
                journey.journey_id,
                {"state": "CLOSED_UNRECOVERED", "closed_at": now},
                updated_at=now,
            )
            runtime.store.append(
                event_type="journey.closed", aggregate_type="journey",
                aggregate_id=journey.journey_id,
                payload={
                    "from": previous_state, "to": "CLOSED_UNRECOVERED",
                    "reason": "lifecycle drill: mandate window closed unrecovered",
                    "plink_id": plink["id"],
                },
                occurred_at=now, recorded_at=now,
                event_id=f"evt_lc_exp_{uuid.uuid4().hex[:10]}",
            )
        _lc_record(
            journey=journey, plink=plink, to_status="expired",
            source="lifecycle.force_expired",
            detail={"razorpay_cancelled": cancelled, "cancel_detail": cancel_detail},
        )
        return {
            "status": "ok",
            "journey_id": journey.journey_id,
            "plink_id": plink["id"],
            "short_url": plink["short_url"],
            "plink_state": "expired",
            "cadence_state": _lc_state(journey.journey_id),
            "razorpay_state": _lc_razorpay_status(plink["id"]),
            "razorpay_cancelled": cancelled,
            "razorpay_note": cancel_detail,
        }

    @router.post("/api/live/lifecycle/complete-journey")
    def lifecycle_complete_journey(body: LiveLifecycleForceIn) -> dict:
        """One-click close-the-loop: paid + audit + state, in one call."""
        out = lifecycle_force_paid(body)
        out["label"] = "journey completed (link paid, journey closed RECOVERED)"
        return out

    @router.post("/api/live/lifecycle/smart")
    def lifecycle_smart(body: LiveLifecycleSmartIn) -> dict:
        """Autonomous orchestrator: hand it a link, it decides the outcome.

        The LLM reasons over (1) the operator's customer hint, (2) Razorpay's
        live link status, (3) the journey's own audit chain, and (4) the
        Guardian's hard constraints, then dispatches the matching drill. The
        reasoning lands in the hash chain as an agent.thinking event, so the
        decision is auditable even when the LLM is unavailable.
        """
        import os as _os
        journey, plink = _lc_require(body.reference_id)
        es = runtime.store
        chain: list[dict] = []
        keep = ("kind", "status", "to_status", "error_code", "amount_minor",
                "arm_chosen", "guard_decision", "intervention", "source")
        for aggregate_id in (journey.journey_id, journey.subscription_id):
            for ev in sorted(es.get_by_aggregate("journey", aggregate_id), key=lambda e: e.seq):
                chain.append({
                    "type": ev.type,
                    "ts": ev.occurred_at,
                    "summary": {k: v for k, v in (ev.payload or {}).items() if k in keep},
                })
        chain = chain[-15:]
        razorpay_status = _lc_razorpay_status(plink["id"])
        journey_view = {
            "journey_id": journey.journey_id,
            "state": journey.state,
            "failure_code": journey.failure_code,
            "root_cause": journey.root_cause,
            "amount_minor": journey.amount_minor,
            "attempts_used": journey.attempts_used,
            "touches_used": journey.touches_used,
        }

        chosen = {
            "outcome": "paid",
            "confidence": 0.5,
            "reason": "no LLM configured; defaulting to the most common outcome (paid)",
        }
        llm_thought = (
            "GROQ_API_KEY is not set, so the orchestrator fell back to its "
            "default arm (paid). Set GROQ_API_KEY in .env to enable reasoning."
        )
        # Read the key off the injected config (env only as a last resort), so
        # a test or a keyless run that blanks the LLM config really does take
        # the deterministic default arm.
        llm_cfg = getattr(runtime.config, "llm", None) if runtime.config else None
        if llm_cfg is not None:
            groq_key = getattr(llm_cfg, "groq_api_key", "") or ""
            groq_model = getattr(llm_cfg, "model_groq", "") or "llama-3.3-70b-versatile"
        else:
            groq_key = _os.environ.get("GROQ_API_KEY", "")
            groq_model = _os.environ.get("LLM_MODEL_GROQ", "llama-3.3-70b-versatile")
        if groq_key:
            import httpx as _httpx
            prompt = (
                "You are Cadence, an autonomous Indian payment-recovery agent. "
                "Given a Razorpay payment link, its journey's audit events, and an "
                "operator hint, decide the most likely next outcome (paid / failed / "
                "expired) and explain it in 2-3 sentences. Respect the Guardian: "
                "NPCI 18-h UPI cooling, RBI 24-h pre-debit notice, 21:00-09:00 IST "
                "quiet hours, hard-decline stop, touch-cap 3 per 14 days.\n\n"
                f"Journey: {json.dumps(journey_view, default=str)}\n\n"
                f"Payment link: {json.dumps({**plink, 'razorpay_status': razorpay_status}, default=str)}\n\n"
                f"Operator hint: {body.customer_hint or '(none)'}\n\n"
                f"Audit chain (last 15 events): {json.dumps(chain, default=str)}\n\n"
                'Return JSON: {"outcome": "paid|failed|expired", '
                '"confidence": 0.0-1.0, "reason": "..."}'
            )
            try:
                r = _httpx.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}",
                             "Content-Type": "application/json"},
                    json={
                        "model": groq_model,
                        "messages": [
                            {"role": "system", "content":
                             "You are a payment-recovery agent. Always return valid JSON."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 260,
                        "response_format": {"type": "json_object"},
                    },
                    timeout=float(max(body.timeout_seconds, 5)),
                )
                if r.status_code == 200:
                    text = r.json()["choices"][0]["message"]["content"]
                    llm_thought = text[:600]
                    parsed = json.loads(text)
                    outcome = str(parsed.get("outcome", "paid")).strip().lower()
                    if outcome not in ("paid", "failed", "expired"):
                        outcome = "paid"
                    chosen = {
                        "outcome": outcome,
                        "confidence": float(parsed.get("confidence", 0.5)),
                        "reason": str(parsed.get("reason") or "(no reason given)"),
                    }
                else:
                    llm_thought = f"LLM call failed: HTTP {r.status_code} {r.text[:200]}"
            except Exception as exc:  # noqa: BLE001
                llm_thought = f"LLM call error: {exc!r}"

        now = utc_iso(datetime.now(timezone.utc))
        es.append(
            event_type="agent.thinking", aggregate_type="journey",
            aggregate_id=journey.journey_id,
            payload={
                "agent": "lifecycle_smart",
                "chosen_outcome": chosen["outcome"],
                "confidence": chosen["confidence"],
                "reason": chosen["reason"],
                "customer_hint": body.customer_hint,
                "razorpay_status": razorpay_status,
                "llm_thought": llm_thought,
                "llm_used": bool(groq_key),
            },
            occurred_at=now, recorded_at=now,
            event_id=f"evt_lc_smart_{uuid.uuid4().hex[:10]}",
        )

        forced = LiveLifecycleForceIn(reference_id=body.reference_id)
        if chosen["outcome"] == "paid":
            dispatched = lifecycle_force_paid(forced)
            label = "smart: closed the loop (link paid)"
        elif chosen["outcome"] == "failed":
            dispatched = lifecycle_force_failed(forced)
            label = "smart: re-entered recovery (debit failed again)"
        else:
            dispatched = lifecycle_force_expired(forced)
            label = "smart: closed unrecovered (24-h window expired)"
        return {
            "status": "ok",
            "label": label,
            "chosen": chosen,
            "llm_used": bool(groq_key),
            "llm_thought": llm_thought,
            "journey_id": journey.journey_id,
            "plink_id": plink["id"],
            "cadence_state": _lc_state(journey.journey_id),
            "dispatched": dispatched,
        }

    return router
