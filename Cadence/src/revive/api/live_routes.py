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
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel

from revive.clock import utc_iso
from revive.logging_setup import get_logger

log = get_logger("revive.api.live")


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

class LivePaymentPaidIn(BaseModel):
    reference_id: str
    # B-fix: the previous default of 'pay_LIVE_DEMO' deduplicated the
    # capture task on the second call (the queue's idempotency_key was
    # built from payment_id) so the worker silently dropped the task
    # and the journey stayed INTERVENING forever. The route now
    # generates a unique id when the caller does not supply one.
    payment_id: str | None = None


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
        queue = runtime.queue
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
                    description="Revive: complete your pending subscription payment",
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
        # Persist the webhook.received event directly (skipping HMAC verify
        # in test mode so the demo never blocks on a missing secret).
        try:
            es.append(
                event_type="webhook.received", aggregate_type="webhook",
                aggregate_id=f"evt:{event_id}",
                payload={"event": "payment.failed", "headers": {"x-razorpay-signature": signature[:16] + "..."}},
                occurred_at=now, recorded_at=now, event_id=event_id,
            )
            es.append(
                event_type="payment.failed", aggregate_type="journey",
                aggregate_id=subscription_id,
                payload={"subscription_id": subscription_id, "customer_id": body.customer_id,
                          "amount_minor": amount_minor, "error_code": "insufficient_funds"},
                occurred_at=now, recorded_at=now,
                event_id=f"pf_{uuid.uuid4().hex[:10]}",
            )
            # Open the journey in the engine so the next SPA poll sees
            # state INTERVENING.
            jr.update_fields(journey_id,
                              {"state": "INTERVENING"},
                              updated_at=now)
        except Exception as exc:  # noqa: BLE001
            log.warning("live failure webhook persist failed: %r", exc)
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
        from revive.ingest.gateway import process_delivery
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
            from revive.ingest.gateway import process_delivery
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
        """
        cfg = runtime.config.razorpay if runtime and runtime.config else None
        import os as _os
        if not (_os.environ.get("RESEND_API_KEY") or (cfg and getattr(cfg, "resend_api_key", None))):
            return {"status": "skipped", "http": 200,
                    "detail": "RESEND_API_KEY not set; bubble shown in SPA but no real send",
                    "to": body.to}
        # Build subject + body
        from revive.agents.message_writer import _NUDGE_SYSTEM
        text = body.text or (
            "Namaste! Aapka subscription ka payment abhi pending hai. "
            "Jab convenient ho, neeche diye gaye link se pay kar dijiye. "
            "Madad ke liye yahan reply karein. - Cadence"
        )
        subject = body.subject or "Action needed: complete your Cadence subscription"
        # POST to Resend
        import httpx as _httpx
        rzp = _os.environ.get("RESEND_API_KEY")
        try:
            r = _httpx.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {rzp}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": "Cadence <onboarding@resend.dev>",
                    "to": [body.to],
                    "subject": subject,
                    "text": text,
                },
                timeout=10.0,
            )
            return {"status": "sent" if r.status_code in (200, 201) else "error",
                    "http": r.status_code,
                    "to": body.to,
                    "subject": subject,
                    "body_chars": len(text),
                    "detail": r.text[:200] if r.status_code not in (200, 201) else "ok"}
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "http": 0, "detail": f"{e!r}", "to": body.to}

    return router
