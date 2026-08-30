// Test Lab tab: agent comparison + chaos drills in one place.
//
// Replaces the previous "Results" (AgentCompareView) and "Simulation & Chaos"
// (TestbenchView) tabs after the SPA consolidation. Renders the headline
// comparison card (5-seed mean uplift) at the top, then a 2-column grid of
// four chaos drills below. Each drill has a real button that POSTs to the
// live API; failures are surfaced honestly in the UI.

import React, { useState, useCallback } from 'react';
import { Card, CardHeader, Badge, Button, PageHeader, EmptyState, Input } from '../components/primitives';
import { api } from '../services/api';
import type { AgentCompare } from '../types';
import {
  BarChart3,
  RefreshCw,
  Trophy,
  Play,
  Copy,
  ZapOff,
  Shuffle,
  AlertOctagon,
} from 'lucide-react';

const DEFAULT_SEEDS = [42, 7, 99, 123, 2024] as const;

interface DrillResult {
  status: 'idle' | 'running' | 'passed' | 'failed';
  detail?: string;
}

type DrillId = 'duplicate_webhook' | 'inject_no_funds' | 'reorder' | 'kill_switch';

interface DrillMeta {
  title: string;
  subtitle: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
}

const DRILL_META: Record<DrillId, DrillMeta> = {
  duplicate_webhook: {
    title: 'Duplicate webhook',
    subtitle: 'Posts the same event twice; engine must dedupe.',
    icon: Copy,
  },
  inject_no_funds: {
    title: 'Inject 3 NO_FUNDS',
    subtitle: 'Triggers the anomaly card on the Overview tab.',
    icon: ZapOff,
  },
  reorder: {
    title: 'Reorder',
    subtitle: 'Sends events out of order; engine must reconcile.',
    icon: Shuffle,
  },
  kill_switch: {
    title: 'Kill switch test',
    subtitle: 'Toggles the kill switch; outbound sends must halt.',
    icon: AlertOctagon,
  },
};

