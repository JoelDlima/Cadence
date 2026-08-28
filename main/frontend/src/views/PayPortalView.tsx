import React, { useState, useEffect } from 'react';
import {
  Lock,
  Smartphone,
  CreditCard,
  ArrowRight,
  CheckCircle2,
  AlertCircle
} from 'lucide-react';
import { Card, Badge, Button, PageHeader } from '../components/primitives';
import { api, formatINR } from '../services/api';
import { Journey } from '../types';
import { NudgePreview } from './NudgePreview';

export const PayPortalView: React.FC = () => {
  const [journey, setJourney] = useState<Journey | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedMethod, setSelectedMethod] = useState<'upi' | 'card'>('upi');
  const [paid, setPaid] = useState(false);
  const [busy, setBusy] = useState(false);
  const [linkMode, setLinkMode] = useState<'DEMO' | 'LIVE' | null>(null);

  // Read ?journey=<id> from the URL. SPA routing is hash-based; this is the
  // minimal way to deep-link from the Testbench / an emailed link.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const key = params.get('journey');
    if (!key) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    api.getJourney(key)
      .then((j) => {
        setJourney(j);
        setPaid(j.state === 'RECOVERED');
      })
      .catch((e: any) => setError(e?.message ?? 'journey not found'))
      .finally(() => setLoading(false));
  }, []);

  const handlePay = async () => {
    if (!journey) return;
    setBusy(true);
    setError(null);
    try {
      const link = await api.createPayLink(journey.journey_id);
      setLinkMode(link.mode);
      if (link.mode === 'LIVE' && link.short_url && !link.simulated) {
        // Real Razorpay Payment Link -> open it in a new tab.
        window.open(link.short_url, '_blank', 'noopener,noreferrer');
      } else {
        // DEMO: short_url is a placeholder; offer to "simulate" the customer
        // payment which writes E_PAYMENT_RECOVERED and closes the journey.
        const sim = await api.simulatePaid(journey.journey_id, 'pay button (demo)');
        setPaid(true);
        // Refresh the journey so the amount/state are accurate
        try {
          const j2 = await api.getJourney(journey.journey_id);
          setJourney(j2);
        } catch {}
        if (sim.state_after) {
          setError(null);
        }
      }
    } catch (e: any) {
      setError(e?.message ?? 'failed to start payment');
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Customer Payment Resolution"
          description="Self-service recovery experience shown to subscribers (`/pay/{journey_id}`). Converts involuntary churn into instant resolution."
        />
        <div className="flex justify-center py-12 text-[13px] text-[var(--color-ink-subtle)]">
          Loading journey…
        </div>
      </div>
    );
  }

  if (error && !journey) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Customer Payment Resolution"
          description="Open this view with `?journey=<id>` or after firing a webhook from the Testbench."
        />
        <div className="max-w-md mx-auto">
          <Card className="p-6 glass-modal border border-[var(--color-line-strong)] text-center space-y-2">
            <AlertCircle size={32} className="mx-auto text-[var(--color-rejected)]" />
            <h3 className="text-base font-semibold text-[var(--color-ink)]">No journey loaded</h3>
            <p className="text-[12.5px] text-[var(--color-ink-muted)]">{error}</p>
            <p className="text-[11px] text-[var(--color-ink-subtle)] pt-2">
              Add <code className="font-mono">?journey=&lt;id&gt;</code> to the URL, or jump to the Testbench to inject one.
            </p>
          </Card>
        </div>
      </div>
    );
  }

  if (!journey) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Customer Payment Resolution"
          description="Self-service recovery experience shown to subscribers (`/pay/{journey_id}`). Converts involuntary churn into instant resolution."
          action={<Badge tone="approved">Demo</Badge>}
        />
        <div className="max-w-md mx-auto">
          <Card className="p-6 glass-modal border border-[var(--color-line-strong)] text-center space-y-2">
            <h3 className="text-base font-semibold text-[var(--color-ink)]">Pick a journey</h3>
            <p className="text-[12.5px] text-[var(--color-ink-muted)]">
              Open this view with <code className="font-mono">?journey=&lt;id&gt;</code> in the URL, or pick one from the Case Ledger.
            </p>
          </Card>
        </div>
      </div>
    );
  }

  const merchant = 'Acme Cloud Services';

  return (
    <div className="space-y-6">
      <PageHeader
        title="Customer Payment Resolution"
        description="Self-service recovery experience. Converts involuntary churn into instant resolution."
        action={<Badge tone={linkMode === 'LIVE' ? 'approved' : 'pending'}>{linkMode === 'LIVE' ? 'LIVE link' : 'DEMO mode'}</Badge>}
      />

      <div className="flex justify-center py-6">
        <div className="w-full max-w-md">
          <Card className="p-8 space-y-6 glass-modal shadow-lg border border-[var(--color-line-strong)]">
            <div className="flex items-center justify-between pb-5 border-b border-[var(--color-line)]">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-md bg-[var(--color-ink)] text-[var(--color-paper)] flex items-center justify-center font-bold font-mono text-sm shadow-xs">
                  RZ
                </div>
                <div>
                  <div className="flex items-center gap-1.5">
                    <span className="font-semibold text-sm text-[var(--color-ink)]">
                      {merchant} ✓
                    </span>
                  </div>
                  <p className="text-[11px] text-[var(--color-ink-subtle)]">
                    Sub: {journey.subscription_id} · Journey: {journey.journey_id}
                  </p>
                </div>
              </div>

              <div className="text-right">
                <span className="text-[10px] uppercase tracking-wider text-[var(--color-ink-subtle)] font-medium">
                  Amount Due
                </span>
                <p className="numeric text-2xl font-bold text-[var(--color-ink)]">
                  {formatINR(journey.amount_minor)}
                </p>
              </div>
            </div>

            {paid ? (
              <div className="py-8 text-center space-y-3">
                <div className="h-12 w-12 rounded-full bg-[var(--color-approved-wash)] text-[var(--color-approved)] flex items-center justify-center mx-auto border border-[var(--color-approved)]/30">
                  <CheckCircle2 size={24} />
                </div>
                <h3 className="text-lg font-semibold text-[var(--color-ink)]">Payment Successful</h3>
                <p className="text-xs text-[var(--color-ink-muted)] max-w-xs mx-auto leading-relaxed">
                  Your payment of {formatINR(journey.amount_minor)} has been cleared via Razorpay. Your UPI AutoPay mandate remains active and your subscription services are uninterrupted.
                </p>
                <p className="text-[10px] text-[var(--color-ink-subtle)] numeric">
                  Journey state: {journey.state}
                </p>
              </div>
            ) : (
              <>
                <div className="p-3.5 rounded-md bg-[var(--color-info-wash)] border border-[var(--color-info)]/20 text-xs space-y-1">
                  <div className="flex items-center gap-1.5 text-[var(--color-info)] font-semibold">
                    <AlertCircle size={14} />
                    <span>AutoPay Debit Paused · {journey.root_cause ?? 'UNKNOWN'}</span>
                  </div>
                  <p className="text-[var(--color-ink)] leading-relaxed">
                    Your scheduled AutoPay debit was paused. Clear this now in 1 tap to maintain continuous billing. Service remains active.
                  </p>
                </div>

                <div className="space-y-2.5">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-ink-subtle)]">
                    Instant Recovery Options
                  </span>

                  <div
                    onClick={() => setSelectedMethod('upi')}
                    className={`p-3 rounded-md border cursor-pointer transition-colors flex items-center gap-3 ${
                      selectedMethod === 'upi'
                        ? 'border-[var(--color-ink)] bg-[var(--color-surface-subtle)]'
                        : 'border-[var(--color-line)] hover:border-[var(--color-line-strong)]'
                    }`}
                  >
                    <Smartphone size={18} className="text-[var(--color-ink)]" />
                    <div className="flex-1">
                      <p className="text-xs font-semibold text-[var(--color-ink)]">One-Tap UPI App</p>
                      <p className="text-[11px] text-[var(--color-ink-subtle)]">Google Pay, PhonePe, Paytm, BHIM</p>
                    </div>
                    {selectedMethod === 'upi' && <CheckCircle2 size={15} className="text-[var(--color-approved)]" />}
                  </div>

                  <div
                    onClick={() => setSelectedMethod('card')}
                    className={`p-3 rounded-md border cursor-pointer transition-colors flex items-center gap-3 ${
                      selectedMethod === 'card'
                        ? 'border-[var(--color-ink)] bg-[var(--color-surface-subtle)]'
                        : 'border-[var(--color-line)] hover:border-[var(--color-line-strong)]'
                    }`}
                  >
                    <CreditCard size={18} className="text-[var(--color-ink)]" />
                    <div className="flex-1">
                      <p className="text-xs font-semibold text-[var(--color-ink)]">Update E-Mandate Card</p>
                      <p className="text-[11px] text-[var(--color-ink-subtle)]">Visa, Mastercard, RuPay</p>
                    </div>
                    {selectedMethod === 'card' && <CheckCircle2 size={15} className="text-[var(--color-approved)]" />}
                  </div>
                </div>

                <Button
                  variant="primary"
                  size="lg"
                  loading={busy}
                  onClick={handlePay}
                  className="w-full"
                >
                  <Lock size={14} />
                  <span>Pay {formatINR(journey.amount_minor)} Securely via Razorpay</span>
                  <ArrowRight size={14} />
                </Button>

                {error && (
                  <p className="text-[11px] text-[var(--color-rejected)] text-center">{error}</p>
                )}
              </>
            )}

            <div className="pt-4 border-t border-[var(--color-line)] flex items-center justify-between text-[10.5px] text-[var(--color-ink-subtle)] font-mono">
              <span className="flex items-center gap-1">
                <Lock size={11} />
                <span>256-Bit SSL</span>
              </span>
              <span>RBI E-Mandate Compliant</span>
              <span>NPCI UPI 2.0 Certified</span>
            </div>
          </Card>
        </div>
      </div>

      <NudgePreview />
    </div>
  );
};
