// B2B receivables view (SPA).
//
// Shows recent B2B invoices and the chaser's overdue-by-age bucket.
// The user can:
//   - create a new invoice (POST /api/b2b/invoice/create)
//   - manually trigger a chase (POST /api/b2b/invoice/{id}/chase)
//   - run the chaser across all overdue (POST /api/b2b/tick)
//   - see the funnel counts (GET /api/b2b/funnel)

import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, Badge, Button, PageHeader, EmptyState } from '../components/primitives';
import { api } from '../services/api';
import { Briefcase, Play, Plus } from 'lucide-react';
import { DemoSeedBadge } from '../components/DemoSeedBadge';

interface B2BInvoice {
  id: string;
  invoice_number: string | null;
  org_id: string;
  contact_email: string | null;
  amount_minor: number;
  currency: string;
  issued_at: string;
  due_date: string;
  paid_at: string | null;
  status: string;
  chases_sent: number;
  last_chase_at: string | null;
  last_chase_action: string | null;
  escalated_to_manager: number;
  writeoff_at: string | null;
}

const ACTION_COLOR: Record<string, string> = {
  pre_due_reminder: 'var(--color-info)',
  friendly_nudge: 'var(--color-info)',
  firmer_nudge: 'var(--color-pending)',
  escalate_to_manager: 'var(--color-pending)',
  written_notice: 'var(--color-rejected)',
  writeoff: 'var(--color-rejected)',
};

export const B2BView: React.FC = () => {
  const [invoices, setInvoices] = useState<B2BInvoice[]>([]);
  const [funnel, setFunnel] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fetch = useCallback(async () => {
    try {
      const [inv, f] = await Promise.all([
        api.getB2BInvoices(null, 50),
        api.getB2BFunnel(),
      ]);
      setInvoices(inv);
      setFunnel(f.counts);
      setError(null);
    } catch (e: any) {
      setError(e?.message ?? 'failed to load B2B invoices');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch();
    const interval = setInterval(fetch, 4000);
    return () => clearInterval(interval);
  }, [fetch]);

  const createOne = async () => {
    setBusy(true);
    try {
      await api.createB2BInvoice({
        org_id: `org_demo_${Date.now()}`,
        contact_email: 'ar@demo.test',
        amount_minor: 1250000 + Math.floor(Math.random() * 5000000),
        currency: 'INR',
        // Due date = 7 days ago so it shows up overdue immediately
        due_date: new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString(),
      });
      await fetch();
    } catch (e: any) {
      setError(e?.message ?? 'failed to create');
    } finally {
      setBusy(false);
    }
  };

  const runTick = async () => {
    setBusy(true);
    try {
      await api.tickB2B();
      await fetch();
    } catch (e: any) {
      setError(e?.message ?? 'failed to run chaser');
    } finally {
      setBusy(false);
    }
  };

  const chaseOne = async (id: string) => {
    setBusy(true);
    try {
      await api.chaseB2BInvoice(id);
      await fetch();
    } catch (e: any) {
      setError(e?.message ?? 'failed to chase');
    } finally {
      setBusy(false);
    }
  };

  if (loading && invoices.length === 0) {
    return (
      <EmptyState
        title="Waiting for the B2B chaser to fire..."
        description="Click 'Create overdue invoice' to add a new invoice that the chaser will pick up on the next tick."
      />
    );
  }
  if (error) {
    return <EmptyState title="B2B feed unavailable" description={error} />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="B2B Receivables Chaser"
        description="Razorpay invoice API. The chaser runs a 5-rung ladder: pre-due reminder (T-3) -> friendly nudge (T+3) -> firmer nudge with UPI deep-link (T+7) -> escalate to manager (T+14) -> written notice (T+21) -> write-off (T+45). Respects quiet hours; each chase is auditable."
        action={
          <div className="flex gap-2 items-center">
            <DemoSeedBadge />
            <Button onClick={createOne} disabled={busy} variant="secondary">
              <Plus size={14} className="inline-block mr-1" />
              Create overdue invoice
            </Button>
            <Button onClick={runTick} disabled={busy} variant="primary">
              <Play size={14} className="inline-block mr-1" />
              Run chaser tick
            </Button>
          </div>
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {(['issued', 'paid', 'cancelled', 'in_dispute'] as const).map((status) => (
          <Card key={status} className="p-4 text-center">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-ink-subtle)]">
              {status.replace('_', ' ')}
            </div>
            <div className="text-2xl font-semibold mt-1 font-mono">{funnel[status] ?? 0}</div>
          </Card>
        ))}
      </div>

      <Card className="p-0 overflow-hidden">
        <CardHeader
          title="Invoices (overdue first)"
          subtitle="The follow-up ladder stops at 'in_dispute' and at 'paid'. The last action column shows the most recent follow-up."
        />
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-[var(--color-ink-muted)]">
                <th className="font-semibold py-2 px-3">Invoice</th>
                <th className="font-semibold py-2 px-3">Org</th>
                <th className="font-semibold py-2 px-3 text-right">Amount</th>
                <th className="font-semibold py-2 px-3">Due</th>
                <th className="font-semibold py-2 px-3">Status</th>
                <th className="font-semibold py-2 px-3 text-right">Follow-up messages</th>
                <th className="font-semibold py-2 px-3">Last follow-up sent</th>
                <th className="font-semibold py-2 px-3 text-right">What we'll do next</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => (
                <tr key={inv.id} className="border-t border-[var(--color-line)]">
                  <td className="py-2 px-3 font-mono">{inv.id}</td>
                  <td className="py-2 px-3 font-mono text-[var(--color-ink-muted)]">{inv.org_id}</td>
                  <td className="py-2 px-3 text-right font-mono">
                    &#8377;{(inv.amount_minor / 100).toFixed(2)}
                  </td>
                  <td className="py-2 px-3 text-[var(--color-ink-muted)] font-mono text-[12px]">
                    {inv.due_date.split('T')[0]}
                  </td>
                  <td className="py-2 px-3">
                    <Badge tone={inv.status === 'paid' ? 'approved' : 'info'}>{inv.status}</Badge>
                  </td>
                  <td className="py-2 px-3 text-right font-mono">{inv.chases_sent}</td>
                  <td className="py-2 px-3">
                    {inv.last_chase_action && (
                      <span
                        className="text-[12px] font-mono font-semibold"
                        style={{ color: ACTION_COLOR[inv.last_chase_action] || 'var(--color-ink-muted)' }}
                      >
                        {inv.last_chase_action.replace(/_/g, ' ')}
                      </span>
                    )}
                  </td>
                  <td className="py-2 px-3 text-right">
                    {inv.status === 'issued' && (
                      <button
                        onClick={() => chaseOne(inv.id)}
                        disabled={busy}
                        className="text-[12px] text-[var(--color-accent)] font-semibold hover:underline disabled:opacity-50"
                      >
                        Send follow-up now
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
};
