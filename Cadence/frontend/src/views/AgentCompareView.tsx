// AgentCompare tab: live "your agent vs the Razorpay default" chart.
//
// PHASE 3: runs the same Indian cohort through both arms and shows
// the deltas. Click "Run comparison" to re-run with a fresh seed. The
// bar chart shows: recovery % per arm, contacts per arm, attempts per
// arm. The headline number is the uplift.

import React, { useState, useCallback } from 'react';
import { Card, CardHeader, Badge, Button, PageHeader, EmptyState } from '../components/primitives';
import { api } from '../services/api';
import type { AgentCompare } from '../types';
import { BarChart3, RefreshCw, Trophy } from 'lucide-react';

export const AgentCompareView: React.FC = () => {
  const [result, setResult] = useState<AgentCompare | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState<number>(100);
  const [seed, setSeed] = useState<number>(42);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getAgentCompare(n, seed);
      setResult(data);
    } catch (e: any) {
      setError(e?.message ?? 'comparison failed');
    } finally {
      setLoading(false);
    }
  }, [n, seed]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Your Agent vs Razorpay Default"
        description="PHASE 3: live head-to-head. Runs the same Indian cohort through both the naive retry policy (Razorpay Smart Retries baseline) and Cadence. The bar chart shows recovery %, contacts, attempts. The headline number is the uplift Cadence delivers."
        action={
          <div className="flex gap-2 items-end">
            <label className="text-[11px] text-[var(--color-ink-muted)]">
              <div>n</div>
              <input
                type="number"
                min={10}
                max={200}
                value={n}
                onChange={(e) => setN(parseInt(e.target.value || '100', 10))}
                className="w-20 px-2 py-1 border border-[var(--color-line)] rounded text-[12px] font-mono"
              />
            </label>
            <label className="text-[11px] text-[var(--color-ink-muted)]">
              <div>seed</div>
              <input
                type="number"
                value={seed}
                onChange={(e) => setSeed(parseInt(e.target.value || '42', 10))}
                className="w-20 px-2 py-1 border border-[var(--color-line)] rounded text-[12px] font-mono"
              />
            </label>
            <Button onClick={run} disabled={loading} variant="primary">
              <RefreshCw size={14} className={`inline-block mr-1 ${loading ? 'animate-spin' : ''}`} />
              {loading ? 'Running…' : 'Run comparison'}
            </Button>
          </div>
        }
      />

      {error && <EmptyState title="Comparison failed" description={error} />}

      {!error && !result && !loading && (
        <EmptyState
          title="Click 'Run comparison' to start"
          description="Runs the same Indian Faker cohort through both arms: naive Razorpay-style retry (T+24h then d1/d3/d5 emails) and Cadence (deterministic bandit + Guardian + real engine). Each arm runs on a fresh SQLite with the same calibrated outcome table, so the comparison is apples-to-apples."
        />
      )}

      {result && (
        <CompareResultView result={result} />
      )}
    </div>
  );
};

