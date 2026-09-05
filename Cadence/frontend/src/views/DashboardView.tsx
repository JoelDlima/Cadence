//
// Dashboard — the Razorpay Payment Links page, but with the agent's reasoning
// attached to every row.
//
// Why it looks like Razorpay: operators already know that table. Showing the
// same Amount / Status / Created / Reference Id / Customer columns means the
// only new thing on screen is what Cadence added — the journey state, the
// root cause, and the audit trail behind each status change.
//
// Data comes from the local engine, not from Razorpay: /api/dashboard/*
// rebuilds these rows out of the hash-chained event log, so the table can
// never disagree with the audit trail. Polling is 5s for rows and 10s for
// counters, which is why a link created on the Live Recovery tab lands here
// within a few seconds.

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowUpRight, BellRing, Clock, ExternalLink, IndianRupee, Link2, MessageSquareText, RefreshCw,
  ShieldCheck, TrendingDown, TrendingUp, Wallet, X,
} from 'lucide-react';
import {
  Badge, Button, Card, CardHeader, EmptyState, PageHeader, Skeleton, cn,
  type BadgeTone,
} from '../components/primitives';
import { api, inrFormatter } from '../services/api';
import type {
  AgentCompare, AgentReasoning, CheckoutIdleScan, CloudPlinks, DashboardStats, PaymentLinkRow, PreDebitHistory, PromiseList, TimelineEvent,
} from '../types';

const ROWS_POLL_MS = 5000;
const STATS_POLL_MS = 10000;
const RAZORPAY_LINKS_URL = 'https://dashboard.razorpay.com/app/payment-links';

/** Tabs mirror Razorpay's own Payment Links filter chips. */
const TABS: { id: string; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'created', label: 'Created' },
  { id: 'partially_paid', label: 'Partially paid' },
  { id: 'paid', label: 'Paid' },
  { id: 'cancelled', label: 'Cancelled' },
  { id: 'expired', label: 'Expired' },
];

const STATUS_TONE: Record<string, BadgeTone> = {
  paid: 'approved',
  created: 'pending',
  partially_paid: 'info',
  cancelled: 'rejected',
  expired: 'rejected',
};

const STATUS_LABEL: Record<string, string> = {
  paid: 'Paid',
  created: 'Created',
  partially_paid: 'Partially paid',
  cancelled: 'Cancelled',
  expired: 'Expired',
};

const JOURNEY_TONE: Record<string, BadgeTone> = {
  RECOVERED: 'approved',
  CLOSED_UNRECOVERED: 'rejected',
  ESCALATED: 'rejected',
  INTERVENING: 'pending',
  OPENED: 'pending',
  CLASSIFIED: 'neutral',
  WAITING_OUTCOME: 'info',
  HUMAN_REVIEW: 'info',
};

function inr(major: number): string {
  return inrFormatter.format(major);
}

function fmtDateTime(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
    hour12: false,
  });
}

function relative(iso?: string | null): string {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}

/* --------------------------------------------------------------- stat card */

function StatCard({
  label, value, sub, icon: Icon, accent,
}: {
  label: string;
  value: string;
  sub?: string;
  icon: typeof Wallet;
  accent: 'approved' | 'rejected' | 'pending' | 'info' | 'neutral';
}) {
  const color = accent === 'neutral' ? 'var(--color-ink)' : `var(--color-${accent})`;
  const wash = accent === 'neutral' ? 'var(--color-surface-subtle)' : `var(--color-${accent}-wash)`;
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-ink-subtle)]">
            {label}
          </p>
          <p className="numeric mt-1.5 text-[22px] font-semibold leading-none text-[var(--color-ink)]">
            {value}
          </p>
          {sub && (
            <p className="mt-1.5 truncate text-[11.5px] text-[var(--color-ink-muted)]">{sub}</p>
          )}
        </div>
        <span
          className="shrink-0 rounded-md p-2"
          style={{ backgroundColor: wash, color }}
          aria-hidden
        >
          <Icon size={16} />
        </span>
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------- row drawer */

