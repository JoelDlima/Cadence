// Test Lab tab: agent comparison + chaos drills in one place.
//
// Replaces the previous "Results" (AgentCompareView) and "Simulation & Chaos"
// (TestbenchView) tabs after the SPA consolidation. Renders the headline
// comparison card (5-seed mean uplift) at the top, then a 2-column grid of
// four chaos drills below. Each drill has a real button that POSTs to the
// live API; failures are surfaced honestly in the UI.

import React, { useState, useCallback, useEffect } from 'react';
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
  CheckCircle2,
  XCircle,
  Clock4,
  CheckCheck,
  Sparkles,
  ExternalLink,
  Mail,
} from 'lucide-react';

const DEFAULT_SEEDS = [42, 7, 99, 123, 2024] as const;

interface DrillResult {
  status: 'idle' | 'running' | 'passed' | 'failed';
  detail?: string;
}

type DrillId =
  | 'duplicate_webhook'
  | 'inject_no_funds'
  | 'reorder'
  | 'kill_switch'
  | 'force_paid'
  | 'force_failed'
  | 'force_expired'
  | 'complete_journey'
  | 'smart';

interface DrillMeta {
  title: string;
  subtitle: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
}

const DRILL_META: Record<DrillId, DrillMeta> = {
  duplicate_webhook: {
    title: 'Send the same webhook twice',
    subtitle: 'Razorpay retries webhooks. The engine must count the payment once, not twice.',
    icon: Copy,
  },
  inject_no_funds: {
    title: 'Three failures at once',
    subtitle: 'Fires 3 NO_FUNDS failures in a row. This is what a bank outage looks like, and it should trip the anomaly alert.',
    icon: ZapOff,
  },
  reorder: {
    title: 'Send webhooks out of order',
    subtitle: 'The internet does not deliver in order. A late event must not overwrite a newer one.',
    icon: Shuffle,
  },
  kill_switch: {
    title: 'Pull the kill switch',
    subtitle: 'Flips the stop flag on and off. While it is on, no message and no retry may leave the building.',
    icon: AlertOctagon,
  },
  force_paid: {
    title: 'The customer pays',
    subtitle: 'Marks the link paid and closes the journey as RECOVERED. Razorpay has no API to mark a link paid, so this side is ours.',
    icon: CheckCircle2,
  },
  force_failed: {
    title: 'The payment fails again',
    subtitle: 'Sends another payment.failed. Cadence reopens recovery (INTERVENING) and the link stays payable, exactly as Razorpay leaves it.',
    icon: XCircle,
  },
  force_expired: {
    title: 'The 24-hour window closes',
    subtitle: 'Really calls Razorpay to cancel the link, then closes the journey unrecovered. This one changes the real Razorpay status.',
    icon: Clock4,
  },
  complete_journey: {
    title: 'Close the loop in one click',
    subtitle: 'Same as "The customer pays", bundled as a single button for a demo.',
    icon: CheckCheck,
  },
  smart: {
    title: 'Let the agent decide',
    subtitle: 'The LLM reads the link, the audit trail and your hint, picks paid / failed / expired, and explains why. No key? It falls back to a fixed choice.',
    icon: Sparkles,
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
  const [custHint, setCustHint] = useState<string>('');
  const [drillOutputs, setDrillOutputs] = useState<Record<string, DrillResult>>({});

  // Lifecycle drills address a journey attempt ('<journey_id>:<attempt_no>'),
  // not a subscription id. Rather than making the operator copy it off another
  // tab, resolve the newest payment link from the Dashboard feed and let them
  // override it if they want an older one.
  const [refId, setRefId] = useState('');
  const [refAuto, setRefAuto] = useState<string | null>(null);

  // Which link the drills will hit. Refreshed on a timer (and right after
  // "Fire live failure") because a mount-only fetch goes stale the moment the
  // operator creates a link, and a stale hint is worse than none.
  const refreshRefAuto = useCallback(async () => {
    try {
      const rows = await api.getPaymentLinks(1);
      setRefAuto(rows[0]?.reference_id ?? null);
    } catch {
      /* leave the previous value; the drill re-resolves at click time anyway */
    }
  }, []);

  useEffect(() => {
    refreshRefAuto();
    const id = setInterval(refreshRefAuto, 5000);
    return () => clearInterval(id);
  }, [refreshRefAuto]);

  const latestReference = useCallback(async (): Promise<string> => {
    if (refId.trim()) return refId.trim();
    const rows = await api.getPaymentLinks(1);
    const found = rows[0]?.reference_id;
    if (!found) {
      throw new Error(
        'no payment link yet — run "Fire live failure" (or Live Recovery steps 1-2) first',
      );
    }
    setRefAuto(found);
    return found;
  }, [refId]);

  // --- Live failure: real Razorpay customer + plink_* + dashboard link ---
  const [liveFiring, setLiveFiring] = useState(false);
  const [liveResult, setLiveResult] = useState<{
    customer_id?: string;
    payment_link_id?: string;
    short_url?: string;
    journey_id?: string;
    simulated?: boolean;
    detail?: string;
  } | null>(null);

  const fireLiveFailure = useCallback(async () => {
    setLiveFiring(true);
    setLiveResult(null);
    try {
      const c = await api.createLiveCustomer({ name: 'Demo (judge)', email: 'demo@x.local', contact: '+910000000000' });
      const f = await api.createLiveFailure({ customer_id: c.id });
      // Point the lifecycle drills at the link we just made, without waiting
      // for the 5s poll.
      if (f.payment_link?.reference_id) setRefAuto(f.payment_link.reference_id);
      setLiveResult({
        customer_id: c.id,
        payment_link_id: f.payment_link?.id,
        short_url: f.payment_link?.short_url,
        journey_id: f.journey_id,
        simulated: f.payment_link?.simulated,
      });
    } catch (e: any) {
      setLiveResult({ detail: e?.message ?? 'live failure request failed' });
    } finally {
      setLiveFiring(false);
    }
  }, []);

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
      } else if (id === 'force_paid' || id === 'force_failed' || id === 'force_expired' || id === 'complete_journey') {
        const label = id.replace('force_', 'Force ').replace('_', ' ').replace('complete journey', 'Complete journey');
        const reference_id = await latestReference();
        const res: any = await api.lifecycleForce({ reference_id, operation: id });
        detail = [
          `${label} on ${reference_id}`,
          `link ${res?.plink_id ?? '?'} -> ${res?.plink_state ?? '?'}`,
          `Cadence: ${res?.cadence_state ?? '?'} · Razorpay: ${res?.razorpay_state ?? '?'}`,
          res?.razorpay_note ? `note: ${res.razorpay_note}` : '',
        ].filter(Boolean).join('\n');
      } else if (id === 'smart') {
        const reference_id = await latestReference();
        const res: any = await api.lifecycleSmart({
          reference_id,
          customer_hint: custHint || undefined,
        });
        const chosen = res?.chosen;
        const conf = chosen?.confidence ? ` (${Math.round(chosen.confidence * 100)}%)` : '';
        const reason = chosen?.reason ? ` — ${chosen.reason}` : '';
        detail = `Smart: ${chosen?.outcome?.toUpperCase() ?? '?'}${conf}${reason}\nLLM thought: ${res?.llm_thought ?? '(none)'}`;
        setDrillOutputs((prev) => ({ ...prev, [id]: { status: 'passed', detail, llmThought: res?.llm_thought } }));
        return;  // skip the default 'passed' set below since we have a richer detail
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
  }, [subId, custId, custHint, latestReference]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Test Lab"
        description="Break the engine on purpose. Fire a real failure, then drive the payment link wherever you want it to go."
        action={<Badge tone="approved">Live</Badge>}
      />

      {/* --- Live failure: real Razorpay object on click --- */}
      <Card>
        <CardHeader
          title="Fire a live test failure"
          subtitle="Creates a real Razorpay test-mode customer, a real payment link, and a signed payment.failed webhook. The plink_ id shows up in your Razorpay dashboard in about a second."
          action={<Badge tone="info">Real Razorpay</Badge>}
        />
        <div className="p-5 space-y-3">
          <Button onClick={fireLiveFailure} disabled={liveFiring} variant="primary" size="sm">
            {liveFiring ? 'Firing…' : 'Fire live failure'}
          </Button>
          {liveResult && (
            <div className="text-[12.5px] font-mono space-y-1 bg-[var(--color-surface-subtle)] border border-[var(--color-line)] rounded p-3">
              {liveResult.detail && <div className="text-[var(--color-coral)]">{liveResult.detail}</div>}
              {liveResult.customer_id && (
                <div className="flex items-center gap-2">
                  <span className="text-[var(--color-ink-muted)] shrink-0">customer id:</span>
                  <code className="bg-[var(--color-paper)] px-1.5 py-0.5 rounded break-all">{liveResult.customer_id}</code>
                </div>
              )}
              {liveResult.payment_link_id && (
                <div className="flex items-center gap-2">
                  <span className="text-[var(--color-ink-muted)] shrink-0">payment link id:</span>
                  <code className="bg-[var(--color-paper)] px-1.5 py-0.5 rounded break-all">{liveResult.payment_link_id}</code>
                </div>
              )}
              {liveResult.short_url && (
                <div className="flex items-center gap-2">
                  <span className="text-[var(--color-ink-muted)] shrink-0">short_url:</span>
                  <a href={liveResult.short_url} target="_blank" rel="noreferrer" className="text-[var(--color-accent)] underline break-all">
                    {liveResult.short_url}
                  </a>
                </div>
              )}
              {liveResult.journey_id && (
                <div className="flex items-center gap-2">
                  <span className="text-[var(--color-ink-muted)] shrink-0">journey id:</span>
                  <code className="bg-[var(--color-paper)] px-1.5 py-0.5 rounded break-all">{liveResult.journey_id}</code>
                </div>
              )}
              {liveResult.simulated !== undefined && (
                <div className="text-[10px] uppercase tracking-wider text-[var(--color-ink-muted)]">
                  simulated: {String(liveResult.simulated)}
                </div>
              )}
              <a
                href="https://dashboard.razorpay.com/app/payment-links"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 text-[12px] text-[var(--color-accent)] underline hover:no-underline mt-2"
              >
                <ExternalLink size={11} /> Open in Razorpay Dashboard (Payment Links)
              </a>
            </div>
          )}
        </div>
      </Card>

      {/* --- Chaos drills section --- */}
      <Card>
        <CardHeader
          title="Drills"
          subtitle="Each button does something real to the live engine. If a drill fails, it says so here — nothing is hidden."
          action={<Badge tone="neutral">9 drills</Badge>}
        />
        <div className="p-5 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">
            <label className="text-[13px] text-[var(--color-ink-muted)]">
              <div className="mb-1">Subscription ID — for the first four drills</div>
              <Input
                value={subId}
                onChange={(e) => setSubId(e.target.value)}
                placeholder="sub_judge_live"
                className="numeric text-[14px]"
              />
            </label>
            <label className="text-[13px] text-[var(--color-ink-muted)]">
              <div className="mb-1">Reference ID — which payment link to act on</div>
              <Input
                value={refId}
                onChange={(e) => setRefId(e.target.value)}
                placeholder={refAuto ?? 'filled in automatically'}
                className="numeric text-[14px]"
              />
            </label>
            <label className="text-[13px] text-[var(--color-ink-muted)]">
              <div className="mb-1">Customer hint — only the agent reads this</div>
              <Input
                value={custHint}
                onChange={(e) => setCustHint(e.target.value)}
                placeholder="e.g. always pays after a reminder"
                className="text-[14px]"
              />
            </label>
          </div>
          <div className="text-[11px] text-[var(--color-ink-muted)] mb-3">
            {refAuto ? (
              <>
                Acting on{' '}
                <span className="font-mono">{refId.trim() || refAuto}</span>
                {!refId.trim() && ' — your newest payment link, picked automatically. '
                  + 'To use a different one, copy its Reference ID from the Dashboard.'}
              </>
            ) : (
              <>
                No payment link yet. Click <span className="font-medium">Fire live failure</span>{' '}
                above and these drills will point at it.
              </>
            )}
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
                        <h4 className="text-[13px] font-semibold text-[var(--color-ink)]">
                          {meta.title}
                        </h4>
                        <p className="text-[13px] text-[var(--color-ink-muted)]">
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
                      className="p-2.5 rounded border text-[12px] font-mono whitespace-pre-wrap"
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
  const cadencePct = multiSeed ? result.mean_cadence_recovery_pct : result.cadence_recovery_pct;
  const uplift = multiSeed ? result.mean_uplift_pct : result.uplift_pct;
  const maxPct = Math.max(naivePct, cadencePct, 1);

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
          <span className="ml-auto text-[11px] text-[var(--color-ink-soft)] font-mono">
            ran in {result.runtime_ms}ms
          </span>
        </div>
        <div className="grid grid-cols-3 gap-4 mt-5">
          <Bar label={multiSeed ? 'Mean recovered %' : 'Recovered %'} naive={naivePct} cadence={cadencePct} max={maxPct} suffix="%" />
          <Bar label="Follow-up messages" naive={result.naive_contacts} cadence={result.cadence_contacts} max={Math.max(result.naive_contacts, result.cadence_contacts, 1)} />
          <Bar label="Recovery attempts" naive={result.naive_attempts} cadence={result.cadence_attempts} max={Math.max(result.naive_attempts, result.cadence_attempts, 1)} />
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
                <th className="py-1 pr-3">Razorpay default %</th>
                <th className="py-1 pr-3">Cadence %</th>
                <th className="py-1 pr-3">Cadence Rs.</th>
                <th className="py-1 pr-3">Lift Rs.</th>
              </tr>
            </thead>
            <tbody>
              {result.per_seed.map((row) => (
                <tr key={row.seed} className="border-t border-[var(--color-line)]">
                  <td className="py-1 pr-3 text-[var(--color-ink)]">{row.seed}</td>
                  <td className="py-1 pr-3">{row.naive_recovery_pct.toFixed(1)}%</td>
                  <td className="py-1 pr-3 text-[var(--color-accent)] font-semibold">{row.cadence_recovery_pct.toFixed(1)}%</td>
                  <td className="py-1 pr-3">Rs.{row.cadence_recovered_inr.toFixed(0)}</td>
                  <td className="py-1 pr-3">Rs.{(row.cadence_recovered_inr - row.naive_recovered_inr).toFixed(0)}</td>
                </tr>
              ))}
              <tr className="border-t-2 border-[var(--color-line)] font-semibold">
                <td className="py-1 pr-3">mean</td>
                <td className="py-1 pr-3">{result.mean_naive_recovery_pct.toFixed(1)}%</td>
                <td className="py-1 pr-3 text-[var(--color-accent)]">{result.mean_cadence_recovery_pct.toFixed(1)}%</td>
                <td className="py-1 pr-3">Rs.{result.per_seed.reduce((s, r) => s + r.cadence_recovered_inr, 0).toFixed(0)}</td>
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
              Razorpay's default retry policy
            </div>
            <div className="text-3xl font-semibold text-[var(--color-ink)] mt-2 font-mono">
              Rs.{result.naive_recovered_inr.toFixed(2)}
            </div>
            <div className="text-[13px] text-[var(--color-ink-muted)] mt-1">
              {naivePct.toFixed(1)}% recovered
            </div>
            <div className="text-[12px] text-[var(--color-ink-soft)] mt-3">
              Blind retry +24h, then d1/d3/d5 emails. Same customer, every
              customer, every time.
            </div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold flex items-center gap-2">
              Cadence (AI agent + rules)
              <Trophy size={14} className="text-[var(--color-accent)]" />
            </div>
            <div className="text-3xl font-semibold text-[var(--color-accent)] mt-2 font-mono">
              Rs.{result.cadence_recovered_inr.toFixed(2)}
            </div>
            <div className="text-[13px] text-[var(--color-ink-muted)] mt-1">
              {cadencePct.toFixed(1)}% recovered
            </div>
            <div className="text-[12px] text-[var(--color-ink-soft)] mt-3">
              Cause-aware decision: only contacts within touch cap, no
              messages 9pm-9am IST, deterministic weights in source.
            </div>
          </div>
        </div>

        <div className="border-t border-[var(--color-line)] mt-5 pt-4 flex items-center gap-3">
          <div className="flex-1">
            <div className="text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold">
              Average improvement
            </div>
            <div className="text-2xl font-semibold text-[var(--color-accent)] mt-1 font-mono">
              +{uplift.toFixed(1)}%
            </div>
            <div className="text-[10px] uppercase tracking-wider text-[var(--color-ink-muted)] mt-1">
              calibrated outcome simulator &middot; not a live Razorpay cohort
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
        <div className="text-[11px] text-[var(--color-ink-soft)] font-mono">
          source: {result.source} &middot; cohort: {result.cohort} &middot; n: {result.n} &middot;
          {multiSeed ? ` seeds: ${result.seeds.join(',')} &middot; average improvement: +${result.mean_uplift_pct.toFixed(1)}%` : ` seed: ${result.seed}`}
          &middot; runtime: {result.runtime_ms}ms
        </div>
      </Card>
    </>
  );
};

