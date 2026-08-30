// Mandate ID retry sequencer view (SPA).
//
// Shows recent sequencer decisions: each row is one failed mandate
// + the action the sequencer chose (RETRY_NOW, RETRY_24H,
// REMITTER_OUTREACH, SWITCH_METHOD, STOP_AND_HUMAN_REVIEW). The
// user can:
//   - simulate a mandate failure (POST /api/mandate/failed)
//   - see the count-by-action summary (GET /api/mandate/sequenced/summary)

import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, Badge, Button, PageHeader, EmptyState } from '../components/primitives';
import { api } from '../services/api';
import { GitBranch, Play } from 'lucide-react';

interface SequencedMandate {
  mandate_id: string;
  action: string;
  schedule_after_seconds: number;
  reason: string;
  ran_at: string;
}

const ACTION_COLOR: Record<string, string> = {
  RETRY_NOW: 'var(--color-approved)',
  RETRY_24H: 'var(--color-info)',
  REMITTER_OUTREACH: 'var(--color-pending)',
  SWITCH_METHOD: 'var(--color-pending)',
  STOP_AND_HUMAN_REVIEW: 'var(--color-rejected)',
};

export const MandateView: React.FC = () => {
  const [decisions, setDecisions] = useState<SequencedMandate[]>([]);
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fetch = useCallback(async () => {
    try {
      const [d, s] = await Promise.all([
        api.getMandateSequenced(25),
        api.getMandateSequencedSummary(),
      ]);
      setDecisions(d);
      setSummary(s.counts);
      setError(null);
    } catch (e: any) {
      setError(e?.message ?? 'failed to load mandate sequencer');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch();
    const interval = setInterval(fetch, 4000);
    return () => clearInterval(interval);
  }, [fetch]);

  const simulateBankDown = async () => {
    setBusy(true);
    try {
      await api.mandateFailed({
        subscription_id: `sub_demo_${Date.now()}`,
        customer_id: `cust_demo_${Date.now()}`,
        mandate_id: `mnd_demo_${Date.now()}`,
        cause: 'BANK_DOWN',
        mandate_status: 'active',
      });
      await fetch();
    } catch (e: any) {
      setError(e?.message ?? 'failed to simulate');
    } finally {
      setBusy(false);
    }
  };

  if (loading && decisions.length === 0) {
    return (
      <EmptyState
        title="Waiting for the UPI auto-pay sequencer to fire..."
        description="Click 'Simulate a UPI auto-pay failure' to record a failure and watch the sequencer pick the next action."
      />
    );
  }
  if (error) {
    return <EmptyState title="UPI auto-pay sequencer unavailable" description={error} />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="UPI Auto-pay Retry Sequencer"
        description="A failed UPI auto-pay or card e-mandate needs cross-channel cadence. The sequencer ladder: RETRY_NOW (cause != BANK_DOWN) -> RETRY_24H (BANK_DOWN) -> REMITTER_OUTREACH (3+ BANK_DOWN in 7d) -> SWITCH_METHOD (mandate paused > 14d) -> STOP_AND_HUMAN_REVIEW (3+ distinct causes). Every decision is replayable from the hash-chained audit log."
        action={
          <Button onClick={simulateBankDown} disabled={busy} variant="secondary">
            <Play size={14} className="inline-block mr-1" />
            Simulate a UPI auto-pay failure
          </Button>
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {(['RETRY_NOW', 'RETRY_24H', 'REMITTER_OUTREACH', 'SWITCH_METHOD', 'STOP_AND_HUMAN_REVIEW'] as const).map((action) => (
          <Card key={action} className="p-4 text-center">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-ink-subtle)] font-mono">
              {action.replace(/_/g, ' ')}
            </div>
            <div
              className="text-2xl font-semibold mt-1 font-mono"
              style={{ color: ACTION_COLOR[action] || 'var(--color-ink-muted)' }}
            >
              {summary[action] ?? 0}
            </div>
          </Card>
        ))}
      </div>

      <Card className="p-0 overflow-hidden">
        <CardHeader
          title="Recent sequencer decisions"
          subtitle="Each row is one failure event + the action the sequencer chose. The reason is the audit chain's plain-text explanation."
        />
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-[var(--color-ink-muted)]">
                <th className="font-semibold py-2 px-3">Mandate</th>
                <th className="font-semibold py-2 px-3">What we'll do next</th>
                <th className="font-semibold py-2 px-3 text-right">When (seconds from now)</th>
                <th className="font-semibold py-2 px-3">Why</th>
                <th className="font-semibold py-2 px-3">When fired</th>
              </tr>
            </thead>
            <tbody>
              {decisions.map((d, i) => (
                <tr key={`${d.mandate_id}-${i}`} className="border-t border-[var(--color-line)]">
                  <td className="py-2 px-3 font-mono">{d.mandate_id}</td>
                  <td className="py-2 px-3">
                    <span
                      className="text-[12px] font-mono font-semibold"
                      style={{ color: ACTION_COLOR[d.action] || 'var(--color-ink-muted)' }}
                    >
                      {d.action.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-right font-mono">
                    {d.schedule_after_seconds}
                  </td>
                  <td className="py-2 px-3 text-[var(--color-ink-muted)] font-mono text-[12px]">
                    {d.reason}
                  </td>
                  <td className="py-2 px-3 text-[var(--color-ink-muted)] font-mono text-[12px]">
                    {d.ran_at}
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
