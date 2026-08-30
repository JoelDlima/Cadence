import React, { useState, useEffect } from 'react';
import { Building2, Activity } from 'lucide-react';
import { Card, CardHeader, Badge, PageHeader } from '../components/primitives';
import { Stagger, StaggerItem } from '../components/motion';
import { GuardianStats, LlmSpend, Bank } from '../types';
import { api } from '../services/api';

interface RuleCardProps {
  title: string;
  statute: string;
  description: string;
  vetoCount: number;
  enforcement: string;
}

const RuleCard: React.FC<RuleCardProps> = ({
  title,
  statute,
  description,
  vetoCount,
  enforcement,
}) => {
  return (
    <Card className="p-5 flex flex-col justify-between space-y-4">
      <div>
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-sm font-semibold text-[var(--color-ink)]">
            {title}
          </h3>
          <Badge tone="rejected" className="shrink-0 text-[10px]">
            {vetoCount} Vetoes
          </Badge>
        </div>
        <p className="text-[11px] font-mono text-[var(--color-info)] mt-1 font-medium">
          {statute}
        </p>
        <p className="text-[12.5px] text-[var(--color-ink-muted)] leading-relaxed mt-2.5">
          {description}
        </p>
      </div>

      <div className="pt-3 border-t border-[var(--color-line)] flex items-center justify-between text-[11px]">
        <span className="text-[var(--color-ink-subtle)]">Source: <strong className="text-[var(--color-ink-muted)]">{enforcement}</strong></span>
        <span className="text-[var(--color-approved)] font-mono font-medium">Stable</span>
      </div>
    </Card>
  );
};

const STATIC_RULES: Array<{ key: string; title: string; statute: string; description: string }> = [
  {
    key: 'predebit_notify_rbi_24h',
    title: 'RBI 24h Advance Pre-Debit Notice',
    statute: 'RBI E-mandate Framework §4.2 / DPSS.CO.PD.No.447',
    description: 'Mandatory pre-debit advice must be issued at least 24 hours prior to any debit execution. Automated instant retries without customer notice are strictly vetoed.',
  },
  {
    key: 'quiet_hours_deferred',
    title: 'Quiet Hours Contact Blackout',
    statute: 'NPCI Customer Protection Circular / TRAI DND Rule',
    description: 'All customer messaging (WhatsApp, SMS, Email nudges) strictly muted between 21:00 and 09:00 IST. Recoveries are automatically deferred to 09:01 IST.',
  },
  {
    key: 'touch_cap_reached',
    title: '14-Day Touch Frequency Ceiling',
    statute: 'Fintech Fair Debt Practice / Cadence §3',
    description: 'Maximum 3 recovery contacts allowed across any 14-day rolling window per subscriber to eliminate spam, customer harassment, and involuntary churn.',
  },
  {
    key: 'hard_decline_stop',
    title: 'Hard Decline Immediate Termination',
    statute: 'NPCI UPI Error Code Standard / ISO 8583',
    description: 'Mandate revoked, stolen card, or authentication cancelled stops recovery immediately. Zero automated retries allowed; routes directly to payment instrument update.',
  },
  {
    key: 'npci_peak_hold_release',
    title: 'NPCI Peak-Hour Hold Detection',
    statute: 'NPCI UPI Mandate Circular (Aug 2025 Guidelines)',
    description: 'Detects clearing holds during morning peak clearing (05:00 - 09:30 AM). Prevents treating queued transactions as failures; pauses contact until hold window clears.',
  },
  {
    key: 'finance_approval_required',
    title: 'High-Value Human Oversight Tier',
    statute: 'Cadence Risk Governance Matrix §7',
    description: 'Transactions > ₹50,000 require manual review before any payment links or settlement grace offers can be sent. AI cannot approve high-value settlements alone.',
  },
];