function RowDrawer({ row, onClose }: { row: PaymentLinkRow; onClose: () => void }) {
  const [reasoning, setReasoning] = useState<AgentReasoning | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      api.getJourneyReasoning(row.journey_id).catch(() => null),
      api.getTimeline(row.journey_id).catch(() => [] as TimelineEvent[]),
    ])
      .then(([r, evs]) => {
        if (cancelled) return;
        setReasoning(r);
        setEvents(evs);
        setError(r ? null : 'agent reasoning unavailable for this journey');
      })
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [row.journey_id]);

  // The bandit's chosen arm and the Guardian's verdict both live in the chain.
  const banditArm = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i -= 1) {
      const p = events[i].payload || {};
      if (events[i].type === 'bandit.ranked' && p.top) return String(p.top);
      if (events[i].type === 'action.executed' && p.kind) return String(p.kind);
    }
    return null;
  }, [events]);

  const vetoes = useMemo(
    () => events.filter((e) => e.type === 'intervention.vetoed').length,
    [events],
  );

  // Close on Escape: a drawer that traps the keyboard is an accessibility bug.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true"
         aria-label={`Payment link ${row.plink_id}`}>
      <div className="absolute inset-0 bg-black/35 backdrop-blur-sm" onClick={onClose} aria-hidden />
      <aside className="relative h-full w-full max-w-xl overflow-y-auto border-l border-[var(--color-line)] bg-[var(--color-surface)] shadow-[var(--shadow-raised)]">
        <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-[var(--color-line)] bg-[var(--color-surface)] px-5 py-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="numeric text-[15px] font-semibold">{inr(row.amount_inr)}</span>
              <Badge tone={STATUS_TONE[row.status] ?? 'neutral'}>
                {STATUS_LABEL[row.status] ?? row.status}
              </Badge>
              {row.simulated && <Badge tone="neutral">simulated</Badge>}
            </div>
            <p className="mt-1 truncate font-mono text-[11.5px] text-[var(--color-ink-subtle)]">
              {row.plink_id}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close details"
            className="rounded-md p-1.5 text-[var(--color-ink-muted)] hover:bg-[var(--color-surface-subtle)]"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-5 px-5 py-5">
          {/* Facts */}
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-[12.5px]">
            {([
              ['Customer', row.customer_id ?? '—'],
              ['Recovery Case ID', row.journey_id],
              ['Subscription ID', row.subscription_id ?? '—'],
              ['Reference Code', row.reference_id || '—'],
              ['Amount Paid', inr(row.amount_paid_minor / 100)],
              ['Contact Attempts', `${row.attempts_used} retry / ${row.touches_used} touch`],
              ['Bank Error Code', row.failure_code ?? '—'],
              ['Failure Diagnosis', row.root_cause ?? 'Analyzing bank response'],
              ['Chosen Recovery Path', banditArm ?? 'Evaluating options'],
              ['Safety Blocks (Quiet Hours / Spam Cap)', String(vetoes)],
              ['Created At', fmtDateTime(row.created_at)],
              ['Last Updated', fmtDateTime(row.updated_at)],
            ] as [string, string][]).map(([k, v]) => (
              <div key={k} className="min-w-0">
                <dt className="text-[10.5px] font-semibold uppercase tracking-wider text-[var(--color-ink-subtle)]">
                  {k}
                </dt>
                <dd className="mt-0.5 truncate font-mono text-[var(--color-ink)]" title={v}>{v}</dd>
              </div>
            ))}
          </dl>

          <div className="flex flex-wrap gap-2">
            {row.journey_state && (
              <Badge tone={JOURNEY_TONE[row.journey_state] ?? 'neutral'}>
                Case Status: {row.journey_state}
              </Badge>
            )}
            {row.short_url && (
              <a href={row.short_url} target="_blank" rel="noreferrer"
                 className="inline-flex items-center gap-1 text-[12px] text-[var(--color-accent)] underline hover:no-underline">
                <Link2 size={12} /> Open Payment Page
              </a>
            )}
            <a href={RAZORPAY_LINKS_URL} target="_blank" rel="noreferrer"
               className="inline-flex items-center gap-1 text-[12px] text-[var(--color-accent)] underline hover:no-underline">
              <ExternalLink size={12} /> Find in Razorpay Dashboard
            </a>
          </div>

          {/* Agent reasoning */}
          <Card>
            <CardHeader
              title="AI Decision &amp; Action Log"
              subtitle="Plain-English explanation of what the AI observed, what it calculated, and what action it took."
            />
            <div className="space-y-3 px-5 py-4">
              {loading && <><Skeleton className="h-4 w-2/3" /><Skeleton className="h-4 w-1/2" /></>}
              {!loading && error && (
                <p className="text-[12.5px] text-[var(--color-ink-muted)]">{error}</p>
              )}
              {!loading && reasoning?.steps?.map((step) => (
                <div key={step.step} className="rounded-md border border-[var(--color-line)] bg-[var(--color-surface-subtle)] px-3.5 py-3">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-ink-subtle)]">
                    {step.title}
                  </p>
                  <p className="mt-1 text-[13px] leading-relaxed text-[var(--color-ink)]">
                    {step.detail || '—'}
                  </p>
                  {step.event_refs?.length > 0 && (
                    <p className="mt-1.5 font-mono text-[10.5px] text-[var(--color-ink-subtle)]">
                      Event #{step.event_refs.map((r) => r.seq).join(', ')}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </Card>

          {/* Lifecycle trail */}
          <Card>
            <CardHeader title="Status Timeline" subtitle="Chronological history of every status update, oldest first." />
            <div className="px-5 py-4">
              {row.lifecycle.length === 0 ? (
                <p className="text-[12.5px] text-[var(--color-ink-muted)]">
                  Created. Nothing has changed yet.
                </p>
              ) : (
                <ol className="space-y-2.5">
                  {row.lifecycle.map((entry, i) => (
                    <li key={`${entry.at}-${i}`} className="flex items-start gap-3">
                      <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-ink-subtle)]" />
                      <div className="min-w-0">
                        <p className="text-[12.5px] text-[var(--color-ink)]">
                          <span className="font-medium">{entry.to_status}</span>
                          <span className="text-[var(--color-ink-subtle)]"> · {entry.source}</span>
                        </p>
                        <p className="font-mono text-[10.5px] text-[var(--color-ink-subtle)]">
                          {fmtDateTime(entry.at)}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </Card>

          {/* Raw chain */}
          <Card>
            <CardHeader title="Step-by-Step History Log" subtitle={`${events.length} verified records`} />
            <div className="max-h-64 overflow-y-auto px-5 py-3">
              <table className="w-full text-left text-[11.5px]">
                <tbody>
                  {events.map((e) => (
                    <tr key={e.seq} className="border-b border-[var(--color-line)] last:border-0">
                      <td className="py-1.5 pr-3 font-mono text-[var(--color-ink-subtle)]">{e.seq}</td>
                      <td className="py-1.5 pr-3 font-mono text-[var(--color-ink)]">{e.type}</td>
                      <td className="py-1.5 font-mono text-[var(--color-ink-subtle)]">
                        {fmtDateTime(e.occurred_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      </aside>
    </div>
  );
}

/* ------------------------------------------------------------------- view */

export const DashboardView: React.FC = () => {
  const [rows, setRows] = useState<PaymentLinkRow[]>([]);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [cloud, setCloud] = useState<CloudPlinks | null>(null);
  const [tab, setTab] = useState('all');
  const [selected, setSelected] = useState<PaymentLinkRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<string | null>(null);
  const [evaluation, setEvaluation] = useState<AgentCompare | null>(null);
  const [evaluationLoading, setEvaluationLoading] = useState(false);
  const [evaluationError, setEvaluationError] = useState<string | null>(null);
  const [idleScan, setIdleScan] = useState<CheckoutIdleScan | null>(null);
  const [idleScanLoading, setIdleScanLoading] = useState(false);
  const [idleScanError, setIdleScanError] = useState<string | null>(null);
  const [promises, setPromises] = useState<PromiseList | null>(null);
  const [promisesLoading, setPromisesLoading] = useState(false);
  const [promisesError, setPromisesError] = useState<string | null>(null);
  const [predebit, setPredebit] = useState<PreDebitHistory | null>(null);
  const [predebitLoading, setPredebitLoading] = useState(false);
  const [predebitError, setPredebitError] = useState<string | null>(null);

  const loadPromises = useCallback(async () => {
    setPromisesLoading(true);
    setPromisesError(null);
    try {
      setPromises(await api.getPromises());
    } catch (e: any) {
      setPromisesError(e?.message ?? 'promise tracker unavailable');
    } finally {
      setPromisesLoading(false);
    }
  }, []);

  const loadPredebit = useCallback(async () => {
    setPredebitLoading(true);
    setPredebitError(null);
    try {
      setPredebit(await api.getPreDebitHistory());
    } catch (e: any) {
      setPredebitError(e?.message ?? 'preventive notice history unavailable');
    } finally {
      setPredebitLoading(false);
    }
  }, []);

  const loadEvaluation = useCallback(async () => {
    setEvaluationLoading(true);
    setEvaluationError(null);
    try {
      setEvaluation(await api.getAgentCompare(50, 42, [42, 7, 99, 123, 2024]));
    } catch (e: any) {
      setEvaluationError(e?.message ?? 'calibrated evaluation unavailable');
    } finally {
      setEvaluationLoading(false);
    }
  }, []);

  const scanIdleLinks = useCallback(async () => {
    setIdleScanLoading(true);
    setIdleScanError(null);
    try {
      const result = await api.scanCheckoutIdle();
      setIdleScan(result);
    } catch (e: any) {
      setIdleScanError(e?.message ?? 'idle checkout scan failed');
    } finally {
      setIdleScanLoading(false);
    }
  }, []);

  const loadRows = useCallback(async () => {
    try {
      const data = await api.getPaymentLinks(100);
      setRows(data);
      setLastSync(new Date().toISOString());
      setError(null);
    } catch (e: any) {
      setError(e?.message ?? 'failed to load payment links');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadStats = useCallback(async () => {
    const [s, c] = await Promise.all([
      api.getDashboardStats().catch(() => null),
      api.getCloudPlinks(50).catch(() => null),
    ]);
    if (s) setStats(s);
    setCloud(c);
  }, []);

  useEffect(() => {
    loadRows();
    const id = setInterval(loadRows, ROWS_POLL_MS);
    return () => clearInterval(id);
  }, [loadRows]);

  useEffect(() => {
    loadStats();
    const id = setInterval(loadStats, STATS_POLL_MS);
    return () => clearInterval(id);
  }, [loadStats]);

  useEffect(() => {
    loadEvaluation();
  }, [loadEvaluation]);

  useEffect(() => {
    loadPromises();
    loadPredebit();
  }, [loadPromises, loadPredebit]);

  // Keep the open drawer in sync with the poll so a status flip is visible
  // without closing and reopening it.
  useEffect(() => {
    if (!selected) return;
    const fresh = rows.find((r) => r.plink_id === selected.plink_id);
    if (fresh && fresh.updated_at !== selected.updated_at) setSelected(fresh);
  }, [rows, selected]);

  const counts = useMemo(() => {
    const acc: Record<string, number> = { all: rows.length };
    for (const r of rows) acc[r.status] = (acc[r.status] ?? 0) + 1;
    return acc;
  }, [rows]);

  const visible = useMemo(
    () => (tab === 'all' ? rows : rows.filter((r) => r.status === tab)),
    [rows, tab],
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="Real-time operations monitor for payment recovery. Shows live status, recovered revenue, active recovery cases, and the step-by-step history log."
        action={
          <div className="flex items-center gap-3">
            <span className="text-[11px] text-[var(--color-ink-subtle)]">
              {lastSync ? `synced ${relative(lastSync)}` : 'syncing…'}
            </span>
            <Button variant="secondary" size="sm" onClick={() => { loadRows(); loadStats(); }}>
              <RefreshCw size={13} /> Refresh
            </Button>
          </div>
        }
      />

      {/* Money counters */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {stats ? (
          <>
            <StatCard
              label="Recovered Revenue" accent="approved" icon={TrendingUp}
              value={inr(stats.recovered_inr)}
              sub={`${stats.recovered_count} successful recoveries · ${stats.recovery_rate_pct}% recovery rate`}
            />
            <StatCard
              label="Lost Revenue" accent="rejected" icon={TrendingDown}
              value={inr(stats.lost_inr)}
              sub={`${stats.lost_count} marked unrecoverable after max retries`}
            />
            <StatCard
              label="At Risk" accent="pending" icon={Wallet}
              value={inr(stats.at_risk_inr)}
              sub={`${stats.open_count} recovery cases actively in progress`}
            />
            <StatCard
              label="Payment Links" accent="info" icon={Link2}
              value={String(stats.plink_count)}
              sub={`${stats.plink_paid_count} links successfully paid`}
            />
            <StatCard
              label="Last 24 Hours" accent="neutral" icon={Clock}
              value={inr(stats.recovered_inr_since)}
              sub={`${stats.recovered_since} recovered · ${stats.mean_time_to_recover_min}m average recovery time`}
            />
          </>
        ) : (
          Array.from({ length: 5 }).map((_, i) => (
            <Card key={i} className="p-4"><Skeleton className="h-14 w-full" /></Card>
          ))
        )}
      </div>

      {/* Benchmark comparison and Idle cart scanner */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="AI Benchmark Comparison"
            subtitle="Compares Cadence's smart AI recovery against standard fixed-schedule retries over 50 simulated subscribers."
            action={<Badge tone="info">Benchmark</Badge>}
          />
          <div className="p-5 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-[12px] text-[var(--color-ink-muted)]">
                Tested across 5 seed cohorts of 50 subscribers to measure relative performance.
              </p>
              <Button variant="secondary" size="sm" onClick={loadEvaluation} loading={evaluationLoading}>
                <RefreshCw size={12} /> {evaluation ? 'Re-run benchmark' : 'Run benchmark'}
              </Button>
            </div>
            {evaluationError && <p className="font-mono text-[12px] text-[var(--color-rejected)]">{evaluationError}</p>}
            {evaluation && (
              <>
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <p className="text-[10px] uppercase tracking-wider text-[var(--color-ink-subtle)]">Standard Fixed Schedule</p>
                    <p className="numeric mt-1 text-[20px] font-semibold">{evaluation.mean_naive_recovery_pct.toFixed(1)}%</p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-wider text-[var(--color-ink-subtle)]">Cadence AI Recovery</p>
                    <p className="numeric mt-1 text-[20px] font-semibold text-[var(--color-approved)]">{evaluation.mean_cadence_recovery_pct.toFixed(1)}%</p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-wider text-[var(--color-ink-subtle)]">Recovery Revenue Uplift</p>
                    <p className="numeric mt-1 text-[20px] font-semibold text-[var(--color-accent)]">+{evaluation.mean_uplift_pct.toFixed(1)}%</p>
                  </div>
                </div>
                <p className="font-mono text-[10.5px] text-[var(--color-ink-subtle)]">
                  seeds: {evaluation.seeds.join(', ')} · {evaluation.n} subscribers per seed
                </p>
              </>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Abandoned Cart &amp; Link Scanner"
            subtitle="Scans for created payment links and checkouts that have been idle past 30 minutes to trigger recovery follow-ups."
            action={<Badge tone="neutral">Idle Monitor</Badge>}
          />
          <div className="p-5 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-[12px] text-[var(--color-ink-muted)]">
                Detects shoppers who left checkout without paying and evaluates whether a discount or nudge is appropriate.
              </p>
              <Button variant="secondary" size="sm" onClick={scanIdleLinks} loading={idleScanLoading}>
                <Clock size={12} /> Scan Idle Links
              </Button>
            </div>
            {idleScanError && <p className="font-mono text-[12px] text-[var(--color-rejected)]">{idleScanError}</p>}
            {idleScan && (
              <div className="rounded border border-[var(--color-line)] bg-[var(--color-surface-subtle)] p-3 text-[12px] font-mono space-y-1">
                <p>Threshold: {idleScan.threshold_minutes} min · Created links scanned: {idleScan.scanned_created_links}</p>
                <p className={idleScan.detected.length ? 'text-[var(--color-approved)]' : 'text-[var(--color-ink-muted)]'}>
                  Idle detected: {idleScan.detected.length} · Already notified: {idleScan.already_detected}
                </p>
                {idleScan.detected.map((finding) => (
                  <p key={finding.payment_link_id} className="break-all text-[var(--color-ink-muted)]">
                    {finding.payment_link_id} → {finding.journey_state ?? 'recorded'} · {finding.journey_id ?? 'case pending'}
                  </p>
                ))}
              </div>
            )}
          </div>
        </Card>
      </div>

      {/* Prevention and promise-to-pay evidence — same data the Test Lab
          cards write, made visible here so it is not Test-Lab-only. */}
      {/* Preventive notices and customer commitments */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Upcoming Payment Reminders (Pre-Debit Notices)"
            subtitle="Proactive notifications sent 24-48 hours ahead of auto-debit so customers maintain sufficient bank balance."
            action={<Badge tone="info">Preventive</Badge>}
          />
          <div className="p-5 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              {predebit && (
                <div className="flex items-center gap-2 text-[11.5px] text-[var(--color-ink-muted)]">
                  <Badge tone="approved">{predebit.notified_count} notified</Badge>
                  <Badge tone="pending">{predebit.suppressed_count} suppressed</Badge>
                </div>
              )}
              <Button variant="secondary" size="sm" onClick={loadPredebit} loading={predebitLoading}>
                <BellRing size={12} /> Refresh
              </Button>
            </div>
            {predebitError && <p className="font-mono text-[12px] text-[var(--color-rejected)]">{predebitError}</p>}
            {predebit && predebit.notices.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[12px]">
                  <thead>
                    <tr className="text-[10.5px] uppercase tracking-wider text-[var(--color-ink-subtle)]">
                      <th className="py-1.5 pr-3">Subscription</th>
                      <th className="py-1.5 pr-3">Channel</th>
                      <th className="py-1.5 pr-3">Debit Time</th>
                      <th className="py-1.5 pr-3">Result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {predebit.notices.map((row) => (
                      <tr key={`${row.subscription_id}-${row.scheduled_at}`} className="border-t border-[var(--color-line)]">
                        <td className="py-1.5 pr-3 max-w-[160px] truncate font-mono" title={row.subscription_id}>{row.subscription_id}</td>
                        <td className="py-1.5 pr-3 font-mono">{row.channel}</td>
                        <td className="py-1.5 pr-3 font-mono">{row.debit_at ? new Date(row.debit_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }) : '—'}</td>
                        <td className="py-1.5 pr-3">
                          <Badge tone={row.notified ? 'approved' : row.reason === 'pending' ? 'neutral' : 'pending'}>
                            {row.notified ? 'notified' : row.reason}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-[12px] text-[var(--color-ink-muted)]">No upcoming payment notices scheduled yet — try the Schedule Pre-Debit Reminder in the Test Lab.</p>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Customer Payday Commitments"
            subtitle="Understands customer promises (e.g. 'I will pay on 25th') and pauses recovery alerts until their promised payday."
            action={<Badge tone="neutral">Commitments</Badge>}
          />
          <div className="p-5 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              {promises && (
                <div className="flex items-center gap-2 text-[11.5px] text-[var(--color-ink-muted)]">
                  <Badge tone="pending">{promises.open_count} pending</Badge>
                  <Badge tone="approved">{promises.kept_count} kept</Badge>
                  <Badge tone="rejected">{promises.broken_count} expired</Badge>
                </div>
              )}
              <Button variant="secondary" size="sm" onClick={loadPromises} loading={promisesLoading}>
                <MessageSquareText size={12} /> Refresh
              </Button>
            </div>
            {promisesError && <p className="font-mono text-[12px] text-[var(--color-rejected)]">{promisesError}</p>}
            {promises && promises.promises.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[12px]">
                  <thead>
                    <tr className="text-[10.5px] uppercase tracking-wider text-[var(--color-ink-subtle)]">
                      <th className="py-1.5 pr-3">Customer Reply</th>
                      <th className="py-1.5 pr-3">Type</th>
                      <th className="py-1.5 pr-3">Promised Date</th>
                      <th className="py-1.5 pr-3">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {promises.promises.map((row) => (
                      <tr key={row.journey_id} className="border-t border-[var(--color-line)]">
                        <td className="py-1.5 pr-3 max-w-[200px] truncate" title={row.reply_text}>{row.reply_text || '—'}</td>
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
              <p className="text-[12px] text-[var(--color-ink-muted)]">No customer commitments recorded yet — simulate a customer reply in the Test Lab.</p>
            )}
          </div>
        </Card>
      </div>

      {/* Payment links table */}
      <Card>
        <CardHeader
          title="Recovery Payment Links &amp; Audit Log"
          subtitle="Real-time monitor of every payment link generated for customer recovery. Refreshes every 5 seconds."
          action={
            <div className="flex flex-wrap items-center gap-3 text-[11.5px]">
              {cloud?.enabled && (
                <a
                  href="https://supabase.com/dashboard/project/vzrasadomyrycafbzdwg/editor"
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-[var(--color-approved)] underline hover:no-underline"
                >
                  <ShieldCheck size={12} /> {cloud.count} in Supabase
                </a>
              )}
              <a
                href="https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-[#25D366] underline hover:no-underline"
              >
                Twilio WhatsApp <ArrowUpRight size={11} />
              </a>
              <a
                href="https://mail.google.com"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-[var(--color-ink)] underline hover:no-underline"
              >
                Gmail <ArrowUpRight size={11} />
              </a>
              <a
                href={RAZORPAY_LINKS_URL}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-[var(--color-accent)] underline hover:no-underline"
              >
                Razorpay Dashboard <ArrowUpRight size={11} />
              </a>
            </div>
          }
        />

        {/* Status tabs */}
        <div className="flex flex-wrap gap-1.5 border-b border-[var(--color-line)] px-5 py-3">
          {TABS.map((t) => {
            const active = tab === t.id;
            const n = counts[t.id] ?? 0;
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                aria-pressed={active}
                className={cn(
                  'rounded-md border px-2.5 py-1 text-[12px] font-medium transition-colors cursor-pointer',
                  active
                    ? 'border-[var(--color-line-strong)] bg-[var(--color-surface-subtle)] text-[var(--color-ink)]'
                    : 'border-transparent text-[var(--color-ink-muted)] hover:bg-[var(--color-surface-subtle)] hover:text-[var(--color-ink)]',
                )}
              >
                {t.label}
                <span className="numeric ml-1.5 text-[10.5px] text-[var(--color-ink-subtle)]">{n}</span>
              </button>
            );
          })}
        </div>

        {loading && rows.length === 0 && (
          <div className="space-y-2 px-5 py-5">
            {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
          </div>
        )}

        {!loading && error && rows.length === 0 && (
          <EmptyState title="Payment links unavailable" description={error} />
        )}

        {!loading && !error && visible.length === 0 && (
          <EmptyState
            title={rows.length === 0 ? 'No payment links yet' : `No ${tab.replace('_', ' ')} links`}
            description={
              rows.length === 0
                ? 'Open Live Recovery and run steps 1 and 2. The link the agent creates shows up here within seconds.'
                : 'Switch to All to see every link the agent created.'
            }
          />
        )}

        {visible.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[12.5px]">
              <thead>
                <tr className="border-b border-[var(--color-line)] text-[10.5px] uppercase tracking-wider text-[var(--color-ink-subtle)]">
                  <th scope="col" className="px-5 py-2.5 font-semibold">Amount</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold">Status</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold">Cadence</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold">Created</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold">Reference id</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold">Customer</th>
                  <th scope="col" className="px-5 py-2.5 font-semibold">Link</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => (
                  <tr
                    key={r.plink_id}
                    onClick={() => setSelected(r)}
                    tabIndex={0}
                    role="button"
                    aria-label={`Details for ${r.plink_id}`}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(r); }
                    }}
                    className="cursor-pointer border-b border-[var(--color-line)] last:border-0 hover:bg-[var(--color-surface-subtle)] focus:bg-[var(--color-surface-subtle)] focus:outline-none"
                  >
                    <td className="px-5 py-2.5">
                      <span className="numeric font-medium">{inr(r.amount_inr)}</span>
                      <span className="ml-1.5 text-[10.5px] text-[var(--color-ink-subtle)]">
                        {r.currency}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      <Badge tone={STATUS_TONE[r.status] ?? 'neutral'}>
                        {STATUS_LABEL[r.status] ?? r.status}
                      </Badge>
                    </td>
                    <td className="px-3 py-2.5">
                      {r.journey_state ? (
                        <Badge tone={JOURNEY_TONE[r.journey_state] ?? 'neutral'}>
                          {r.journey_state}
                        </Badge>
                      ) : (
                        <span className="text-[var(--color-ink-subtle)]">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-[var(--color-ink-muted)]">
                      <span className="numeric">{fmtDateTime(r.created_at)}</span>
                      <span className="ml-1.5 text-[10.5px] text-[var(--color-ink-subtle)]">
                        {relative(r.created_at)}
                      </span>
                    </td>
                    <td className="max-w-[190px] truncate px-3 py-2.5 font-mono text-[11.5px] text-[var(--color-ink-muted)]"
                        title={r.reference_id}>
                      {r.reference_id || '—'}
                    </td>
                    <td className="max-w-[150px] truncate px-3 py-2.5 font-mono text-[11.5px] text-[var(--color-ink-muted)]"
                        title={r.customer_id ?? ''}>
                      {r.customer_id ?? '—'}
                    </td>
                    <td className="px-5 py-2.5">
                      {r.short_url ? (
                        <a
                          href={r.short_url}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="inline-flex items-center gap-1 font-mono text-[11px] text-[var(--color-accent)] underline hover:no-underline"
                        >
                          {r.plink_id.slice(0, 14)} <ExternalLink size={10} />
                        </a>
                      ) : (
                        <span className="font-mono text-[11px] text-[var(--color-ink-subtle)]">
                          {r.plink_id.slice(0, 14)}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--color-line)] px-5 py-2.5 text-[11px] text-[var(--color-ink-subtle)]">
          <span className="inline-flex items-center gap-1">
            <IndianRupee size={11} /> amounts in rupees, read from the local audit log
          </span>
          <span>
            Razorpay has no link for a single payment link, so &ldquo;Open Razorpay&rdquo; opens the
            full list — search the plink id there.
          </span>
        </div>
      </Card>

      {selected && <RowDrawer row={selected} onClose={() => setSelected(null)} />}
    </div>
  );
};

export default DashboardView;
