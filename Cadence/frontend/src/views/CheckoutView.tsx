// Checkout drop-off recovery view (SPA).
//
// Shows recent abandoned checkout sessions and the chaser's funnel.
// The user can:
//   - simulate a new abandoned checkout (POST /api/checkout/abandon)
//   - run the chaser (POST /api/checkout/tick)
//   - mark a session recovered (POST /api/checkout/recover/{id})
//   - see the funnel counts (GET /api/checkout/funnel)

import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, Badge, Button, PageHeader, EmptyState } from '../components/primitives';
import { api } from '../services/api';
import { ShoppingCart, Play, RefreshCw, Sparkles, ExternalLink, CheckCircle2 } from 'lucide-react';
import { DemoSeedBadge } from '../components/DemoSeedBadge';

interface CheckoutSession {
  id: string;
  customer_id: string;
  amount_minor: number;
  currency: string;
  started_at: string;
  abandoned_at: string | null;
  last_nudge_at: string | null;
  nudges_sent: number;
  status: string;
  payment_link_id: string | null;
  payment_link_short_url: string | null;
  recovered_at: string | null;
  recovery_payment_id: string | null;
}

const STATUS_COLOR: Record<string, string> = {
  OPEN: 'var(--color-info)',
  ABANDONED: 'var(--color-pending)',
  NUDGED: 'var(--color-pending)',
  RECOVERED: 'var(--color-approved)',
  EXPIRED: 'var(--color-rejected)',
};

