//
// Dashboard — the Razorpay Payment Links page, but with the agent's reasoning
// attached to every row.
//
// Why it looks like Razorpay: a judge already knows that table. Showing the
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
  ArrowUpRight, Clock, ExternalLink, IndianRupee, Link2, RefreshCw,
  ShieldCheck, TrendingDown, TrendingUp, Wallet, X,
} from 'lucide-react';
import {
  Badge, Button, Card, CardHeader, EmptyState, PageHeader, Skeleton, cn,
  type BadgeTone,
} from '../components/primitives';
import { api, inrFormatter } from '../services/api';
import type {
  AgentReasoning, CloudPlinks, DashboardStats, PaymentLinkRow, TimelineEvent,
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
              ['Journey', row.journey_id],
              ['Subscription', row.subscription_id ?? '—'],
              ['Reference id', row.reference_id || '—'],
              ['Amount paid', inr(row.amount_paid_minor / 100)],
              ['Attempts / touches', `${row.attempts_used} / ${row.touches_used}`],
              ['Failure code', row.failure_code ?? '—'],
              ['Root cause', row.root_cause ?? 'not classified'],
              ['Recovery channel', banditArm ?? 'none yet'],
              ['Guardian vetoes', String(vetoes)],
              ['Created', fmtDateTime(row.created_at)],
              ['Last update', fmtDateTime(row.updated_at)],
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
                Cadence: {row.journey_state}
              </Badge>
            )}
            {row.short_url && (
              <a href={row.short_url} target="_blank" rel="noreferrer"
                 className="inline-flex items-center gap-1 text-[12px] text-[var(--color-accent)] underline hover:no-underline">
                <Link2 size={12} /> open payment link
              </a>
            )}
            <a href={RAZORPAY_LINKS_URL} target="_blank" rel="noreferrer"
               className="inline-flex items-center gap-1 text-[12px] text-[var(--color-accent)] underline hover:no-underline">
              <ExternalLink size={12} /> find in Razorpay
            </a>
          </div>

          {/* Agent reasoning — the panel that used to live on the Journeys tab */}
          <Card>
            <CardHeader
              title="What the agent did"
              subtitle="Rebuilt from the audit log: what it saw, what it weighed, what it did."
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
                      seq {step.event_refs.map((r) => r.seq).join(', ')}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </Card>

          {/* Lifecycle trail */}
          <Card>
            <CardHeader title="Link history" subtitle="Every status change, oldest first." />
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
            <CardHeader title="Audit trail" subtitle={`${events.length} tamper-evident records`} />
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
        description="Every payment link the agent created, laid out the way Razorpay lays them out. The rows are rebuilt from the audit log, so the table and the audit trail can never disagree."
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
              label="Recovered" accent="approved" icon={TrendingUp}
              value={inr(stats.recovered_inr)}
              sub={`${stats.recovered_count} journeys · ${stats.recovery_rate_pct}% rate`}
            />
            <StatCard
              label="Lost" accent="rejected" icon={TrendingDown}
              value={inr(stats.lost_inr)}
              sub={`${stats.lost_count} closed unrecovered`}
            />
            <StatCard
              label="At risk" accent="pending" icon={Wallet}
              value={inr(stats.at_risk_inr)}
              sub={`${stats.open_count} journeys still open`}
            />
            <StatCard
              label="Payment links" accent="info" icon={Link2}
              value={String(stats.plink_count)}
              sub={`${stats.plink_paid_count} paid`}
            />
            <StatCard
              label="Last 24 hours" accent="neutral" icon={Clock}
              value={inr(stats.recovered_inr_since)}
              sub={`${stats.recovered_since} recovered · mean ${stats.mean_time_to_recover_min}m to recover`}
            />
          </>
        ) : (
          Array.from({ length: 5 }).map((_, i) => (
            <Card key={i} className="p-4"><Skeleton className="h-14 w-full" /></Card>
          ))
        )}
      </div>

      {/* Payment links table */}
      <Card>
        <CardHeader
          title="Payment links"
          subtitle="Refreshes every 5 seconds, so a link you create on Live Recovery lands here within seconds."
          action={
            <div className="flex items-center gap-3">
              {cloud?.enabled && (
                <span className="inline-flex items-center gap-1 text-[11px] text-[var(--color-approved)]">
                  <ShieldCheck size={12} /> {cloud.count} mirrored to Supabase
                </span>
              )}
              <a
                href={RAZORPAY_LINKS_URL}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-[11.5px] text-[var(--color-accent)] underline hover:no-underline"
              >
                Open Razorpay <ArrowUpRight size={11} />
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
