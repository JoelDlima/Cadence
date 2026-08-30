import React, { useState, useEffect } from 'react';
import {
  Search,
  X,
  Copy,
  Check,
  ShieldCheck,
  FileClock,
  ChevronRight,
  Download,
  Brain
} from 'lucide-react';
import { Card, CardHeader, Badge, Button, Input, Select, PageHeader, EmptyState } from '../components/primitives';
import { Journey, TimelineEvent, AuditVerify, AgentReasoning, BanditRanking } from '../types';
import { api, formatINR } from '../services/api';

interface JourneysViewProps {
  journeys: Journey[];
}

export const JourneysView: React.FC<JourneysViewProps> = ({ journeys }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [stateFilter, setStateFilter] = useState('all');
  const [causeFilter, setCauseFilter] = useState('all');
  const [selectedJourney, setSelectedJourney] = useState<Journey | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [loadingTimeline, setLoadingTimeline] = useState(false);
  const [timelineError, setTimelineError] = useState<string | null>(null);
  const [copiedHash, setCopiedHash] = useState<string | null>(null);
  const [pollingClosed, setPollingClosed] = useState(false);
  const [reasoning, setReasoning] = useState<AgentReasoning | null>(null);
  const [reasoningLoading, setReasoningLoading] = useState(false);
  const [reasonPlaying, setReasonPlaying] = useState(false);
  const [shownSteps, setShownSteps] = useState(0);
  const [audit, setAudit] = useState<AuditVerify | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [why, setWhy] = useState<BanditRanking | null>(null);
  const [whyLoading, setWhyLoading] = useState(false);
  const [whyError, setWhyError] = useState<string | null>(null);

  // Periodically re-verify the audit chain while a journey is open so the
  // operator sees live "verified" / "tampered" state.
  useEffect(() => {
    if (!selectedJourney) return;
    let mounted = true;
    const fetchAudit = async () => {
      setAuditLoading(true);
      try {
        const a = await api.getAuditVerify();
        if (mounted) setAudit(a);
      } finally {
        if (mounted) setAuditLoading(false);
      }
    };
    fetchAudit();
    const interval = setInterval(fetchAudit, 8000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [selectedJourney]);

  const filteredJourneys = journeys.filter((j) => {
    const matchesSearch =
      j.journey_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      j.subscription_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      j.customer_id.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesState = stateFilter === 'all' || j.state === stateFilter;
    const matchesCause = causeFilter === 'all' || j.root_cause === causeFilter;
    return matchesSearch && matchesState && matchesCause;
  });

  const handleSelectJourney = async (journey: Journey) => {
    setSelectedJourney(journey);
    setLoadingTimeline(true);
    setTimelineError(null);
    setWhy(null);
    setWhyError(null);
    setWhyLoading(true);
    try {
      const events = await api.getTimeline(journey.journey_id);
      setTimeline(events);
      try {
        const bandit = await api.getBanditRanked(50);
        const jOpened = new Date(journey.opened_at).getTime();
        const match = (bandit.rankings ?? []).find(
          (r) =>
            (journey.root_cause ? r.cause === journey.root_cause : false) &&
            new Date(r.occurred_at).getTime() <= jOpened,
        ) ?? (bandit.rankings ?? []).find(
          (r) => new Date(r.occurred_at).getTime() <= jOpened,
        ) ?? (bandit.rankings?.[0] ?? null);
        setWhy(match);
      } catch (e: any) {
        setWhyError(e?.message ?? 'bandit rankings unavailable');
      } finally {
        setWhyLoading(false);
      }
      if (journey.state === 'WAITING_OUTCOME' || journey.state === 'INTERVENING') {
        const started = journey.state;
        const pollId = window.setInterval(async () => {
          try {
            const refreshed = await api.getJourney(journey.journey_id);
            if (refreshed.state === 'RECOVERED' || refreshed.state === 'CLOSED_UNRECOVERED' || refreshed.state === 'HUMAN_REVIEW') {
              setSelectedJourney(refreshed);
              if (started === 'INTERVENING' && refreshed.state === 'RECOVERED') {
                setPollingClosed(true);
              }
              window.clearInterval(pollId);
            }
          } catch (_e) { /* network blip, retry next tick */ }
        }, 2000);
        setTimeout(() => window.clearInterval(pollId), 60_000);
      }
    } catch (e: any) {
      setTimelineError(e?.message ?? 'timeline unavailable');
      setTimeline([]);
    } finally {
      setLoadingTimeline(false);
    }
  };

  const copyHash = (hash: string) => {
    navigator.clipboard.writeText(hash);
    setCopiedHash(hash);
    setTimeout(() => setCopiedHash(null), 2000);
  };

  const exportCsv = () => {
    const headers = "Journey ID,Subscription ID,Customer ID,Amount Minor,State,Root Cause,Opened At\n";
    const rows = filteredJourneys.map(j =>
      `${j.journey_id},${j.subscription_id},${j.customer_id},${j.amount_minor ?? 0},${j.state},${j.root_cause ?? ''},${j.opened_at}`
    ).join("\n");
    const blob = new Blob([headers + rows], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `cadence-case-ledger-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Case Ledger & Audit"
        description="Event-sourced subscriber journeys, decline triage records, and cryptographic audit chains."
        action={
          <Button variant="secondary" size="sm" onClick={exportCsv} disabled={filteredJourneys.length === 0}>
            <Download size={14} />
            <span>Export CSV</span>
          </Button>
        }
      />

      <Card>
        <div className="flex flex-wrap items-center gap-3 p-3.5">
          <div className="relative flex-1 min-w-[240px]">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-ink-subtle)]" />
            <Input
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search by Journey, Subscription, or Customer ID..."
              className="pl-9 h-8 text-[13px]"
            />
          </div>

          <div className="flex items-center gap-2 text-[12px] text-[var(--color-ink-muted)]">
            <span>State:</span>
            <Select
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
              className="h-8 w-36 text-[12px]"
            >
              <option value="all">All States</option>
              <option value="RECOVERED">RECOVERED</option>
              <option value="INTERVENING">INTERVENING</option>
              <option value="WAITING_OUTCOME">WAITING_OUTCOME</option>
              <option value="HUMAN_REVIEW">HUMAN_REVIEW</option>
              <option value="CLOSED_UNRECOVERED">CLOSED_UNRECOVERED</option>
            </Select>
          </div>

          <div className="flex items-center gap-2 text-[12px] text-[var(--color-ink-muted)]">
            <span>Root Cause:</span>
            <Select
              value={causeFilter}
              onChange={(e) => setCauseFilter(e.target.value)}
              className="h-8 w-44 text-[12px]"
            >
              <option value="all">All Root Causes</option>
              <option value="NO_FUNDS">Insufficient Balance</option>
              <option value="BANK_DOWN">Bank Server Downtime</option>
              <option value="TIMEOUT">Collect Timeout</option>
              <option value="BAD_VPA">Invalid VPA</option>
              <option value="EXPIRED_INSTRUMENT">Expired Mandate</option>
              <option value="CUSTOMER_ABORTED">User Cancelled</option>
            </Select>
          </div>

          <span className="text-[12px] text-[var(--color-ink-subtle)] ml-auto numeric">
            {filteredJourneys.length} of {journeys.length} cases
          </span>
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Subscriber Journeys"
          subtitle="Click any row to open the cryptographic timeline drawer"
          action={<FileClock size={14} className="text-[var(--color-ink-subtle)]" />}
        />

        {filteredJourneys.length === 0 ? (
          <EmptyState
            title={journeys.length === 0 ? 'No journeys yet' : 'No matching journeys found'}
            description={
              journeys.length === 0
                ? 'Fire a webhook from the Testbench tab, or POST one with the dev curl in the README.'
                : 'Adjust your search filters or simulate a new webhook in the Testbench.'
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-[13px]">
              <thead>
                <tr className="border-b border-[var(--color-line)] bg-[var(--color-surface-subtle)] text-[11px] font-semibold uppercase tracking-wider text-[var(--color-ink-subtle)]">
                  <th className="py-3 px-5">Journey ID / Subscription</th>
                  <th className="py-3 px-4">Customer ID</th>
                  <th className="py-3 px-4">Amount</th>
                  <th className="py-3 px-4">Root Cause</th>
                  <th className="py-3 px-4">Score</th>
                  <th className="py-3 px-4">State</th>
                  <th className="py-3 px-4 text-right">Audit</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-line)]">
                {filteredJourneys.map((j) => {
                  const isRecovered = j.state === 'RECOVERED';
                  const isIntervening = j.state === 'INTERVENING';
                  const isWaiting = j.state === 'WAITING_OUTCOME';

                  return (
                    <tr
                      key={j.journey_id}
                      onClick={() => handleSelectJourney(j)}
                      className="hover:bg-[var(--color-paper)] cursor-pointer transition-colors duration-[var(--duration-micro)]"
                    >
                      <td className="py-3 px-5">
                        <span className="numeric font-medium text-[var(--color-ink)]">{j.journey_id}</span>
                        <p className="text-[11px] text-[var(--color-ink-subtle)]">{j.subscription_id}</p>
                      </td>
                      <td className="py-3 px-4 text-[var(--color-ink-muted)]">
                        {j.customer_id}
                      </td>
                      <td className="py-3 px-4 numeric font-medium text-[var(--color-ink)]">
                        {formatINR(j.amount_minor)}
                      </td>
                      <td className="py-3 px-4">
                        <Badge tone={j.root_cause === 'NO_FUNDS' ? 'approved' : j.root_cause === 'BANK_DOWN' ? 'info' : 'neutral'}>
                          {j.root_cause ?? 'UNKNOWN'}
                        </Badge>
                      </td>
                      <td className="py-3 px-4 numeric">
                        <span className={j.score != null && j.score >= 70 ? 'text-[var(--color-approved)] font-semibold' : j.score != null && j.score >= 50 ? 'text-[var(--color-pending)] font-medium' : 'text-[var(--color-rejected)] font-medium'}>
                          {j.score != null ? `${j.score}/100` : '—'}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        <Badge tone={isRecovered ? 'approved' : isIntervening ? 'info' : isWaiting ? 'pending' : 'rejected'}>
                          {j.state}
                        </Badge>
                      </td>
                      <td className="py-3 px-4 text-right">
                        <ChevronRight size={15} className="inline text-[var(--color-ink-subtle)]" />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {selectedJourney && (
        <div className="fixed inset-0 z-50 overflow-hidden flex justify-end">
          <div
            className="fixed inset-0 bg-black/35 backdrop-blur-xs transition-opacity"
            onClick={() => setSelectedJourney(null)}
          />

          <aside className="relative w-full max-w-lg glass-modal h-full shadow-2xl flex flex-col justify-between overflow-y-auto border-l border-[var(--color-line-strong)]">
            <div className="p-6 border-b border-[var(--color-line)] flex items-center justify-between sticky top-0 bg-white/95 backdrop-blur-md z-10">
              <div>
                <div className="flex items-center gap-2">
                  <span className="display text-2xl text-[var(--color-ink)]">Audit Trail</span>
                  <Badge tone={selectedJourney.state === 'RECOVERED' ? 'approved' : 'info'}>
                    {selectedJourney.state}
                  </Badge>
                  {(selectedJourney.state === 'WAITING_OUTCOME' || selectedJourney.state === 'INTERVENING') && (
                    <span className="flex items-center gap-1.5 text-[11px] text-[var(--color-coral)] font-medium">
                      <span className="inline-block h-2 w-2 rounded-full bg-[var(--color-coral)] animate-pulse" />
                      Waiting for payment webhook… (auto-refresh)
                    </span>
                  )}
                </div>
                <p className="numeric text-[12px] text-[var(--color-ink-subtle)] mt-0.5">
                  Journey: {selectedJourney.journey_id}
                </p>
              </div>

              <button
                onClick={() => setSelectedJourney(null)}
                className="p-1.5 rounded text-[var(--color-ink-muted)] hover:bg-[var(--color-surface-subtle)] cursor-pointer"
              >
                <X size={18} />
              </button>
            </div>

            <div className="p-6 space-y-6 flex-1 bg-[var(--color-paper)]">
              <div className="p-4 rounded-md bg-[var(--color-surface)] border border-[var(--color-line)] shadow-xs space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-[var(--color-ink-subtle)]">Customer Entity:</span>
                  <span className="font-mono text-[var(--color-ink)] font-medium">{selectedJourney.customer_id}</span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-[var(--color-ink-subtle)]">Amount Due:</span>
                  <span className="numeric font-semibold text-[var(--color-ink)]">{formatINR(selectedJourney.amount_minor)}</span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-[var(--color-ink-subtle)]">Root Cause:</span>
                  <Badge tone="neutral">{selectedJourney.root_cause ?? 'UNKNOWN'}</Badge>
                </div>
              </div>

              <div>
                <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-ink-subtle)]">
                    Agent Reasoning (chat trace)
                  </h4>
                  {reasoning && reasoning.steps.length > 0 && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setShownSteps(0);
                        setReasonPlaying(true);
                        for (let i = 1; i <= reasoning.steps.length; i++) {
                          setTimeout(() => setShownSteps(i), i * 700);
                        }
                        setTimeout(() => setReasonPlaying(false), reasoning.steps.length * 700 + 600);
                      }}
                    >
                      {reasonPlaying ? "Replaying…" : "Replay chat trace"}
                    </Button>
                  )}
                </div>

                {reasoningLoading && (
                  <div className="space-y-2">
                    {[0, 1, 2].map((i) => (
                      <div key={i} className="h-12 rounded bg-[var(--color-line)] animate-pulse" />
                    ))}
                  </div>
                )}

                {!reasoningLoading && reasoning && reasoning.steps.length === 0 && (
                  <div className="text-[12px] text-[var(--color-ink-subtle)] p-3 border border-dashed border-[var(--color-line)] rounded">
                    No reasoning trace captured for this journey yet.
                  </div>
                )}

                <div className="space-y-2">
                  {(reasoning?.steps ?? []).slice(0, shownSteps || reasoning?.steps.length || 0).map((s: any, i: number) => (
                    <div
                      key={i}
                      className={
                        "p-3 rounded-md border text-[12.5px] leading-relaxed " +
                        (s.role === "observation"
                          ? "bg-[var(--color-info-wash)] border-[var(--color-info)] text-[var(--color-ink)]"
                          : s.role === "decision"
                            ? "bg-[var(--color-surface)] border-[var(--color-line)] text-[var(--color-ink)]"
                            : s.role === "action"
                              ? "bg-[var(--color-approved-wash)] border-[var(--color-approved)] text-[var(--color-ink)]"
                              : "bg-[var(--color-ink-subtle)]/10 border-[var(--color-line-strong)] text-[var(--color-ink)] italic")
                      }
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-semibold text-[11px]">Step {s.step}: {s.title}</span>
                        {s.source && (
                          <span className="text-[10px] font-mono text-[var(--color-ink-subtle)]">
                            [{s.source}]
                          </span>
                        )}
                        {s.channel && (
                          <span className="text-[10px] font-mono text-[var(--color-ink-subtle)]">
                            channel={s.channel}
                          </span>
                        )}
                      </div>
                      <div>{s.detail}</div>
                      {s.event_refs && s.event_refs.length > 0 && (
                        <div className="text-[10px] text-[var(--color-ink-subtle)] mt-1 font-mono">
                          events: {s.event_refs.map((r: any) => `#${r.seq} ${r.type}`).join(", ")}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* Why this choice: bandit ranking + feature importances */}
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Brain size={13} className="text-[var(--color-ink-subtle)]" />
                  <h4 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-ink-subtle)]">
                    Why this choice
                  </h4>
                  {why && (
                    <Badge tone="info">{why.cause}</Badge>
                  )}
                </div>

                {whyLoading && (
                  <div className="space-y-2">
                    {[0, 1].map((i) => (
                      <div key={i} className="h-12 rounded bg-[var(--color-line)] animate-pulse" />
                    ))}
                  </div>
                )}

                {!whyLoading && whyError && (
                  <div className="p-3 rounded border border-dashed border-[var(--color-line)] text-[12px] text-[var(--color-ink-subtle)]">
                    Bandit feed unavailable: {whyError}
                  </div>
                )}

                {!whyLoading && !why && !whyError && (
                  <div className="p-3 rounded border border-dashed border-[var(--color-line)] text-[12px] text-[var(--color-ink-subtle)]">
                    No bandit ranking captured for this journey yet.
                  </div>
                )}

                {why && (
                  <div className="p-3.5 rounded-md bg-[var(--color-surface)] border border-[var(--color-line)] shadow-xs space-y-3">
                    <div>
                      <div className="text-[10.5px] uppercase tracking-wider text-[var(--color-ink-subtle)] font-semibold mb-1.5">
                        Top 3 ranked interventions
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {(why.ranked ?? []).slice(0, 3).map((candidate, j) => {
                          const score = why.scores?.[candidate] ?? 0;
                          const tone = j === 0 ? 'approved' : j === 1 ? 'info' : 'neutral';
                          return (
                            <Badge key={candidate} tone={tone as any}>
                              {j + 1}. {candidate} <span className="font-mono ml-1 opacity-75">{score.toFixed(1)}</span>
                            </Badge>
                          );
                        })}
                      </div>
                    </div>

                    <div>
                      <div className="text-[10.5px] uppercase tracking-wider text-[var(--color-ink-subtle)] font-semibold mb-1.5">
                        Feature importances
                      </div>
                      <div className="space-y-1.5">
                        {(() => {
                          const importances = why.feature_importances ?? {};
                          const causeKey = why.cause in importances ? why.cause : Object.keys(importances)[0];
                          const weights = (causeKey ? importances[causeKey] : {}) ?? {};
                          const entries = Object.entries(weights);
                          if (entries.length === 0) {
                            return (
                              <div className="text-[11.5px] text-[var(--color-ink-subtle)]">
                                No feature importances published for this cause.
                              </div>
                            );
                          }
                          const max = entries.reduce((m, [, v]) => Math.max(m, Math.abs(v)), 0) || 1;
                          return entries
                            .slice()
                            .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
                            .slice(0, 8)
                            .map(([feature, weight]) => {
                              const pct = (Math.abs(weight) / max) * 100;
                              const positive = weight >= 0;
                              return (
                                <div key={feature} className="text-[11.5px]">
                                  <div className="flex items-center justify-between mb-0.5">
                                    <span className="font-mono text-[var(--color-ink)]">{feature}</span>
                                    <span
                                      className="font-mono tabular-nums"
                                      style={{ color: positive ? 'var(--color-approved)' : 'var(--color-rejected)' }}
                                    >
                                      {positive ? '+' : ''}{(weight * 100).toFixed(0)}%
                                    </span>
                                  </div>
                                  <div className="h-1.5 w-full rounded-full bg-[var(--color-surface-subtle)] overflow-hidden border border-[var(--color-line)]">
                                    <div
                                      className="h-full rounded-full"
                                      style={{
                                        width: `${Math.max(2, pct)}%`,
                                        backgroundColor: positive ? 'var(--color-approved)' : 'var(--color-rejected)',
                                      }}
                                    />
                                  </div>
                                </div>
                              );
                            });
                        })()}
                      </div>
                    </div>

                    {why.reason && why.reason.length > 0 && (
                      <div>
                        <div className="text-[10.5px] uppercase tracking-wider text-[var(--color-ink-subtle)] font-semibold mb-1.5">
                          Bandit reason
                        </div>
                        <p className="text-[12px] text-[var(--color-ink)] leading-relaxed">
                          {why.reason.join(' - ')}
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </div>

              <h4 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-ink-subtle)] mb-3">
                  Cryptographic Event Stream (SQLite WAL)
                </h4>

                {loadingTimeline ? (
                  <div className="space-y-3">
                    {[0, 1, 2, 3].map((i) => (
                      <div key={i} className="h-16 rounded bg-[var(--color-line)] animate-pulse" />
                    ))}
                  </div>
                ) : timelineError ? (
                  <div className="p-3 rounded border border-[var(--color-rejected)] bg-[var(--color-rejected-wash)] text-[var(--color-rejected)] text-[12px]">
                    {timelineError}
                  </div>
                ) : (
                  <div className="space-y-4 relative before:absolute before:inset-0 before:left-3 before:w-0.5 before:bg-[var(--color-line)]">
                    {timeline.map((event) => (
                      <div key={event.seq} className="relative flex items-start gap-4 pl-8">
                        <div className="absolute left-1.5 top-1 h-3.5 w-3.5 rounded-full bg-[var(--color-surface)] border-2 border-[var(--color-info)] shadow-xs" />
                        <div className="flex-1 p-3.5 rounded-md bg-[var(--color-surface)] border border-[var(--color-line)] shadow-xs space-y-1.5">
                          <div className="flex items-center justify-between text-[12px]">
                            <span className="font-semibold text-[var(--color-ink)]">{event.type}</span>
                            <span className="numeric text-[11px] text-[var(--color-ink-subtle)]">
                              Seq #{event.seq}
                            </span>
                          </div>

                          <div className="flex items-center gap-2 text-[11px] text-[var(--color-ink-subtle)]">
                            <span>Occurred:</span>
                            <span className="numeric font-medium text-[var(--color-ink-muted)]">
                              {new Date(event.occurred_at).toLocaleTimeString('en-IN', { hour12: false })}
                            </span>
                          </div>

                          {event.payload && (
                            <pre className="mt-2 p-2.5 rounded bg-[var(--color-paper)] border border-[var(--color-line)] text-[11px] font-mono text-[var(--color-ink)] overflow-x-auto leading-relaxed">
                              {JSON.stringify(event.payload, null, 2)}
                            </pre>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="p-4 border-t border-[var(--color-line)] bg-[var(--color-surface)] flex items-center justify-between text-xs">
              <div className="flex items-center gap-1.5 font-mono font-medium text-[12px]"
                style={{ color: audit?.chain_ok === false ? 'var(--color-rejected)' : 'var(--color-approved)' }}>
                <ShieldCheck size={15} />
                {auditLoading && !audit
                  ? 'Verifying...'
                  : audit
                    ? audit.chain_ok
                      ? `SHA-256 Verified · ${audit.event_count} events · ${audit.last_hash.slice(0, 12)}…`
                      : `TAMPERED at seq ${audit.first_bad_seq}`
                    : 'SHA-256 Hash Chain'}
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => audit && copyHash(audit.last_hash)}
                disabled={!audit}
              >
                {copiedHash ? <Check size={12} className="text-[var(--color-approved)]" /> : <Copy size={12} />}
                <span>{copiedHash ? "Copied" : "Copy last hash"}</span>
              </Button>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
};