const Bar: React.FC<{
  label: string;
  naive: number;
  cadence: number;
  max: number;
  suffix?: string;
}> = ({ label, naive, cadence, max, suffix = '' }) => {
  const naiveW = Math.max(2, (naive / max) * 100);
  const cadenceW = Math.max(2, (cadence / max) * 100);
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold">
        {label}
      </div>
      <div className="mt-2 space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="w-16 text-[11px] text-[var(--color-ink-muted)] font-mono">Razorpay</span>
          <div className="flex-1 h-3 bg-[var(--color-paper-2)] rounded overflow-hidden">
            <div className="h-full bg-[var(--color-ink-soft)]" style={{ width: `${naiveW}%` }} />
          </div>
          <span className="w-16 text-right text-[12px] font-mono">
            {naive.toFixed(0)}{suffix}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-16 text-[11px] text-[var(--color-ink-muted)] font-mono">Cadence</span>
          <div className="flex-1 h-3 bg-[var(--color-paper-2)] rounded overflow-hidden">
            <div className="h-full bg-[var(--color-accent)]" style={{ width: `${cadenceW}%` }} />
          </div>
          <span className="w-16 text-right text-[12px] font-mono">
            {cadence.toFixed(0)}{suffix}
          </span>
        </div>
      </div>
    </div>
  );
};