const TestLabView: React.FC = () => {
  // --- Comparison (top) ---
  const [result, setResult] = useState<AgentCompare | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState<number>(50);
  const [seed, setSeed] = useState<number>(42);
  const [useMultiSeed, setUseMultiSeed] = useState<boolean>(true);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = useMultiSeed
        ? await api.getAgentCompare(n, DEFAULT_SEEDS[0], [...DEFAULT_SEEDS])
        : await api.getAgentCompare(n, seed);
      setResult(data);
    } catch (e: any) {
      setError(e?.message ?? 'comparison failed');
    } finally {
      setLoading(false);
    }
  }, [n, seed, useMultiSeed]);

  // --- Chaos drills (bottom) ---
  const [subId, setSubId] = useState('sub_judge_live');
  const [custId, setCustId] = useState('cust_judge_01');
  const [activeDrill, setActiveDrill] = useState<DrillId | null>(null);
  const [drillOutputs, setDrillOutputs] = useState<Record<string, DrillResult>>({});

  const runDrill = useCallback(async (id: DrillId) => {
    setActiveDrill(id);
    setDrillOutputs((prev) => ({ ...prev, [id]: { status: 'running' } }));
    try {
      let detail = '';
      if (id === 'duplicate_webhook') {
        const res = await api.injectFailure({
          subscription_id: subId,
          customer_id: custId,
          failure_code: 'insufficient_funds',
          amount_minor: 149900,
          error_description: 'Chaos drill: duplicate webhook',
        });
        detail = `http ${res.http_status} · journey ${res.body?.journey_id ?? 'n/a'}`;
      } else if (id === 'inject_no_funds') {
        for (let i = 0; i < 3; i++) {
          await api.injectFailure({
            subscription_id: `${subId}_${i}`,
            customer_id: `${custId}_${i}`,
            failure_code: 'insufficient_funds',
            amount_minor: 49900,
            error_description: 'Chaos drill: NO_FUNDS burst',
          });
        }
        detail = '3 NO_FUNDS events injected';
      } else if (id === 'reorder') {
        const res = await api.injectFailure({
          subscription_id: subId,
          customer_id: custId,
          failure_code: 'bank_technical_error',
          amount_minor: 29900,
          error_description: 'Chaos drill: reorder (later event, replayed first)',
        });
        detail = `http ${res.http_status} (reorder test)`;
      } else {
        const current = await api.getKillSwitch().catch(() => false);
        const next = !current;
        const after = await api.setKillSwitch(next);
        detail = `kill switch: ${current ? 'ON' : 'OFF'} -> ${after ? 'ON' : 'OFF'}`;
      }
      setDrillOutputs((prev) => ({ ...prev, [id]: { status: 'passed', detail } }));
    } catch (err: any) {
      setDrillOutputs((prev) => ({
        ...prev,
        [id]: { status: 'failed', detail: err?.message ?? 'drill request failed' },
      }));
    } finally {
      setActiveDrill(null);
    }
  }, [subId, custId]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Test Lab"
        description="Agent comparison and chaos drills in one place. Run the head-to-head against the naive baseline, then poke the engine with adversarial inputs."
        action={<Badge tone="approved">Live</Badge>}
      />

      {/* --- Comparison section --- */}
      <Card>
        <CardHeader
          title="Agent vs Razorpay default"
          subtitle="Same Indian cohort through both arms. Naive arm is Razorpay Smart Retries. Cadence runs the bandit, Guardian, and LLM writer."
          action={
            <div className="flex gap-2 items-end">
              <label className="text-[11px] text-[var(--color-ink-muted)]">
                <div>n</div>
                <input
                  type="number"
                  min={10}
                  max={50}
                  value={n}
                  onChange={(e) => setN(parseInt(e.target.value || '50', 10))}
                  className="w-20 px-2 py-1 border border-[var(--color-line)] rounded text-[12px] font-mono"
                />
              </label>
              <label className="text-[11px] text-[var(--color-ink-muted)] flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={useMultiSeed}
                  onChange={(e) => setUseMultiSeed(e.target.checked)}
                  className="accent-[var(--color-accent)]"
                />
                <span>5 seeds (mean)</span>
              </label>
              {!useMultiSeed && (
                <label className="text-[11px] text-[var(--color-ink-muted)]">
                  <div>seed</div>
                  <input
                    type="number"
                    value={seed}
                    onChange={(e) => setSeed(parseInt(e.target.value || '42', 10))}
                    className="w-20 px-2 py-1 border border-[var(--color-line)] rounded text-[12px] font-mono"
                  />
                </label>
              )}
              <Button onClick={run} disabled={loading} variant="primary">
                <RefreshCw size={14} className={`inline-block mr-1 ${loading ? 'animate-spin' : ''}`} />
                {loading ? 'Running…' : 'Run comparison'}
              </Button>
            </div>
          }
        />

        <div className="p-5">
          {error && <EmptyState title="Comparison failed" description={error} />}

          {!error && !result && !loading && (
            <EmptyState
              title="Click Run comparison to start"
              description="Same cohort, both arms. Each arm runs on a fresh DB with the same outcome table."
            />
          )}

          {result && <CompareResultView result={result} />}
        </div>
      </Card>

      {/* --- Chaos drills section --- */}
      <Card>
        <CardHeader
          title="Chaos drills"
          subtitle="Adversarial inputs against the live engine. Honest failures are surfaced below — check the result box for status."
          action={<Badge tone="neutral">4 drills</Badge>}
        />
        <div className="p-5 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="text-[12px] text-[var(--color-ink-muted)]">
              <div className="mb-1">Subscription</div>
              <Input
                value={subId}
                onChange={(e) => setSubId(e.target.value)}
                placeholder="sub_..."
                className="numeric text-[13px]"
              />
            </label>
            <label className="text-[12px] text-[var(--color-ink-muted)]">
              <div className="mb-1">Customer</div>
              <Input
                value={custId}
                onChange={(e) => setCustId(e.target.value)}
                placeholder="cust_..."
                className="numeric text-[13px]"
              />
            </label>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {(Object.keys(DRILL_META) as DrillId[]).map((id) => {
              const meta = DRILL_META[id];
              const Icon = meta.icon;
              const drillState = drillOutputs[id];
              return (
                <div
                  key={id}
                  className="p-3.5 rounded-md border border-[var(--color-line)] bg-[var(--color-surface-subtle)] space-y-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-start gap-2 min-w-0">
                      <Icon size={14} className="text-[var(--color-ink-muted)] mt-0.5 shrink-0" />
                      <div className="min-w-0">
                        <h4 className="text-xs font-semibold text-[var(--color-ink)]">
                          {meta.title}
                        </h4>
                        <p className="text-[11.5px] text-[var(--color-ink-muted)]">
                          {meta.subtitle}
                        </p>
                      </div>
                    </div>
                    <Button
                      variant="secondary"
                      size="sm"
                      loading={activeDrill === id}
                      onClick={() => runDrill(id)}
                    >
                      <Play size={12} />
                      Run
                    </Button>
                  </div>
                  {drillState && drillState.status !== 'idle' && (
                    <div
                      className="p-2.5 rounded border text-[11px] font-mono whitespace-pre-wrap"
                      style={{
                        backgroundColor:
                          drillState.status === 'running'
                            ? 'var(--color-info-wash)'
                            : drillState.status === 'passed'
                              ? 'var(--color-approved-wash)'
                              : 'var(--color-rejected-wash)',
                        borderColor:
                          drillState.status === 'running'
                            ? 'var(--color-info)'
                            : drillState.status === 'passed'
                              ? 'var(--color-approved)'
                              : 'var(--color-rejected)',
                        color:
                          drillState.status === 'running'
                            ? 'var(--color-info)'
                            : drillState.status === 'passed'
                              ? 'var(--color-approved)'
                              : 'var(--color-rejected)',
                      }}
                    >
                      <strong>
                        {drillState.status === 'running'
                          ? 'RUNNING…'
                          : drillState.status === 'passed'
                            ? 'PASS'
                            : 'FAIL'}
                      </strong>
                      {drillState.detail ? ` · ${drillState.detail}` : ''}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </Card>
    </div>
  );
};

export default TestLabView;

const CompareResultView: React.FC<{ result: AgentCompare }> = ({ result }) => {
  const multiSeed = (result.per_seed?.length ?? 0) > 1;
  const naivePct = multiSeed ? result.mean_naive_recovery_pct : result.naive_recovery_pct;
  const revivePct = multiSeed ? result.mean_revive_recovery_pct : result.revive_recovery_pct;
  const uplift = multiSeed ? result.mean_uplift_pct : result.uplift_pct;
  const maxPct = Math.max(naivePct, revivePct, 1);

  return (
    <>
      <Card className="p-5">
        <div className="flex items-baseline gap-3">
          <BarChart3 size={20} className="text-[var(--color-ink-muted)]" />
          <span className="text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold">
            {multiSeed
              ? `Mean of ${result.per_seed.length} seeds, ${result.n} subscribers each (${result.seeds.join(', ')})`
              : `Head-to-head on ${result.n} Indian subscribers (seed ${result.seed})`}
          </span>
          <span className="ml-auto text-[10px] text-[var(--color-ink-soft)] font-mono">
            ran in {result.runtime_ms}ms
          </span>
        </div>
        <div className="grid grid-cols-3 gap-4 mt-5">
          <Bar label={multiSeed ? 'Mean recovery %' : 'Recovery %'} naive={naivePct} revive={revivePct} max={maxPct} suffix="%" />
          <Bar label="Contacts sent" naive={result.naive_contacts} revive={result.revive_contacts} max={Math.max(result.naive_contacts, result.revive_contacts, 1)} />
          <Bar label="Recovery attempts" naive={result.naive_attempts} revive={result.revive_attempts} max={Math.max(result.naive_attempts, result.revive_attempts, 1)} />
        </div>
      </Card>

      {multiSeed && (result.per_seed?.length ?? 0) > 0 && (
        <Card className="p-4 mt-4">
          <div className="text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold mb-3">
            Per-seed transparency
          </div>
          <table className="w-full text-[12px] font-mono">
            <thead>
              <tr className="text-left text-[var(--color-ink-muted)]">
                <th className="py-1 pr-3">seed</th>
                <th className="py-1 pr-3">naive %</th>
                <th className="py-1 pr-3">revive %</th>
                <th className="py-1 pr-3">revive INR</th>
                <th className="py-1 pr-3">revive - naive INR</th>
              </tr>
            </thead>
            <tbody>
              {result.per_seed.map((row) => (
                <tr key={row.seed} className="border-t border-[var(--color-line)]">
                  <td className="py-1 pr-3 text-[var(--color-ink)]">{row.seed}</td>
                  <td className="py-1 pr-3">{row.naive_recovery_pct.toFixed(1)}%</td>
                  <td className="py-1 pr-3 text-[var(--color-accent)] font-semibold">{row.revive_recovery_pct.toFixed(1)}%</td>
                  <td className="py-1 pr-3">Rs.{row.revive_recovered_inr.toFixed(0)}</td>
                  <td className="py-1 pr-3">Rs.{(row.revive_recovered_inr - row.naive_recovered_inr).toFixed(0)}</td>
                </tr>
              ))}
              <tr className="border-t-2 border-[var(--color-line)] font-semibold">
                <td className="py-1 pr-3">mean</td>
                <td className="py-1 pr-3">{result.mean_naive_recovery_pct.toFixed(1)}%</td>
                <td className="py-1 pr-3 text-[var(--color-accent)]">{result.mean_revive_recovery_pct.toFixed(1)}%</td>
                <td className="py-1 pr-3">Rs.{result.per_seed.reduce((s, r) => s + r.revive_recovered_inr, 0).toFixed(0)}</td>
                <td className="py-1 pr-3">Rs.{result.mean_recovered_delta_inr.toFixed(0)}</td>
              </tr>
            </tbody>
          </table>
        </Card>
      )}

      <Card className="p-5 mt-4">
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
              +{uplift.toFixed(1)}%
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

      <Card className="p-4 mt-4">
        <div className="text-[10px] text-[var(--color-ink-soft)] font-mono">
          source: {result.source} &middot; cohort: {result.cohort} &middot; n: {result.n} &middot;
          {multiSeed ? ` seeds: ${result.seeds.join(',')} &middot; mean uplift: +${result.mean_uplift_pct.toFixed(1)}%` : ` seed: ${result.seed}`}
          &middot; runtime: {result.runtime_ms}ms
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
            <div className="h-full bg-[var(--color-ink-soft)]" style={{ width: `${naiveW}%` }} />
          </div>
          <span className="w-16 text-right text-[11px] font-mono">
            {naive.toFixed(0)}{suffix}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-12 text-[10px] text-[var(--color-ink-muted)] font-mono">Cadence</span>
          <div className="flex-1 h-3 bg-[var(--color-paper-2)] rounded overflow-hidden">
            <div className="h-full bg-[var(--color-accent)]" style={{ width: `${reviveW}%` }} />
          </div>
          <span className="w-16 text-right text-[11px] font-mono">
            {revive.toFixed(0)}{suffix}
          </span>
        </div>
      </div>
    </div>
  );
};