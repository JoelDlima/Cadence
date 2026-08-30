// Adaptive How the agent decides view (SPA).
//
// Renders the most recent Adaptive How the agent decides ranking events.
// Each event shows cause, ranked interventions with scores, top choice
// with a human-readable reason, and the feature importances dict.

import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, PageHeader, Badge, EmptyState } from '../components/primitives';
import { api } from '../services/api';
import type { BanditRanking } from '../types';

const FEATURE_LABELS: Record<string, string> = {
  amount_big: 'big amount',
  amount_mid: 'mid amount',
  touches_0: 'first contact',
  touches_1: 'second contact',
  touches_2: 'third contact',
  touches_3_plus: 'saturated',
  attempts_0: 'first attempt',
  attempts_1: 'second attempt',
  attempts_2: 'third attempt',
  attempts_3_plus: 'saturated attempts',
  cause_no_funds: 'cause = no funds',
  cause_bank_down: 'cause = bank down',
  cause_timeout: 'cause = timeout',
  outage_active: 'same-cause spike in last 24h',
  in_peak_hold: 'NPCI peak-hold window now',
};

export const RecoveryBrainView: React.FC = () => {
  const [rankings, setRankings] = useState<BanditRanking[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    try {
      const data = await api.getBanditRanked(25);
      setRankings(data.rankings);
      setError(null);
    } catch (e: any) {
      setError(e?.message ?? 'failed to load bandit rankings');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch();
    const interval = setInterval(fetch, 3000);
    return () => clearInterval(interval);
  }, [fetch]);

  if (loading && rankings.length === 0) {
    return (
      <EmptyState
        title="Waiting for the How the agent decides to fire..."
        description="Inject a webhook from the Testbench tab to see the engine pick its first action and emit its first bandit.ranked event."
      />
    );
  }
  if (error) {
    return (
      <EmptyState title="Bandit feed unavailable" description={error} />
    );
  }
  if (rankings.length === 0) {
    return (
      <EmptyState
        title="No bandit rankings yet"
        description="Inject a webhook from the Testbench tab to see the engine pick its first action and emit its first bandit.ranked event."
      />
    );
  }

  const mostRecentImportances = rankings[0]?.feature_importances ?? {};

  return (
    <div className="space-y-6">
      <PageHeader
        title="How the agent decides"
        description="Deterministic, auditable bandit that picks the next action for every (cause, context) tuple. Trained weights on amount tier, touch fatigue, attempts, cause prior, outage flag, peak-hold flag. The Guardian gates; the Phantom-Failure Guard still floors the schedule."
        action={
          <Badge tone={rankings.length > 0 ? 'info' : 'neutral'}>
            {rankings.length} ranked decisions
          </Badge>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {rankings.slice(0, 12).map((r, i) => (
          <Card key={`${r.occurred_at}-${i}`} className="p-5 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-mono text-[var(--color-ink-muted)]">
                {r.occurred_at}
              </span>
              <Badge tone="info">{r.cause}</Badge>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold mb-1">
                Agent's top pick
              </div>
              <div className="text-base font-semibold text-[var(--color-ink)] font-mono">
                {r.top}
              </div>
              {r.reason && r.reason.length > 0 && (
                <div className="text-[12px] text-[var(--color-ink-muted)] mt-1">
                  {r.reason.join(' - ')}
                </div>
              )}
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold mb-1">
                Other options the agent considered
              </div>
              <ol className="space-y-0.5 text-[12px] font-mono">
                {r.ranked.map((candidate, j) => {
                  const score = r.scores[candidate] ?? 0;
                  const isTop = j === 0;
                  return (
                    <li
                      key={candidate}
                      className={
                        isTop
                          ? 'text-[var(--color-ink)] font-semibold'
                          : 'text-[var(--color-ink-muted)]'
                      }
                    >
                      <span className="inline-block w-4 text-right pr-1.5">{j + 1}.</span>
                      <span>{candidate}</span>
                      <span className="pl-2 tabular-nums text-[var(--color-ink-muted)]">
                        {score.toFixed(1)}
                      </span>
                    </li>
                  );
                })}
              </ol>
            </div>
          </Card>
        ))}
      </div>

      <Card className="p-5">
        <CardHeader
          title="Reason importances (latest ranked decision)"
          subtitle="Why the brain picked what it picked. Tuned on the engine audit chain."
        />
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-left text-[var(--color-ink-muted)]">
                <th className="font-semibold py-1 pr-3">Reason</th>
                {Object.keys(mostRecentImportances).map((cause) => (
                  <th key={cause} className="font-mono font-semibold py-1 px-2 text-center">
                    {cause}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(FEATURE_LABELS).map(([feature, label]) => (
                <tr key={feature} className="border-t border-[var(--color-line)]">
                  <td className="py-1 pr-3 font-mono text-[var(--color-ink-muted)]">{label}</td>
                  {Object.keys(mostRecentImportances).map((cause) => {
                    const weight = mostRecentImportances[cause]?.[feature];
                    const isActive = weight !== undefined && weight !== 0;
                    return (
                      <td
                        key={cause + feature}
                        className={
                          'py-1 px-2 text-center font-mono ' +
                          (isActive
                            ? weight! > 0
                              ? 'text-[var(--color-ink)]'
                              : 'text-[var(--color-ink-muted)]'
                            : 'text-[var(--color-line)]')
                        }
                      >
                        {weight === undefined ? '-' : weight.toFixed(1)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-[11px] text-[var(--color-ink-muted)] mt-3">
          Positive values push the bandit toward that action; negative values push against.
          Weights come from FEATURE_IMPORTANCES in <code className="font-mono">revive/policy/bandit.py</code>
          and are auditable in the source.
        </p>
      </Card>
    </div>
  );
};