const CompareResultView: React.FC<{ result: AgentCompare }> = ({ result }) => {
  const naivePct = result.naive_recovery_pct;
  const revivePct = result.revive_recovery_pct;
  const maxPct = Math.max(naivePct, revivePct, 1);

  return (
    <>
      <Card className="p-5">
        <div className="flex items-baseline gap-3">
          <BarChart3 size={20} className="text-[var(--color-ink-muted)]" />
          <span className="text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold">
            Head-to-head on {result.n} Indian subscribers (seed {result.seed})
          </span>
          <span className="ml-auto text-[10px] text-[var(--color-ink-soft)] font-mono">
            ran in {result.runtime_ms}ms
          </span>
        </div>
        <div className="grid grid-cols-3 gap-4 mt-5">
          <Bar label="Recovery %" naive={naivePct} revive={revivePct} max={maxPct} suffix="%" />
          <Bar label="Contacts sent" naive={result.naive_contacts} revive={result.revive_contacts} max={Math.max(result.naive_contacts, result.revive_contacts, 1)} />
          <Bar label="Recovery attempts" naive={result.naive_attempts} revive={result.revive_attempts} max={Math.max(result.naive_attempts, result.revive_attempts, 1)} />
        </div>
      </Card>

      <Card className="p-5">
        <div className="grid grid-cols-2 gap-6">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold">
              Naive (Razorpay Smart Retries baseline)
            </div>
            <div className="text-3xl font-semibold text-[var(--color-ink)] mt-2 font-mono">
              Rs.{result.naive_recovered_inr.toFixed(2)}
            </div>
            <div className="text-[12px] text-[var(--color-ink-muted)] mt-1">
              {naivePct.toFixed(1)}% recovery rate
            </div>
            <div className="text-[11px] text-[var(--color-ink-soft)] mt-3">
              Blind retry +24h, then d1/d3/d5 emails. Same customer, every
              customer, every time.
            </div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold flex items-center gap-2">
              Cadence (deterministic bandit + Guardian)
              <Trophy size={14} className="text-[var(--color-accent)]" />
            </div>
            <div className="text-3xl font-semibold text-[var(--color-accent)] mt-2 font-mono">
              Rs.{result.revive_recovered_inr.toFixed(2)}
            </div>
            <div className="text-[12px] text-[var(--color-ink-muted)] mt-1">
              {revivePct.toFixed(1)}% recovery rate
            </div>
            <div className="text-[11px] text-[var(--color-ink-soft)] mt-3">
              Cause-aware decision: only contacts within touch cap, no
              messages 9pm-9am IST, deterministic weights in source.
            </div>
          </div>
        </div>

        <div className="border-t border-[var(--color-line)] mt-5 pt-4 flex items-center gap-3">
          <div className="flex-1">
            <div className="text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold">
              Uplift
            </div>
            <div className="text-2xl font-semibold text-[var(--color-accent)] mt-1 font-mono">
              +{result.uplift_pct.toFixed(1)}%
            </div>
          </div>
          <div className="flex-1">
            <div className="text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold">
              Recovered delta
            </div>
            <div className="text-2xl font-semibold text-[var(--color-ink)] mt-1 font-mono">
              Rs.{result.recovered_delta.toFixed(2)}
            </div>
          </div>
          <div className="flex-1">
            <div className="text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold">
              Fast-path %
            </div>
            <div className="text-2xl font-semibold text-[var(--color-ink)] mt-1 font-mono">
              {result.fast_path_pct.toFixed(0)}%
            </div>
            <div className="text-[10px] text-[var(--color-ink-soft)] mt-1">
              deterministic, no LLM
            </div>
          </div>
        </div>
      </Card>

      <Card className="p-4">
        <div className="text-[10px] text-[var(--color-ink-soft)] font-mono">
          source: {result.source} &middot; cohort: {result.cohort} &middot; n: {result.n} &middot;
          seed: {result.seed} &middot; runtime: {result.runtime_ms}ms
        </div>
      </Card>
    </>
  );
};

const Bar: React.FC<{
  label: string;
  naive: number;
  revive: number;
  max: number;
  suffix?: string;
}> = ({ label, naive, revive, max, suffix = '' }) => {
  const naiveW = Math.max(2, (naive / max) * 100);
  const reviveW = Math.max(2, (revive / max) * 100);
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold">
        {label}
      </div>
      <div className="mt-2 space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="w-12 text-[10px] text-[var(--color-ink-muted)] font-mono">naive</span>
          <div className="flex-1 h-3 bg-[var(--color-paper-2)] rounded overflow-hidden">
            <div
              className="h-full bg-[var(--color-ink-soft)]"
              style={{ width: `${naiveW}%` }}
            />
          </div>
          <span className="w-16 text-right text-[11px] font-mono">
            {naive.toFixed(0)}{suffix}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-12 text-[10px] text-[var(--color-ink-muted)] font-mono">Cadence</span>
          <div className="flex-1 h-3 bg-[var(--color-paper-2)] rounded overflow-hidden">
            <div
              className="h-full bg-[var(--color-accent)]"
              style={{ width: `${reviveW}%` }}
            />
          </div>
          <span className="w-16 text-right text-[11px] font-mono">
            {revive.toFixed(0)}{suffix}
          </span>
        </div>
      </div>
    </div>
  );
};
