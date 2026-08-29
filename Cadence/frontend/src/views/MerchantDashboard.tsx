// Merchant Dashboard view (SPA).
//
// Plain-language "what happened today" tab for merchant owners.
// Pulls live data from api.getMerchantSummary() and refreshes every 8s.
// Three top stat cards (Recovered, Journeys, Avg time to recover),
// a top root causes table, and two bottom panels (state distribution
// horizontal bars + intervention performance bar list).

import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, PageHeader, Badge, EmptyState } from '../components/primitives';
import { api, inrFormatter } from '../services/api';
import type { MerchantSummary } from '../types';

const STATE_LABEL: Record<string, string> = {
  OPENED: 'Opened',
  CLASSIFIED: 'Classified',
  INTERVENING: 'Intervening',
  WAITING_OUTCOME: 'Waiting Outcome',
  RECOVERED: 'Recovered',
  CLOSED_UNRECOVERED: 'Closed Unrecovered',
  ESCALATED: 'Escalated',
  OPEN: 'Open',
  HUMAN_REVIEW: 'Human Review',
};

const CAUSE_LABEL: Record<string, string> = {
  NO_FUNDS: 'No Funds',
  BANK_DOWN: 'Bank Outage',
  TIMEOUT: 'Collect Timeout',
  CUSTOMER_ABORTED: 'User Cancelled',
  HARD_DECLINE: 'Hard Decline',
  BAD_VPA: 'Invalid VPA',
  EXPIRED_INSTRUMENT: 'Expired Mandate',
  UNKNOWN: 'Other',
};

// Map journey states to semantic color tokens in this codebase.
// RECOVERED -> mint (approved), CLOSED_UNRECOVERED/ESCALATED -> coral (rejected),
// INTERVENING/OPEN -> amber (pending), WAITING_OUTCOME -> blue (info),
// HUMAN_REVIEW -> violet (no purple token, mix info + ink wash).
const STATE_TONE: Record<string, { color: string; wash: string }> = {
  RECOVERED: { color: 'var(--color-approved)', wash: 'var(--color-approved-wash)' },
  CLOSED_UNRECOVERED: { color: 'var(--color-rejected)', wash: 'var(--color-rejected-wash)' },
  ESCALATED: { color: 'var(--color-rejected)', wash: 'var(--color-rejected-wash)' },
  INTERVENING: { color: 'var(--color-pending)', wash: 'var(--color-pending-wash)' },
  OPEN: { color: 'var(--color-pending)', wash: 'var(--color-pending-wash)' },
  OPENED: { color: 'var(--color-pending)', wash: 'var(--color-pending-wash)' },
  WAITING_OUTCOME: { color: 'var(--color-info)', wash: 'var(--color-info-wash)' },
  HUMAN_REVIEW: { color: 'var(--color-info)', wash: 'var(--color-info-wash)' },
  CLASSIFIED: { color: 'var(--color-ink-muted)', wash: 'var(--color-surface-subtle)' },
};

