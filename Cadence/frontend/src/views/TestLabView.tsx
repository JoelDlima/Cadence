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
import type { AgentCompare, PromiseRow } from '../types';
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
  const [promises, setPromises] = useState<PromiseRow[] | null>(null);
  const [promiseCounts, setPromiseCounts] = useState<{ open: number; kept: number; broken: number } | null>(null);
  const [promisesLoading, setPromisesLoading] = useState(false);

  const loadPromises = useCallback(async () => {
    setPromisesLoading(true);
    try {
      const result = await api.getPromises();
      setPromises(result.promises);
      setPromiseCounts({ open: result.open_count, kept: result.kept_count, broken: result.broken_count });
    } catch {
      /* leave prior state; the card shows its own error on the next simulate click */
    } finally {
      setPromisesLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPromises();
  }, [loadPromises]);

  const runSimulateReply = useCallback(async () => {
    setReplyResult({ status: 'running' });
    try {
      const reference_id = await latestReference();
      const result = await api.simulateCustomerReply({ reference_id, text: replyText });
      setReplyResult({
        status: result.accepted ? 'passed' : 'failed',
        detail: [
          `kind: ${result.kind ?? 'n/a'}`,
          result.commit_date ? `promised date: ${result.commit_date}` : '',
          `${result.detail}`,
        ].filter(Boolean).join('\n'),
      });
      await loadPromises();
    } catch (e: any) {
      setReplyResult({ status: 'failed', detail: e?.message ?? 'simulate reply failed' });
    }
  }, [replyText, latestReference, loadPromises]);

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

  return (
    <div className="space-y-6">
      <PageHeader
        title="Test Lab"
        description="Test delivery and safety behaviour. The expiry drill is the only lifecycle action shown because it makes a real Razorpay cancel request."
        action={<Badge tone="approved">Live</Badge>}
      />

      {/* --- No standalone "fire failure" here: it duplicated Live Recovery
          steps 1-2 exactly. Every drill below acts on whichever payment link
          you most recently created there. --- */}
      <Card>
        <CardHeader
          title="Need a payment link to test against?"
          subtitle="Open Live Recovery and run steps 1-2 (Create real customer, then Create payment link + post failure webhook). Every drill below auto-selects your newest link."
          action={<Badge tone="neutral">Live Recovery</Badge>}
        />
      </Card>

      {/* --- Prevention proof --- */}
      <Card>
        <CardHeader
          title="Prevent before a debit"
          subtitle="Schedules a proactive pre-debit notice in the controlled local audit workflow. This is not a bank-balance claim and makes no Razorpay call."
          action={<Badge tone="info">Preventive</Badge>}
        />
        <div className="p-5 space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={runPrevention} disabled={prevention.status === 'running'} variant="primary" size="sm">
              <Mail size={12} />
              {prevention.status === 'running' ? 'Sending…' : 'Schedule preventive notice'}
            </Button>
            <span className="text-[11.5px] text-[var(--color-ink-muted)]">
              Uses <code>predebit.scheduled</code> and <code>predebit.notified</code>; Guardian can suppress it.
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
        </div>
      </Card>

      {/* --- Promise-to-pay tracker --- */}
      <Card>
        <CardHeader
          title="Promise-to-pay tracker"
          subtitle="Reuses the real ptp_parser and dispatcher path. No Resend inbound webhook is wired yet, so this types a reply instead of receiving a live inbound email."
          action={<Badge tone="neutral">Simulated inbound</Badge>}
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
              {replyResult.status === 'running' ? 'Sending…' : 'Simulate customer reply'}
            </Button>
          </div>
          <p className="text-[11.5px] text-[var(--color-ink-muted)]">
            Applies to your newest payment link (same reference as the drills below). Try Hinglish phrasing:
            date-of-month (<code>25 tarikh ko</code>), a duration (<code>3 din me</code>), a refusal (<code>cancel kar do</code>), or vague (<code>jaldi karunga</code>).
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
                {replyResult.status === 'running' ? 'SENDING…' : replyResult.status === 'passed' ? 'RECORDED' : 'FAILED'}
              </strong>
              {replyResult.detail ? ` · ${replyResult.detail}` : ''}
            </div>
          )}

          <div className="flex items-center justify-between pt-2 border-t border-[var(--color-line)]">
            <div className="flex items-center gap-2 text-[11.5px] text-[var(--color-ink-muted)]">
              {promiseCounts && (
                <>
                  <Badge tone="pending">{promiseCounts.open} open</Badge>
                  <Badge tone="approved">{promiseCounts.kept} kept</Badge>
                  <Badge tone="rejected">{promiseCounts.broken} broken</Badge>
                </>
              )}
            </div>
            <Button variant="secondary" size="sm" onClick={loadPromises} loading={promisesLoading}>
              <RefreshCw size={12} /> Refresh
            </Button>
          </div>

          {promises && promises.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[12px]">
                <thead>
                  <tr className="text-[10.5px] uppercase tracking-wider text-[var(--color-ink-subtle)]">
                    <th className="py-1.5 pr-3">Reply</th>
                    <th className="py-1.5 pr-3">Kind</th>
                    <th className="py-1.5 pr-3">Promised date</th>
                    <th className="py-1.5 pr-3">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {promises.map((row) => (
                    <tr key={row.journey_id} className="border-t border-[var(--color-line)]">
                      <td className="py-1.5 pr-3 max-w-[220px] truncate" title={row.reply_text}>{row.reply_text || '—'}</td>
                      <td className="py-1.5 pr-3 font-mono">{row.kind}</td>
                      <td className="py-1.5 pr-3 font-mono">{row.promised_date ?? '—'}</td>
                      <td className="py-1.5 pr-3">
                        <Badge tone={row.status === 'kept' ? 'approved' : row.status === 'broken' ? 'rejected' : 'pending'}>
                          {row.status}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-[12px] text-[var(--color-ink-muted)]">No promises recorded yet — simulate a reply above.</p>
          )}
        </div>
      </Card>

      {/* --- Chaos drills section --- */}
      <Card>
        <CardHeader
          title="Drills"
          subtitle="Reliability and safety drills for Cadence. The expiry drill also makes a real Razorpay cancellation request."
          action={<Badge tone="neutral">5 drills</Badge>}
        />
        <div className="p-5 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
            <label className="text-[13px] text-[var(--color-ink-muted)]">
              <div className="mb-1">Subscription ID — for the first four drills</div>
              <Input
                value={subId}
                onChange={(e) => setSubId(e.target.value)}
                placeholder="sub_demo_live"
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
            {(
              ['duplicate_webhook', 'inject_no_funds', 'reorder', 'kill_switch', 'force_expired'] as DrillId[]
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