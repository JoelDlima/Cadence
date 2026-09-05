// Test Lab tab: agent comparison + chaos drills in one place.
//
// Replaces the previous "Results" (AgentCompareView) and "Simulation & Chaos"
// (TestbenchView) tabs after the SPA consolidation. Renders the headline
// comparison card (5-seed mean uplift) at the top, then a 2-column grid of
// four chaos drills below. Each drill has a real button that POSTs to the
// live API; failures are surfaced honestly in the UI.

import React, { useState, useCallback, useEffect } from 'react';
import { Card, CardHeader, Badge, Button, PageHeader, EmptyState, Input, cn } from '../components/primitives';
import { api } from '../services/api';
import type { AgentCompare, PromiseRow } from '../types';
import { LiveRecoveryView } from './LiveRecoveryView';
import { CheckoutView } from './CheckoutView';
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
  Mail,
  MessageSquareText,
  ShoppingCart,
  Sliders,
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
    title: 'Test Duplicate Bank Alert Protection',
    subtitle: 'Payment gateways often send duplicate alerts. Cadence ignores duplicates so customers are never double-charged or spammed.',
    icon: Copy,
  },
  inject_no_funds: {
    title: 'Test Bank Outage Spike Alert',
    subtitle: 'Simulates 3 rapid bank failures. When a bank server is down, Cadence pauses retries to avoid annoying customers.',
    icon: ZapOff,
  },
  reorder: {
    title: 'Test Delayed Network Alert Delivery',
    subtitle: 'Internet lag can deliver old alerts after new ones. Cadence orders events by bank timestamp so old alerts never undo real payments.',
    icon: Shuffle,
  },
  kill_switch: {
    title: 'Emergency Master Pause (Kill Switch)',
    subtitle: 'Instantly stops all outgoing WhatsApp messages, emails, and payment retries during maintenance.',
    icon: AlertOctagon,
  },
  force_paid: {
    title: 'Simulate Customer Completing Payment',
    subtitle: 'Marks the recovery case as paid and updates revenue metrics in the live audit log.',
    icon: CheckCircle2,
  },
  force_failed: {
    title: 'Simulate Second Payment Failure',
    subtitle: 'Simulates another failure so you can observe Cadence smart-rescheduling to another channel or time.',
    icon: XCircle,
  },
  force_expired: {
    title: 'Cancel Payment Link (Live Razorpay API)',
    subtitle: 'Sends a real cancellation call to Razorpay to expire the payment link after the recovery window ends.',
    icon: Clock4,
  },
  complete_journey: {
    title: 'One-Click Full Recovery Demo',
    subtitle: 'Simulates instant payment confirmation and closes the recovery case.',
    icon: CheckCheck,
  },
  smart: {
    title: 'Let AI Agent Decide Next Step',
    subtitle: 'The AI reads the payment history, customer hint, and safety rules to pick the optimal next action.',
    icon: Sparkles,
  },
};

interface TestLabProps {
  initialSection?: string;
}