function labelFor(code: string, lookup: Record<string, string>): string {
  return lookup[code] ?? code.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

export const MerchantDashboard: React.FC = () => {
  const [summary, setSummary] = useState<MerchantSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    try {
      const data = await api.getMerchantSummary();
      setSummary(data);
      setError(null);
    } catch (e: any) {
      setError(e?.message ?? 'failed to load merchant summary');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch();
    const interval = setInterval(fetch, 8000);
    return () => clearInterval(interval);
  }, [fetch]);

  if (loading && !summary) {
    return (
      <EmptyState
        title="Loading today's summary..."
        description="Pulling the latest recovery numbers, root-cause mix, and intervention performance from the engine."
      />
    );
  }
  if (error && !summary) {
    return <EmptyState title="Merchant summary unavailable" description={error} />;
  }
  if (!summary) return null;

  const recoveredInr = summary.recovered_amount_inr;
  const lostInr = summary.lost_amount_inr;
  const totalAtRisk = recoveredInr + lostInr;
  const recoveryPct = summary.recovery_rate_pct;
  const totalJourneys = summary.total_journeys;
  const recoveredCount = summary.total_recovered;
  const lostCount = summary.total_lost;
  const openCount = Math.max(0, totalJourneys - recoveredCount - lostCount);
  const avgMinutes = summary.avg_time_to_recover_minutes;

  // Journey ring progress (recovered / total)
  const ringPct = totalJourneys > 0
    ? Math.min(100, Math.max(0, (recoveredCount / totalJourneys) * 100))
    : 0;
  const ringCircumference = 2 * Math.PI * 18;
  const ringDash = (ringPct / 100) * ringCircumference;

  const rootCauses = [...summary.top_root_causes].sort((a, b) => b.count - a.count);

  // State distribution rows, sorted by count desc
  const stateRows = Object.entries(summary.state_distribution)
    .map(([state, count]) => ({ state, count }))
    .sort((a, b) => b.count - a.count);
  const maxStateCount = stateRows.reduce((m, r) => Math.max(m, r.count), 0);

  // Intervention performance, sorted by count desc
  const interventions = [...summary.intervention_performance].sort((a, b) => b.count - a.count);
  const maxInterventionCount = interventions.reduce((m, r) => Math.max(m, r.count), 0);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Merchant Dashboard"
        description="What happened today, in plain language. Live totals for money recovered, journeys closed, and how long it took — refreshed every 8 seconds."
        action={
          <Badge tone={error ? 'rejected' : 'approved'}>
            {error ? 'Stale' : 'Live'}
          </Badge>
        }
      />

      {/* Top row: 3 large stat cards */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="p-5">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-ink-subtle)]">
              Recovered
            </span>
            <Badge tone="approved">Today</Badge>
          </div>
          <p className="numeric text-3xl sm:text-4xl font-semibold text-[var(--color-approved)] mt-3">
            {inrFormatter.format(recoveredInr / 100)}
          </p>
          <p className="text-[12px] text-[var(--color-ink-muted)] mt-2">
            of {inrFormatter.format(totalAtRisk / 100)} total at risk
          </p>
          <p className="text-[12px] text-[var(--color-ink-muted)] mt-0.5">
            <span className="font-medium text-[var(--color-ink)]">
              {recoveryPct.toFixed(1)}%
            </span>{' '}
            recovery rate
          </p>
        </Card>

        <Card className="p-5">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-ink-subtle)]">
              Journeys
            </span>
            <Badge tone="info">Today</Badge>
          </div>
          <div className="flex items-center gap-4 mt-3">
            <div className="relative h-12 w-12 shrink-0">
              <svg viewBox="0 0 40 40" className="h-12 w-12 -rotate-90">
                <circle
                  cx="20"
                  cy="20"
                  r="18"
                  fill="none"
                  stroke="var(--color-line)"
                  strokeWidth="4"
                />
                <circle
                  cx="20"
                  cy="20"
                  r="18"
                  fill="none"
                  stroke="var(--color-approved)"
                  strokeWidth="4"
                  strokeLinecap="round"
                  strokeDasharray={`${ringDash} ${ringCircumference}`}
                />
              </svg>
              <span className="absolute inset-0 flex items-center justify-center text-[10px] font-semibold text-[var(--color-ink-muted)] tabular-nums">
                {Math.round(ringPct)}%
              </span>
            </div>
            <div>
              <p className="numeric text-3xl sm:text-4xl font-semibold text-[var(--color-ink)] leading-none">
                {totalJourneys}
              </p>
              <p className="text-[11px] text-[var(--color-ink-subtle)] mt-1">total today</p>
            </div>
          </div>
          <p className="text-[12px] text-[var(--color-ink-muted)] mt-3">
            <span className="text-[var(--color-approved)] font-medium">{recoveredCount} recovered</span>
            {' · '}
            <span className="text-[var(--color-rejected)] font-medium">{lostCount} lost</span>
            {' · '}
            <span className="text-[var(--color-pending)] font-medium">{openCount} still open</span>
          </p>
        </Card>

        <Card className="p-5">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-ink-subtle)]">
              Avg time to recover
            </span>
            <Badge tone="pending">End-to-end</Badge>
          </div>
          <p className="numeric text-3xl sm:text-4xl font-semibold text-[var(--color-ink)] mt-3">
            {avgMinutes.toFixed(1)}
            <span className="text-base font-normal text-[var(--color-ink-muted)] ml-1">minutes</span>
          </p>
          <p className="text-[12px] text-[var(--color-ink-muted)] mt-2">
            end-to-end including payment_link.paid wait
          </p>
        </Card>
      </div>

      {/* Middle row: Top root causes table */}
      <Card>
        <CardHeader
          title="Top root causes"
          subtitle="What actually broke, and how often we rescued each one"
          action={
            <Badge tone="neutral">{rootCauses.length} cause{rootCauses.length === 1 ? '' : 's'}</Badge>
          }
        />
        {rootCauses.length === 0 ? (
          <div className="px-5 py-10 text-center text-[12px] text-[var(--color-ink-subtle)]">
            No decline events recorded yet today.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[12.5px]">
              <thead>
                <tr className="text-left text-[var(--color-ink-muted)] border-b border-[var(--color-line)]">
                  <th className="font-semibold py-2.5 px-5">Cause</th>
                  <th className="font-semibold py-2.5 px-3 text-right">Count</th>
                  <th className="font-semibold py-2.5 px-3 text-right">Recovered</th>
                  <th className="font-semibold py-2.5 px-3 text-right">Lost</th>
                  <th className="font-semibold py-2.5 px-5 text-right">Recovery %</th>
                </tr>
              </thead>
              <tbody>
                {rootCauses.map((c) => {
                  const total = c.recovered + c.lost;
                  const pct = total > 0 ? (c.recovered / total) * 100 : 0;
                  const tone = pct >= 70 ? 'approved' : pct >= 40 ? 'pending' : 'rejected';
                  return (
                    <tr key={c.root_cause} className="border-t border-[var(--color-line)]">
                      <td className="py-2.5 px-5 font-medium text-[var(--color-ink)]">
                        {labelFor(c.root_cause, CAUSE_LABEL)}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono tabular-nums text-[var(--color-ink)]">
                        {c.count}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono tabular-nums text-[var(--color-approved)]">
                        {c.recovered}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono tabular-nums text-[var(--color-rejected)]">
                        {c.lost}
                      </td>
                      <td className="py-2.5 px-5 text-right">
                        <Badge tone={tone}>{pct.toFixed(0)}%</Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Bottom row: 2 panels side-by-side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader
            title="State distribution"
            subtitle="Where every journey sits right now"
          />
          <div className="p-5 space-y-2.5">
            {stateRows.length === 0 ? (
              <div className="text-[12px] text-[var(--color-ink-subtle)]">
                No journeys yet today.
              </div>
            ) : (
              stateRows.map((row) => {
                const tone = STATE_TONE[row.state] ?? {
                  color: 'var(--color-ink-muted)',
                  wash: 'var(--color-surface-subtle)',
                };
                const widthPct = maxStateCount > 0
                  ? Math.max(2, (row.count / maxStateCount) * 100)
                  : 0;
                return (
                  <div key={row.state} className="text-[12.5px]">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[var(--color-ink-muted)]">
                        {labelFor(row.state, STATE_LABEL)}
                      </span>
                      <span
                        className="numeric tabular-nums font-medium"
                        style={{ color: tone.color }}
                      >
                        {row.count}
                      </span>
                    </div>
                    <div className="h-2 w-full rounded-full bg-[var(--color-surface-subtle)] overflow-hidden border border-[var(--color-line)]">
                      <div
                        className="h-full rounded-full transition-[width] duration-[var(--duration-micro)]"
                        style={{ width: `${widthPct}%`, backgroundColor: tone.color }}
                      />
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Intervention performance"
            subtitle="Which actions actually closed the loop"
          />
          <div className="p-5 space-y-2.5">
            {interventions.length === 0 ? (
              <div className="text-[12px] text-[var(--color-ink-subtle)]">
                No interventions fired yet today.
              </div>
            ) : (
              interventions.map((iv) => {
                const widthPct = maxInterventionCount > 0
                  ? Math.max(2, (iv.count / maxInterventionCount) * 100)
                  : 0;
                const recoveryPct = iv.count > 0 ? (iv.recovered / iv.count) * 100 : 0;
                return (
                  <div key={iv.intervention} className="text-[12.5px]">
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-mono text-[var(--color-ink)] truncate pr-2">
                        {iv.intervention}
                      </span>
                      <span className="numeric tabular-nums text-[var(--color-ink-muted)] shrink-0">
                        {iv.recovered}/{iv.count}
                      </span>
                    </div>
                    <div className="h-2 w-full rounded-full bg-[var(--color-surface-subtle)] overflow-hidden border border-[var(--color-line)]">
                      <div
                        className="h-full rounded-full bg-[var(--color-approved)] transition-[width] duration-[var(--duration-micro)]"
                        style={{ width: `${widthPct}%` }}
                      />
                    </div>
                    <div className="text-[10.5px] text-[var(--color-ink-subtle)] mt-0.5 font-mono tabular-nums">
                      {recoveryPct.toFixed(0)}% recovered
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </Card>
      </div>

      <p className="text-[11px] text-[var(--color-ink-subtle)] font-mono">
        generated_at {summary.generated_at}
      </p>
    </div>
  );
};