export const GuardianView: React.FC = () => {
  const [stats, setStats] = useState<GuardianStats | null>(null);
  const [spend, setSpend] = useState<LlmSpend | null>(null);
  const [banks, setBanks] = useState<Bank[]>([]);

  useEffect(() => {
    let mounted = true;
    const fetchAll = async () => {
      try {
        const [g, s, b] = await Promise.all([
          api.getGuardianStats().catch(() => null),
          api.getLlmSpend().catch(() => null),
          api.getBanks().catch(() => []),
        ]);
        if (mounted) {
          setStats(g);
          setSpend(s);
          setBanks(b);
        }
      } catch {
        // keep prior state
      }
    };
    fetchAll();
    const interval = setInterval(fetchAll, 5000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const totalVetoes = stats?.total_vetoes ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Autonomous Policy Guardian"
        description="Deterministic code guardrails for RBI regulations and NPCI circulars. Rules own the money; AI models can only propose."
        action={
          <div className="flex items-center gap-2">
            <Badge tone="approved">{totalVetoes} Out-of-Policy Blocked</Badge>
            <Badge tone="info">0 Compliance Drift</Badge>
          </div>
        }
      />

      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-ink-subtle)] mb-3">
          Rules that stop Cadence from doing something
        </h3>
        <Stagger className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {STATIC_RULES.map((r) => (
            <StaggerItem key={r.key}>
              <RuleCard
                title={r.title}
                statute={r.statute}
                description={r.description}
                vetoCount={stats?.by_reason?.[r.key] ?? 0}
                enforcement="Pure Python Veto"
              />
            </StaggerItem>
          ))}
        </Stagger>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pt-2">
        <Card>
          <CardHeader
            title="Bank Outage Anomaly Shield"
            subtitle="Live cross-journey telemetry detecting clearing bank downtime"
            action={
              <Badge tone={banks.some((b) => b.is_holding) ? 'rejected' : 'approved'}>
                {banks.filter((b) => b.is_holding).length} Holding
              </Badge>
            }
          />
          <div className="p-5">
            <p className="text-[12.5px] text-[var(--color-ink-muted)] mb-4 leading-relaxed">
              When a bank's network failure rate spikes past 15%, the shield pauses all retries for that bank to prevent burning customer attempt limits.
            </p>

            {banks.length === 0 ? (
              <div className="text-[12px] text-[var(--color-ink-subtle)]">No bank data yet.</div>
            ) : (
              <div className="divide-y divide-[var(--color-line)] border border-[var(--color-line)] rounded-md overflow-hidden bg-[var(--color-surface)]">
                {banks.map((b) => (
                  <div key={b.bank_name} className="flex items-center justify-between p-3 text-[12.5px] hover:bg-[var(--color-surface-subtle)] transition-colors">
                    <div className="flex items-center gap-2.5">
                      <Building2 size={15} className="text-[var(--color-ink-subtle)]" />
                      <span className="font-medium text-[var(--color-ink)]">{b.bank_name}</span>
                    </div>

                    <div className="flex items-center gap-3">
                      <span className="numeric text-[11px] text-[var(--color-ink-muted)]">
                        {b.failure_count} / {b.threshold}
                      </span>
                      <Badge tone={b.is_holding ? 'pending' : 'approved'} className="text-[10px]">
                        {b.is_holding ? 'Anomaly Hold' : 'Normal'}
                      </Badge>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader
            title="4-Tier Model Router & Budgeter"
            subtitle="Hierarchical LLM failover with hard daily expenditure ceiling"
            action={
              <Badge tone="neutral">
                {spend?.providers?.reduce((sum, p) => sum + p.requests, 0) ?? 0} / {spend?.providers?.reduce((sum, p) => sum + p.cap, 0) ?? 400} requests
              </Badge>
            }
          />
          <div className="p-5 space-y-4">
            <p className="text-[12.5px] text-[var(--color-ink-muted)] leading-relaxed">
              Fast path handles ~100% of standard decline codes with zero AI tokens. For novel text or ambiguous customer replies, the router activates with strict budget caps:
            </p>

            <div className="space-y-2 text-[12px]">
              <div className="flex items-center justify-between p-2.5 rounded bg-[var(--color-surface-subtle)] border border-[var(--color-line)]">
                <span className="font-medium text-[var(--color-ink)]">1) Gemini</span>
                <span className="text-[11px] text-[var(--color-approved)] font-mono font-medium">Primary · $0.10/M</span>
              </div>
              <div className="flex items-center justify-between p-2.5 rounded bg-[var(--color-surface-subtle)] border border-[var(--color-line)]">
                <span className="font-medium text-[var(--color-ink)]">2) Groq</span>
                <span className="text-[11px] text-[var(--color-info)] font-mono font-medium">Fallback A · Ultra-low latency</span>
              </div>
              <div className="flex items-center justify-between p-2.5 rounded bg-[var(--color-surface-subtle)] border border-[var(--color-line)]">
                <span className="font-medium text-[var(--color-ink)]">Tier 3: OpenRouter</span>
                <span className="text-[11px] text-[var(--color-pending)] font-mono font-medium">Fallback B · Multi-provider</span>
              </div>
              <div className="flex items-center justify-between p-2.5 rounded bg-[var(--color-surface-subtle)] border border-[var(--color-line)]">
                <span className="font-medium text-[var(--color-ink)]">Tier 4: Local Ollama</span>
                <span className="text-[11px] text-[var(--color-ink-subtle)] font-mono font-medium">Air-gapped · Zero internet</span>
              </div>
            </div>

            <div className="pt-3 border-t border-[var(--color-line)] flex items-center justify-between text-[11px] text-[var(--color-ink-subtle)]">
              <span>Daily Cap: {spend?.providers?.reduce((sum, p) => sum + p.cap, 0) ?? 400} requests</span>
              <span className="text-[var(--color-approved)] font-mono font-medium">Live Spend</span>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
};
