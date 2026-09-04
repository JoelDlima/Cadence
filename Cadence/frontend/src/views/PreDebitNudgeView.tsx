// PreDebitNudgeView: proof surface for the preventive pre-debit nudge workflow.
//
// This is the PROACTIVE counterpart to Live Recovery (which is reactive — it
// responds to a failure). Here the operator schedules a nudge that fires BEFORE
// an upcoming AutoPay debit — the RBI 24h pre-debit notification — and the panel
// shows the two distinct audit events the backend appends:
//   • predebit.scheduled  (the intent, always recorded)
//   • predebit.notified   (the notice went out) OR intervention.vetoed
//                         (suppressed by the kill switch or quiet hours)
//
// It calls POST /api/predebit/schedule, a test-safe path that appends events
// only and never touches Razorpay.

import React, { useState, useCallback } from 'react';
import {
  Card, CardHeader, Badge, Button, PageHeader, Input,
} from '../components/primitives';
import { api } from '../services/api';
import { BellRing, ShieldAlert, CheckCircle2, Clock4 } from 'lucide-react';

interface ScheduleResult {
  subscription_id: string;
  notified: boolean;
  reason: string;
  channel: string;
  debit_at: string;
  scheduled_event: boolean;
  notified_event: boolean;
  ref: string | null;
}

// A default debit time 24h out, rendered as an ISO string the backend accepts.
const defaultDebitAt = (): string => {
  const d = new Date(Date.now() + 24 * 60 * 60 * 1000);
  return d.toISOString();
};

export const PreDebitNudgeView: React.FC = () => {
  const [subId, setSubId] = useState('sub_predebit_demo');
  const [custId, setCustId] = useState('cust_predebit_demo');
  const [amount, setAmount] = useState('49900');
  const [debitAt, setDebitAt] = useState(defaultDebitAt());
  const [channel, setChannel] = useState('whatsapp');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ScheduleResult | null>(null);

  const schedule = useCallback(async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.schedulePreDebitNudge({
        subscription_id: subId,
        customer_id: custId,
        amount_minor: Number(amount) || 0,
        debit_at: debitAt,
        channel,
      });
      setResult(res);
    } catch (e: any) {
      setError(e?.message ?? 'schedule request failed');
    } finally {
      setBusy(false);
    }
  }, [subId, custId, amount, debitAt, channel]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Pre-Debit Nudge"
        description="Proactive workflow: notify a customer BEFORE a scheduled AutoPay debit (the RBI 24h pre-debit notice). The Guardian still applies — the kill switch and 21:00-09:00 IST quiet hours suppress the notice and record why."
        action={<Badge tone="info">Preventive</Badge>}
      />

      <Card>
        <CardHeader
          title="Schedule a pre-debit nudge"
          subtitle="Appends predebit.scheduled, runs the contact guardrails, then appends predebit.notified (or intervention.vetoed). Test-safe: audit events only, no Razorpay call."
          action={<BellRing size={16} className="text-[var(--color-ink-muted)]" />}
        />
        <div className="p-5 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="text-[13px] text-[var(--color-ink-muted)]">
              <div className="mb-1">Subscription ID</div>
              <Input value={subId} onChange={(e) => setSubId(e.target.value)} className="text-[14px]" />
            </label>
            <label className="text-[13px] text-[var(--color-ink-muted)]">
              <div className="mb-1">Customer ID</div>
              <Input value={custId} onChange={(e) => setCustId(e.target.value)} className="text-[14px]" />
            </label>
            <label className="text-[13px] text-[var(--color-ink-muted)]">
              <div className="mb-1">Amount (minor, paise)</div>
              <Input value={amount} onChange={(e) => setAmount(e.target.value)} className="numeric text-[14px]" />
            </label>
            <label className="text-[13px] text-[var(--color-ink-muted)]">
              <div className="mb-1">Channel</div>
              <select
                value={channel}
                onChange={(e) => setChannel(e.target.value)}
                className="w-full border border-[var(--color-line)] rounded px-2 py-1.5 text-[14px] bg-[var(--color-paper)]"
              >
                <option value="whatsapp">whatsapp</option>
                <option value="email">email</option>
              </select>
            </label>
            <label className="text-[13px] text-[var(--color-ink-muted)] sm:col-span-2">
              <div className="mb-1">Scheduled debit at (ISO 8601)</div>
              <Input value={debitAt} onChange={(e) => setDebitAt(e.target.value)} className="numeric text-[14px]" />
            </label>
          </div>
          <Button onClick={schedule} disabled={busy} variant="primary" size="sm">
            {busy ? 'Scheduling…' : 'Schedule pre-debit nudge'}
          </Button>
          {error && (
            <div className="text-[12.5px] text-[var(--color-coral)] font-mono">{error}</div>
          )}
        </div>
      </Card>

      {result && (
        <Card>
          <CardHeader
            title="Outcome"
            subtitle={`subscription ${result.subscription_id} · channel ${result.channel}`}
            action={
              result.notified ? (
                <Badge tone="approved">Notified</Badge>
              ) : (
                <Badge tone="rejected">Suppressed</Badge>
              )
            }
          />
          <div className="p-5 space-y-3 text-[13px]">
            <div className="flex items-center gap-2">
              {result.notified ? (
                <CheckCircle2 size={15} className="text-[var(--color-approved)]" />
              ) : (
                <ShieldAlert size={15} className="text-[var(--color-rejected)]" />
              )}
              <span className="font-mono">
                notified={String(result.notified)} · reason={result.reason}
                {result.ref ? ` · ref=${result.ref}` : ''}
              </span>
            </div>

            {/* The two distinct events, shown as proof. */}
            <div className="space-y-2">
              <div className="text-[10px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold">
                Audit events appended
              </div>
              <EventRow
                ok={result.scheduled_event}
                type="predebit.scheduled"
                note="the intent to notify ahead of the debit (always recorded)"
              />
              {result.notified_event ? (
                <EventRow
                  ok
                  type="predebit.notified"
                  note={`notice sent via ${result.channel} for debit at ${result.debit_at}`}
                />
              ) : (
                <EventRow
                  ok={false}
                  type="intervention.vetoed"
                  note={`suppressed — ${result.reason} (kill switch or quiet hours)`}
                  icon={<Clock4 size={13} className="text-[var(--color-rejected)]" />}
                />
              )}
            </div>
          </div>
        </Card>
      )}
    </div>
  );
};

const EventRow: React.FC<{
  ok: boolean;
  type: string;
  note: string;
  icon?: React.ReactNode;
}> = ({ ok, type, note, icon }) => (
  <div
    className="p-2.5 rounded border text-[12px] font-mono flex items-start gap-2"
    style={{
      backgroundColor: ok ? 'var(--color-approved-wash)' : 'var(--color-rejected-wash)',
      borderColor: ok ? 'var(--color-approved)' : 'var(--color-rejected)',
      color: ok ? 'var(--color-approved)' : 'var(--color-rejected)',
    }}
  >
    {icon ?? (ok ? <CheckCircle2 size={13} /> : <ShieldAlert size={13} />)}
    <span>
      <strong>{type}</strong> · {note}
    </span>
  </div>
);

export default PreDebitNudgeView;