export const TestLabView: React.FC<TestLabProps> = ({ initialSection }) => {
  const [activeSection, setActiveSection] = useState<'payment' | 'checkout' | 'benchmark' | 'chaos'>(() => {
    if (initialSection === 'checkout') return 'checkout';
    if (initialSection === 'agentcompare' || initialSection === 'benchmark') return 'benchmark';
    if (initialSection === 'testbench' || initialSection === 'chaos') return 'chaos';
    return 'payment';
  });

  useEffect(() => {
    if (initialSection === 'checkout') setActiveSection('checkout');
    else if (initialSection === 'agentcompare' || initialSection === 'benchmark') setActiveSection('benchmark');
    else if (initialSection === 'testbench' || initialSection === 'chaos') setActiveSection('chaos');
    else if (initialSection === 'live' || initialSection === 'payment') setActiveSection('payment');
  }, [initialSection]);

  // --- Comparison (top) ---
  const [result, setResult] = useState<AgentCompare | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState<number>(100);
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
  const [subId, setSubId] = useState('sub_demo_live');
  const [custId, setCustId] = useState('cust_demo_01');
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

  // Reference auto-selection alone is enough: the drills below already pick
  // up the newest payment link from Live Recovery via the 5s poll above.

  const [prevention, setPrevention] = useState<{ status: 'idle' | 'running' | 'passed' | 'failed'; detail?: string }>({ status: 'idle' });
  const runPrevention = useCallback(async () => {
    setPrevention({ status: 'running' });
    try {
      const debitAt = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();
      const result = await api.schedulePreDebitNudge({
        subscription_id: `${subId}_prevent`, customer_id: custId,
        amount_minor: 49900, debit_at: debitAt, channel: 'email',
      });
      setPrevention({
        status: 'passed',
        detail: [
          `scheduled debit: ${result.debit_at}`,
          `preventive notice: ${result.notified ? 'sent' : 'blocked'} (${result.reason})`,
          `audit: predebit.scheduled=${result.scheduled_event}, predebit.notified=${result.notified_event}`,
        ].join('\n'),
      });
    } catch (e: any) {
      setPrevention({ status: 'failed', detail: e?.message ?? 'prevention workflow failed' });
    }
  }, [subId, custId]);

  const [replyText, setReplyText] = useState('25 tarikh ko paisa bhej dunga');
  const [replyResult, setReplyResult] = useState<{ status: 'idle' | 'running' | 'passed' | 'failed'; detail?: string }>({ status: 'idle' });

  const runSimulateReply = useCallback(async () => {
    setReplyResult({ status: 'running' });
    try {
      const reference_id = await latestReference();
      const result = await api.simulateCustomerReply({ reference_id, text: replyText });
      setReplyResult({
        status: result.accepted ? 'passed' : 'failed',
        detail: [
          `Interpretation: ${result.kind === 'promised_payday' ? 'Promised Payday Commitment' : result.kind ?? 'Customer Reply'}`,
          result.commit_date ? `Promised Date: ${result.commit_date}` : '',
          `Action: ${result.detail}`,
        ].filter(Boolean).join('\n'),
      });
    } catch (e: any) {
      setReplyResult({ status: 'failed', detail: e?.message ?? 'simulate reply failed' });
    }
  }, [replyText, latestReference]);

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
          delivery_count: 2,
        });
        const [firstDelivery, replay] = res.delivery_statuses;
        if (firstDelivery !== 'accepted' || replay !== 'duplicate') {
          throw new Error(`expected accepted then duplicate; received ${res.delivery_statuses.join(', ') || 'no delivery status'}`);
        }
        detail = [
          `delivery 1: ${firstDelivery}`,
          `replay: ${replay}`,
          `one recovery journey: ${res.journey_id ?? 'not found'}${res.journey_state ? ` (${res.journey_state})` : ''}`,
        ].join('\n');
      } else if (id === 'inject_no_funds') {
        const responses = [];
        for (let i = 0; i < 3; i++) {
          responses.push(await api.injectFailure({
            subscription_id: `${subId}_${i}`,
            customer_id: `${custId}_${i}`,
            failure_code: 'insufficient_funds',
            amount_minor: 49900,
            error_description: 'Chaos drill: NO_FUNDS burst',
          }));
        }
        const openedJourneys = responses.filter((res) => res.delivery_statuses[0] === 'accepted' && res.journey_id);
        if (openedJourneys.length !== 3) {
          throw new Error(`${openedJourneys.length}/3 controlled failures opened a recovery journey`);
        }
        const anomaly = (await api.getAnomaly(10, 3)).find((row) => row.cause === 'NO_FUNDS');
        if (!anomaly) {
          throw new Error('3 journeys opened, but the NO_FUNDS anomaly was not detected');
        }
        detail = [
          `3 signed NO_FUNDS events accepted`,
          `recovery journeys opened: ${openedJourneys.length}/3`,
          `anomaly: ${anomaly.severity.toUpperCase()} — ${anomaly.count} NO_FUNDS in ${anomaly.window_minutes} min`,
          `recommendation: ${anomaly.recommendation}`,
        ].join('\n');
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

  const hasAutoRunRef = React.useRef(false);

  useEffect(() => {
    if (activeSection === 'benchmark' && !result && !loading && !hasAutoRunRef.current) {
      hasAutoRunRef.current = true;
      run();
    }
  }, [activeSection, result, loading, run]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Recovery & Test Lab"
        description="The unified operations and testing center for Cadence. Execute live Razorpay payment failure recoveries, test Shopify cart drop-offs, benchmark AI agent uplift over 100 subscribers, or trigger resilience drills."
        action={<Badge tone="approved">Operational</Badge>}
      />

      {/* Navigation Pill Bar */}
      <div className="flex items-center gap-2 border-b border-[var(--color-line)] pb-3 overflow-x-auto">
        <button
          onClick={() => setActiveSection('payment')}
          className={cn(
            "flex items-center gap-2 px-3.5 py-2 rounded-md text-[13px] font-medium transition-colors cursor-pointer",
            activeSection === 'payment'
              ? "bg-[var(--color-surface)] text-[var(--color-ink)] font-semibold border border-[var(--color-line)] shadow-xs"
              : "text-[var(--color-ink-muted)] hover:bg-[var(--color-surface-subtle)] hover:text-[var(--color-ink)]"
          )}
        >
          <Play size={14} className={activeSection === 'payment' ? "text-[var(--color-accent)]" : "text-[var(--color-ink-subtle)]"} />
          <span>1. Live Payment Recovery</span>
          <Badge tone={activeSection === 'payment' ? 'approved' : 'neutral'} className="text-[10px]">
            Razorpay Flow
          </Badge>
        </button>

        <button
          onClick={() => setActiveSection('checkout')}
          className={cn(
            "flex items-center gap-2 px-3.5 py-2 rounded-md text-[13px] font-medium transition-colors cursor-pointer",
            activeSection === 'checkout'
              ? "bg-[var(--color-surface)] text-[var(--color-ink)] font-semibold border border-[var(--color-line)] shadow-xs"
              : "text-[var(--color-ink-muted)] hover:bg-[var(--color-surface-subtle)] hover:text-[var(--color-ink)]"
          )}
        >
          <ShoppingCart size={14} className={activeSection === 'checkout' ? "text-[var(--color-accent)]" : "text-[var(--color-ink-subtle)]"} />
          <span>2. Checkout Drop-offs</span>
          <Badge tone={activeSection === 'checkout' ? 'approved' : 'neutral'} className="text-[10px]">
            Shopify UCP
          </Badge>
        </button>

        <button
          onClick={() => setActiveSection('benchmark')}
          className={cn(
            "flex items-center gap-2 px-3.5 py-2 rounded-md text-[13px] font-medium transition-colors cursor-pointer",
            activeSection === 'benchmark'
              ? "bg-[var(--color-surface)] text-[var(--color-ink)] font-semibold border border-[var(--color-line)] shadow-xs"
              : "text-[var(--color-ink-muted)] hover:bg-[var(--color-surface-subtle)] hover:text-[var(--color-ink)]"
          )}
        >
          <BarChart3 size={14} className={activeSection === 'benchmark' ? "text-[var(--color-accent)]" : "text-[var(--color-ink-subtle)]"} />
          <span>3. Batch Simulation</span>
          <Badge tone={activeSection === 'benchmark' ? 'approved' : 'neutral'} className="text-[10px]">
            100-User Lift
          </Badge>
        </button>

        <button
          onClick={() => setActiveSection('chaos')}
          className={cn(
            "flex items-center gap-2 px-3.5 py-2 rounded-md text-[13px] font-medium transition-colors cursor-pointer",
            activeSection === 'chaos'
              ? "bg-[var(--color-surface)] text-[var(--color-ink)] font-semibold border border-[var(--color-line)] shadow-xs"
              : "text-[var(--color-ink-muted)] hover:bg-[var(--color-surface-subtle)] hover:text-[var(--color-ink)]"
          )}
        >
          <ZapOff size={14} className={activeSection === 'chaos' ? "text-[var(--color-accent)]" : "text-[var(--color-ink-subtle)]"} />
          <span>4. Chaos & Safety</span>
          <Badge tone={activeSection === 'chaos' ? 'approved' : 'neutral'} className="text-[10px]">
            4 Drills
          </Badge>
        </button>
      </div>

      {/* Section 1: Live Payment Failure Recovery */}
      {activeSection === 'payment' && (
        <div className="space-y-4">
          <LiveRecoveryView />
        </div>
      )}

      {/* Section 2: Checkout Drop-offs (Shopify UCP) */}
      {activeSection === 'checkout' && (
        <div className="space-y-4">
          <CheckoutView />
        </div>
      )}

      {/* Section 3: Batch Benchmark Simulation */}
      {activeSection === 'benchmark' && (
        <div className="space-y-5">
          <Card className="p-5">
            <CardHeader
              title="Batch Recovery Benchmark (Track 03)"
              subtitle="Run a realistic multi-subscriber simulation across 100 Indian subscribers to compare Cadence's intelligent recovery agent against standard static retry schedules."
              action={
                <Button onClick={run} loading={loading} variant="primary">
                  <Play size={14} className="inline-block mr-1" />
                  Run 100-Subscriber Simulation
                </Button>
              }
            />
            <div className="mt-4 flex flex-wrap items-center gap-4 text-[13px] text-[var(--color-ink-muted)]">
              <label className="flex items-center gap-2">
                <span>Subscribers per batch:</span>
                <select
                  value={n}
                  onChange={(e) => setN(Number(e.target.value))}
                  className="bg-[var(--color-paper)] border border-[var(--color-line)] rounded px-2 py-1 text-[13px]"
                >
                  <option value={25}>25</option>
                  <option value={50}>50</option>
                  <option value={100}>100 (Official)</option>
                  <option value={200}>200</option>
                </select>
              </label>

              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={useMultiSeed}
                  onChange={(e) => setUseMultiSeed(e.target.checked)}
                  className="rounded"
                />
                <span>5-Batch Average (Runs across 5 randomized test groups for verified consistency)</span>
              </label>
            </div>
            {error && <p className="mt-3 text-[13px] text-[var(--color-rejected)]">{error}</p>}
          </Card>

          {result ? (
            <CompareResultView result={result} />
          ) : (
            <EmptyState
              title={loading ? "Running benchmark simulation..." : "Ready to run benchmark"}
              description={loading ? "Calculating recovery uplift comparing Cadence against default retry schedules across 5 randomized test groups..." : "Click 'Run 100-Subscriber Simulation' above to benchmark Cadence AI recovery against standard schedules."}
            />
          )}
        </div>
      )}

      {/* Section 4: Chaos & Safety Drills */}
      {activeSection === 'chaos' && (
        <div className="space-y-6">
          {/* Prevention proof */}
          <Card>
            <CardHeader
              title="Upcoming Payment Reminder (Pre-Debit Notice)"
              subtitle="Sends a proactive reminder 24 hours before a recurring debit so the customer keeps sufficient bank balance."
              action={<Badge tone="info">Preventive</Badge>}
            />
            <div className="p-5 space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <Button onClick={runPrevention} disabled={prevention.status === 'running'} variant="primary" size="sm">
                  <Mail size={12} />
                  {prevention.status === 'running' ? 'Sending…' : 'Schedule Pre-Debit Reminder'}
                </Button>
                <span className="text-[11.5px] text-[var(--color-ink-muted)]">
                  Sends friendly notice ahead of billing; safety guard prevents duplicate alerts.
                </span>
              </div>
              {prevention.status !== 'idle' && (
                <div
                  className="p-2.5 rounded border text-[12px] font-mono whitespace-pre-wrap"
                  style={{
                    backgroundColor: prevention.status === 'running'
                      ? 'var(--color-info-wash)'
                      : prevention.status === 'passed'
                        ? 'var(--color-approved-wash)'
                        : 'var(--color-rejected-wash)',
                    borderColor: prevention.status === 'running'
                      ? 'var(--color-info)'
                      : prevention.status === 'passed'
                        ? 'var(--color-approved)'
                        : 'var(--color-rejected)',
                    color: prevention.status === 'running'
                      ? 'var(--color-info)'
                      : prevention.status === 'passed'
                        ? 'var(--color-approved)'
                        : 'var(--color-rejected)',
                  }}
                >
                  <strong>
                    {prevention.status === 'running' ? 'SENDING…' : prevention.status === 'passed' ? 'RECORDED' : 'FAILED'}
                  </strong>
                  {prevention.detail ? ` · ${prevention.detail}` : ''}
                </div>
              )}
              <div className="flex items-center justify-between pt-2 border-t border-[var(--color-line)] text-[12px] text-[var(--color-ink-muted)]">
                <span>All scheduled pre-debit notices are tracked live in the Upcoming Payment Reminders panel on the Dashboard.</span>
                <button
                  type="button"
                  onClick={() => { window.location.hash = 'dashboard'; }}
                  className="text-[var(--color-accent)] hover:underline font-medium cursor-pointer"
                >
                  View in Dashboard &rarr;
                </button>
              </div>
            </div>
          </Card>

          {/* Promise-to-pay tracker */}
          <Card>
            <CardHeader
              title="Customer Payday Commitment Tracker"
              subtitle="Parses natural Hindi and English replies like '25 tarikh ko bhej dunga' and pauses reminders until their promised payday."
              action={<Badge tone="neutral">Interactive Demo</Badge>}
            />
            <div className="p-5 space-y-4">
              <div className="flex flex-col sm:flex-row gap-3">
                <Input
                  value={replyText}
                  onChange={(e) => setReplyText(e.target.value)}
                  placeholder="e.g. 25 tarikh ko paisa bhej dunga"
                  className="flex-1 text-[14px]"
                />
                <Button onClick={runSimulateReply} disabled={replyResult.status === 'running'} variant="primary" size="sm">
                  <MessageSquareText size={12} />
                  {replyResult.status === 'running' ? 'Processing…' : 'Simulate Customer Reply'}
                </Button>
              </div>
              <p className="text-[11.5px] text-[var(--color-ink-muted)]">
                Applies to your newest recovery payment link. Try Hinglish phrasing:
                date-of-month (<code>25 tarikh ko</code>), a duration (<code>3 din me</code>), or a cancellation request (<code>cancel kar do</code>).
              </p>
              {replyResult.status !== 'idle' && (
                <div
                  className="p-2.5 rounded border text-[12px] font-mono whitespace-pre-wrap"
                  style={{
                    backgroundColor: replyResult.status === 'running'
                      ? 'var(--color-info-wash)'
                      : replyResult.status === 'passed'
                        ? 'var(--color-approved-wash)'
                        : 'var(--color-rejected-wash)',
                    borderColor: replyResult.status === 'running'
                      ? 'var(--color-info)'
                      : replyResult.status === 'passed'
                        ? 'var(--color-approved)'
                        : 'var(--color-rejected)',
                    color: replyResult.status === 'running'
                      ? 'var(--color-info)'
                      : replyResult.status === 'passed'
                        ? 'var(--color-approved)'
                        : 'var(--color-rejected)',
                  }}
                >
                  <strong>
                    {replyResult.status === 'running' ? 'PROCESSING…' : replyResult.status === 'passed' ? 'RECORDED' : 'FAILED'}
                  </strong>
                  {replyResult.detail ? ` · ${replyResult.detail}` : ''}
                </div>
              )}

              <div className="flex items-center justify-between pt-2 border-t border-[var(--color-line)] text-[12px] text-[var(--color-ink-muted)]">
                <span>Active customer commitments are monitored live in the Customer Payday Commitments panel on the Dashboard.</span>
                <button
                  type="button"
                  onClick={() => { window.location.hash = 'dashboard'; }}
                  className="text-[var(--color-accent)] hover:underline font-medium cursor-pointer"
                >
                  View in Dashboard &rarr;
                </button>
              </div>
            </div>
          </Card>

          {/* Drills */}
          <Card>
            <CardHeader
              title="System Resilience &amp; Safety Drills"
              subtitle="Run live drills to verify that Cadence handles bank outages, duplicates, and link expirations without human error."
              action={<Badge tone="neutral">4 Safety Drills</Badge>}
            />
            <div className="p-5 space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
                <label className="text-[13px] text-[var(--color-ink-muted)]">
                  <div className="mb-1">Subscription ID — for bank alert &amp; outage drills</div>
                  <Input
                    value={subId}
                    onChange={(e) => setSubId(e.target.value)}
                    placeholder="sub_demo_live"
                    className="numeric text-[14px]"
                  />
                </label>
                <label className="text-[13px] text-[var(--color-ink-muted)]">
                  <div className="mb-1">Reference ID — for payment link cancellation</div>
                  <Input
                    value={refId}
                    onChange={(e) => setRefId(e.target.value)}
                    placeholder={refAuto ?? 'filled in automatically'}
                    className="numeric text-[14px]"
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
                    No payment link yet. Click <span className="font-medium">1. Live Payment Recovery</span>{' '}
                    above to create a link and these drills will point at it.
                  </>
                )}
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {(
                  ['duplicate_webhook', 'inject_no_funds', 'reorder', 'force_expired'] as DrillId[]
                ).map((id) => {
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
      )}
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
            Batch Breakdown (5 Randomized Test Groups)
          </div>
          <table className="w-full text-[12px] font-mono">
            <thead>
              <tr className="text-left text-[var(--color-ink-muted)]">
                <th className="py-1 pr-3">Test Group</th>
                <th className="py-1 pr-3">Standard Schedule %</th>
                <th className="py-1 pr-3">Cadence AI %</th>
                <th className="py-1 pr-3">Cadence Recovered</th>
                <th className="py-1 pr-3">Revenue Gain</th>
              </tr>
            </thead>
            <tbody>
              {result.per_seed.map((row) => (
                <tr key={row.seed} className="border-t border-[var(--color-line)]">
                  <td className="py-1 pr-3 text-[var(--color-ink)]">Batch #{row.seed}</td>
                  <td className="py-1 pr-3">{row.naive_recovery_pct.toFixed(1)}%</td>
                  <td className="py-1 pr-3 text-[var(--color-accent)] font-semibold">{row.cadence_recovery_pct.toFixed(1)}%</td>
                  <td className="py-1 pr-3">Rs.{row.cadence_recovered_inr.toFixed(0)}</td>
                  <td className="py-1 pr-3">Rs.{(row.cadence_recovered_inr - row.naive_recovered_inr).toFixed(0)}</td>
                </tr>
              ))}
              <tr className="border-t-2 border-[var(--color-line)] font-semibold">
                <td className="py-1 pr-3">Average</td>
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
              Average Revenue Uplift
            </div>
            <div className="text-2xl font-semibold text-[var(--color-accent)] mt-1 font-mono">
              +{uplift.toFixed(1)}%
            </div>
            <div className="text-[10px] uppercase tracking-wider text-[var(--color-ink-muted)] mt-1">
              Calibrated outcome simulation &middot; 5 test groups
            </div>
          </div>
          <div className="flex-1">
            <div className="text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold">
              Net Extra Revenue Won
            </div>
            <div className="text-2xl font-semibold text-[var(--color-ink)] mt-1 font-mono">
              Rs.{result.recovered_delta.toFixed(2)}
            </div>
          </div>
          <div className="flex-1">
            <div className="text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold">
              Instant Rule Decisions
            </div>
            <div className="text-2xl font-semibold text-[var(--color-ink)] mt-1 font-mono">
              {result.fast_path_pct.toFixed(0)}%
            </div>
            <div className="text-[10px] text-[var(--color-ink-soft)] mt-1">
              Deterministic (Zero AI token latency)
            </div>
          </div>
        </div>
      </Card>

      <Card className="p-4 mt-4">
        <div className="text-[11px] text-[var(--color-ink-soft)] font-mono">
          source: {result.source} &middot; cohort: {result.cohort} &middot; n: {result.n} &middot;
          {multiSeed ? ` test groups: ${result.seeds.join(', ')} &middot; average uplift: +${result.mean_uplift_pct.toFixed(1)}%` : ` test group: ${result.seed}`}
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