export const CheckoutView: React.FC = () => {
  const [sessions, setSessions] = useState<CheckoutSession[]>([]);
  const [funnel, setFunnel] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fetch = useCallback(async () => {
    try {
      const [s, f] = await Promise.all([
        api.getCheckoutSessions(50),
        api.getCheckoutFunnel(),
      ]);
      setSessions(s);
      setFunnel(f.counts);
      setError(null);
    } catch (e: any) {
      setError(e?.message ?? 'failed to load checkout sessions');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch();
    const interval = setInterval(fetch, 4000);
    return () => clearInterval(interval);
  }, [fetch]);

  const simulateAbandon = async () => {
    setBusy(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const amount = 19900 + Math.floor(Math.random() * 50000);
      const customer = `cust_demo_${Date.now().toString().slice(-4)}`;
      // Set started_at to 35 mins ago so the state machine detects it as abandoned (> 30 min)
      const startedAt = new Date(Date.now() - 35 * 60 * 1000).toISOString();
      await api.abandonCheckout({
        customer_id: customer,
        amount_minor: amount,
        currency: 'INR',
        started_at: startedAt,
      });
      await fetch();
      setSuccessMsg(`Ingested abandoned cart (₹${(amount / 100).toFixed(0)}). Click 'Run Recovery Agent' to evaluate the recovery nudge!`);
    } catch (e: any) {
      setError(e?.message ?? 'failed to simulate abandon');
    } finally {
      setBusy(false);
    }
  };

  const simulateShopifyAbandon = async () => {
    setBusy(true);
    setError(null);
    setSuccessMsg(null);
    try {
      // Real Burton Blossom Snowboard from verified Shopify UCP Global Catalog ($559.95 -> 46,400 INR)
      const amount = 4640000;
      const customer = `shopify_burton_snowboard_${Date.now().toString().slice(-4)}`;
      // Set started_at to 35 mins ago so the state machine detects it as abandoned (> 30 min)
      const startedAt = new Date(Date.now() - 35 * 60 * 1000).toISOString();
      await api.abandonCheckout({
        customer_id: customer,
        amount_minor: amount,
        currency: 'INR',
        started_at: startedAt,
      });
      await fetch();
      setSuccessMsg(`Ingested Shopify UCP abandoned cart: Burton Blossom Snowboard (₹46,400). Click 'Run Recovery Agent' to evaluate!`);
    } catch (e: any) {
      setError(e?.message ?? 'failed to simulate Shopify abandon');
    } finally {
      setBusy(false);
    }
  };

  const runTick = async () => {
    setBusy(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const res = await api.tickCheckout();
      await fetch();
      if (res?.nudged > 0) {
        setSuccessMsg(`Recovery agent evaluated drop-offs: dispatched ${res.nudged} recovery nudge(s) and minted live Razorpay payment link(s)!`);
      } else if (res?.abandoned > 0) {
        setSuccessMsg(`Recovery agent evaluated drop-offs: identified ${res.abandoned} new abandoned cart(s).`);
      } else {
        setSuccessMsg('Recovery agent evaluated all drop-offs: all sessions up to date.');
      }
    } catch (e: any) {
      setError(e?.message ?? 'failed to run chaser');
    } finally {
      setBusy(false);
    }
  };

  const recoverOne = async (id: string) => {
    setBusy(true);
    setError(null);
    setSuccessMsg(null);
    try {
      await api.recoverCheckout(id, { payment_id: `pay_demo_${Date.now()}` });
      await fetch();
      setSuccessMsg(`Checkout session ${id} marked as RECOVERED! Revenue saved.`);
    } catch (e: any) {
      setError(e?.message ?? 'failed to recover');
    } finally {
      setBusy(false);
    }
  };

  if (loading && sessions.length === 0) {
    return (
      <EmptyState
        title="No active checkout drop-offs"
        description="Click 'Shopify UCP Abandon' or 'Generic Abandon' to trigger an abandoned cart, then click 'Run Recovery Agent' to evaluate the recovery nudge."
      />
    );
  }
  if (error) {
    return <EmptyState title="Checkout feed unavailable" description={error} />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Checkout Drop-off Recovery"
        description="Recovers shoppers who abandon their cart before finishing payment. When a buyer leaves their checkout, Cadence detects the drop-off, checks compliance rules (TRAI quiet hours & message caps), and sends automated follow-up recovery links with smart discount incentives."
        action={
          <div className="flex gap-2 items-center flex-wrap">
            <DemoSeedBadge />
            <Button onClick={simulateShopifyAbandon} disabled={busy} variant="secondary">
              <Sparkles size={14} className="inline-block mr-1 text-[var(--color-accent)]" />
              Shopify UCP Cart (₹46,400)
            </Button>
            <Button onClick={simulateAbandon} disabled={busy} variant="secondary">
              <ShoppingCart size={14} className="inline-block mr-1" />
              Generic Abandon
            </Button>
            <Button onClick={runTick} disabled={busy} variant="primary">
              <Play size={14} className="inline-block mr-1" />
              Run Recovery Agent
            </Button>
          </div>
        }
      />

      {successMsg && (
        <div className="flex items-center gap-2 p-3 bg-emerald-500/10 border border-emerald-500/20 text-emerald-600 dark:text-emerald-400 rounded-md text-[13px] font-medium">
          <CheckCircle2 size={16} className="shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {(['OPEN', 'ABANDONED', 'NUDGED', 'RECOVERED', 'EXPIRED'] as const).map((status) => (
          <Card key={status} className="p-4 text-center">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-ink-subtle)]">
              {status.replace('_', ' ')}
            </div>
            <div className="text-2xl font-semibold mt-1 font-mono" style={{ color: STATUS_COLOR[status] }}>
              {funnel[status] ?? 0}
            </div>
          </Card>
        ))}
      </div>

      <Card className="p-0 overflow-hidden">
        <CardHeader
          title="Recent sessions"
          subtitle="Most recent first. The follow-up ladder: OPEN -> ABANDONED -> NUDGED (up to 3 times) -> RECOVERED or EXPIRED after 14 days."
        />
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-[var(--color-ink-muted)]">
                <th className="font-semibold py-2 px-3">Session</th>
                <th className="font-semibold py-2 px-3">Customer</th>
                <th className="font-semibold py-2 px-3 text-right">Amount</th>
                <th className="font-semibold py-2 px-3">Status</th>
                <th className="font-semibold py-2 px-3 text-right">Follow-up messages</th>
                <th className="font-semibold py-2 px-3">Started</th>
                <th className="font-semibold py-2 px-3 text-right">What we'll do next</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.id} className="border-t border-[var(--color-line)]">
                  <td className="py-2 px-3 font-mono">{s.id}</td>
                  <td className="py-2 px-3 font-mono text-[var(--color-ink-muted)]">{s.customer_id}</td>
                  <td className="py-2 px-3 text-right font-mono">
                    &#8377;{(s.amount_minor / 100).toFixed(2)}
                  </td>
                  <td className="py-2 px-3">
                    <Badge tone={s.status === 'RECOVERED' ? 'approved' : s.status === 'EXPIRED' ? 'rejected' : 'info'}>
                      {s.status}
                    </Badge>
                  </td>
                  <td className="py-2 px-3 text-right font-mono">{s.nudges_sent}</td>
                  <td className="py-2 px-3 text-[var(--color-ink-muted)] font-mono">{s.started_at}</td>
                  <td className="py-2 px-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      {s.payment_link_short_url && (
                        <a
                          href={s.payment_link_short_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--color-accent)] hover:underline bg-[var(--color-surface-subtle)] px-2 py-0.5 rounded border border-[var(--color-line)]"
                        >
                          <ExternalLink size={11} />
                          Razorpay Link
                        </a>
                      )}
                      {s.status !== 'RECOVERED' && s.status !== 'EXPIRED' && (
                        <button
                          onClick={() => recoverOne(s.id)}
                          disabled={busy}
                          className="text-[12px] text-[var(--color-accent)] font-semibold hover:underline disabled:opacity-50"
                        >
                          Mark recovered
                        </button>
                      )}
                    </div>
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
