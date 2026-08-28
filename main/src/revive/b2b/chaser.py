"""B2B receivables chaser.

A different customer type than the consumer recovery path: an org,
a contact, an invoice with terms, a chaser ladder that escalates.
The chaser reuses the same Guardian rules and the same Adaptive
Recovery Brain for picking the *content* of each chase; this
module only decides the *cadence* and the *escalation level*.

The chaser ladder is:
  issued  -> nothing (still within terms)
  due_soon (T-3 to T+0)  -> pre-due reminder (T-3)
  overdue_t3 (T+3)        -> friendly nudge
  overdue_t7 (T+7)        -> firmer nudge with UPI deep-link
  overdue_t14 (T+14)      -> escalation to manager
  overdue_t21 (T+21)      -> written notice (legal tone)
  overdue_t45 (T+45)      -> write-off
  paid, cancelled, in_dispute -> stop
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


STATUS_ISSUED = "issued"
STATUS_PAID = "paid"
STATUS_CANCELLED = "cancelled"
STATUS_EXPIRED = "expired"
STATUS_IN_DISPUTE = "in_dispute"

VALID_STATUSES = frozenset({
    STATUS_ISSUED, STATUS_PAID, STATUS_CANCELLED,
    STATUS_EXPIRED, STATUS_IN_DISPUTE,
})

# The chaser ladder thresholds (in days past due).
PRE_DUE_DAYS = -3       # 3 days before due date
T3_DAYS = 3
T7_DAYS = 7
T14_DAYS = 14
T21_DAYS = 21
T45_DAYS = 45

# Action labels for the audit chain.
ACTION_PRE_DUE = "pre_due_reminder"
ACTION_FRIENDLY = "friendly_nudge"
ACTION_FIRMER = "firmer_nudge"
ACTION_MANAGER = "escalate_to_manager"
ACTION_WRITTEN = "written_notice"
ACTION_WRITEOFF = "writeoff"
ACTION_NONE = "none"


@dataclass(frozen=True)
class Invoice:
    id: str
    org_id: str
    amount_minor: int
    due_date: datetime
    status: str
    chases_sent: int
    last_chase_at: datetime | None


@dataclass(frozen=True)
class ChaseDecision:
    next_status: str        # we never change the invoice status here; we record chases
    action: str             # one of the ACTION_* constants
    should_chase: bool
    channel: str            # 'email' or 'manager' or 'legal' or 'none'
    recipient: str          # contact_email or 'manager' or 'legal'
    days_past_due: int
    reason: str


def _days_past_due(due: datetime, now: datetime) -> int:
    return (now.date() - due.date()).days


def decide(invoice: Invoice, now: datetime) -> ChaseDecision:
    """Compute the next chase action for a B2B invoice.

    Pure function. The caller is responsible for reading the row,
    calling decide, and writing the chase state back.
    """
    if invoice.status in (STATUS_PAID, STATUS_CANCELLED):
        return ChaseDecision(
            next_status=invoice.status,
            action=ACTION_NONE,
            should_chase=False,
            channel="none",
            recipient="none",
            days_past_due=_days_past_due(invoice.due_date, now),
            reason=f"terminal status {invoice.status}",
        )

    if invoice.status == STATUS_IN_DISPUTE:
        return ChaseDecision(
            next_status=STATUS_IN_DISPUTE,
            action=ACTION_NONE,
            should_chase=False,
            channel="none",
            recipient="none",
            days_past_due=_days_past_due(invoice.due_date, now),
            reason="in_dispute — pause chases until resolved",
        )

    dpd = _days_past_due(invoice.due_date, now)

    # Pre-due reminder (T-3)
    if dpd < T3_DAYS and dpd >= PRE_DUE_DAYS and invoice.chases_sent == 0:
        return ChaseDecision(
            next_status=STATUS_ISSUED,
            action=ACTION_PRE_DUE,
            should_chase=True,
            channel="email",
            recipient="contact",
            days_past_due=dpd,
            reason=f"pre-due reminder (T-3, dpd={dpd})",
        )

    # Friendly nudge at T+3
    if T3_DAYS <= dpd < T7_DAYS and invoice.chases_sent <= 1:
        return ChaseDecision(
            next_status=STATUS_ISSUED,
            action=ACTION_FRIENDLY,
            should_chase=True,
            channel="email",
            recipient="contact",
            days_past_due=dpd,
            reason=f"friendly nudge (T+3, dpd={dpd})",
        )

    # Firmer nudge at T+7
    if T7_DAYS <= dpd < T14_DAYS and invoice.chases_sent <= 2:
        return ChaseDecision(
            next_status=STATUS_ISSUED,
            action=ACTION_FIRMER,
            should_chase=True,
            channel="email",
            recipient="contact",
            days_past_due=dpd,
            reason=f"firmer nudge with UPI link (T+7, dpd={dpd})",
        )

    # Escalate to manager at T+14
    if T14_DAYS <= dpd < T21_DAYS and invoice.chases_sent <= 3:
        return ChaseDecision(
            next_status=STATUS_ISSUED,
            action=ACTION_MANAGER,
            should_chase=True,
            channel="manager",
            recipient="manager",
            days_past_due=dpd,
            reason=f"escalate to manager (T+14, dpd={dpd})",
        )

    # Written notice at T+21
    if T21_DAYS <= dpd < T45_DAYS and invoice.chases_sent <= 4:
        return ChaseDecision(
            next_status=STATUS_ISSUED,
            action=ACTION_WRITTEN,
            should_chase=True,
            channel="legal",
            recipient="legal",
            days_past_due=dpd,
            reason=f"written notice (T+21, dpd={dpd})",
        )

    # Write-off at T+45
    if dpd >= T45_DAYS and invoice.chases_sent <= 5:
        return ChaseDecision(
            next_status=STATUS_ISSUED,
            action=ACTION_WRITEOFF,
            should_chase=True,
            channel="legal",
            recipient="finance",
            days_past_due=dpd,
            reason=f"write-off (T+45, dpd={dpd})",
        )

    # No action needed
    return ChaseDecision(
        next_status=invoice.status,
        action=ACTION_NONE,
        should_chase=False,
        channel="none",
        recipient="none",
        days_past_due=dpd,
        reason=f"no action needed (dpd={dpd}, chases={invoice.chases_sent})",
    )


__all__ = [
    "ACTION_FIRMER",
    "ACTION_FRIENDLY",
    "ACTION_MANAGER",
    "ACTION_NONE",
    "ACTION_PRE_DUE",
    "ACTION_WRITTEN",
    "ACTION_WRITEOFF",
    "ChaseDecision",
    "Invoice",
    "PRE_DUE_DAYS",
    "STATUS_CANCELLED",
    "STATUS_EXPIRED",
    "STATUS_IN_DISPUTE",
    "STATUS_ISSUED",
    "STATUS_PAID",
    "T14_DAYS",
    "T21_DAYS",
    "T3_DAYS",
    "T45_DAYS",
    "T7_DAYS",
    "VALID_STATUSES",
    "decide",
]
