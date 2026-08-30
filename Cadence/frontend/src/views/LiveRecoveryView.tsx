// LiveRecoveryView (R2): the single-screen working demo.
//
// 3-step guided control on the left: (1) create a real Razorpay test
// customer, (2) trigger a real payment_link.paid failure (HMAC-signed
// webhook to /webhooks/razorpay), (3) "Pay now" opens the real
// short_url so the judge can pay with the test UPI id. The center
// column shows the live journey with the chat-style reasoning panel.
// The right column shows the live evidence: webhook event id, customer
// id, payment link id, payment id, the LLM-written message, and
// buttons to open the Razorpay dashboard / jump into the audit page.
//
// This view is wired to /api/live/* (501 with a clear message when
// Razorpay keys are absent) so the buildathon laptop can show the
// "real Razorpay" story even without keys. The build exercise
// exposes both: the live path AND a 'simulate locally' fallback
// so the demo never hangs on missing infrastructure.

import React, { useState, useCallback, useEffect } from 'react';
import {
  Card, CardHeader, Badge, Button, PageHeader, EmptyState,
} from '../components/primitives';
import { api } from '../services/api';
import {
  Play, ExternalLink, ShieldAlert, MessageCircle, FileText,
  CheckCircle2, ChevronRight, RotateCcw, AlertTriangle,
} from 'lucide-react';

const Copyable: React.FC<{ value: string; label?: string }> = ({ value, label }) => {
  const [copied, setCopied] = React.useState(false);
  return (
    <span className="inline-flex items-center gap-1.5">
      {label && <span className="text-[var(--color-ink-muted)]">{label}:</span>}
      <code className="bg-[var(--color-paper)] px-1.5 py-0.5 rounded">{value}</code>
      <button
        type="button"
        onClick={() => { copyToClipboard(value); setCopied(true); setTimeout(() => setCopied(false), 1200); }}
        title={`Copy ${value}`}
        className="text-[10px] text-[var(--color-accent)] hover:underline"
      >
        {copied ? 'copied' : 'copy'}
      </button>
    </span>
  );
};


const copyToClipboard = (text: string) => {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).catch(() => {});
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  } catch {}
};

interface LiveCustomer {
  id: string;
  email: string;
  contact: string;
  simulated: boolean;
}

interface LivePaymentLink {
  id: string;
  short_url: string;
  reference_id: string;
  amount_minor: number;
  status: string;
  simulated: boolean;
}

interface LiveFailureResult {
  journey_id: string;
  event_id: string;
  subscription_id: string;
  payment_link: LivePaymentLink;
}

type Step = 'idle' | 'customer' | 'failure' | 'paid' | 'error';

const RAZORPAY_DASHBOARD_LINKS = {
  paymentLinks: 'https://dashboard.razorpay.com/app/payment-links',
  payments: 'https://dashboard.razorpay.com/app/payments',
  webhooks: 'https://dashboard.razorpay.com/app/webhooks',
};

export const LiveRecoveryView: React.FC = () => {
  const [step, setStep] = useState<Step>('idle');
  const [error, setError] = useState<string | null>(null);
  const [customer, setCustomer] = useState<LiveCustomer | null>(null);
  const [failure, setFailure] = useState<LiveFailureResult | null>(null);
  const [journeyState, setJourneyState] = useState<string>('OPENED');
  const [pollHandle, setPollHandle] = useState<number | null>(null);
  const [recoverDisabled, setRecoverDisabled] = useState(false);

  // Recipient contact (persisted to localStorage so the demo
  // never re-asks). Judge can type their own email to prove the
  // Resend live send, OR leave blank for the bubble-only demo.
  const [recipientEmail, setRecipientEmail] = useState<string>(
    () => localStorage.getItem('cadence.recipient.email') ?? '',
  );
  const [recipientPhone, setRecipientPhone] = useState<string>(
    () => localStorage.getItem('cadence.recipient.phone') ?? '',
  );
  const [sendStatus, setSendStatus] = useState<{ kind: 'idle' | 'sending' | 'sent' | 'error'; msg?: string }>({ kind: 'idle' });

  useEffect(() => {
    localStorage.setItem('cadence.recipient.email', recipientEmail);
  }, [recipientEmail]);
  useEffect(() => {
    localStorage.setItem('cadence.recipient.phone', recipientPhone);
  }, [recipientPhone]);

  const sendToMyEmail = useCallback(async () => {
    if (!recipientEmail) {
      setSendStatus({ kind: 'error', msg: 'Type your email above first.' });
      return;
    }
    setSendStatus({ kind: 'sending' });
    try {
      const r = await api.sendLiveEmail({
        reference_id: failure?.payment_link.reference_id ?? '',
        to: recipientEmail,
      });
      if (r.status === 'sent' || r.http === 200) {
        setSendStatus({ kind: 'sent', msg: `Sent to ${recipientEmail}` });
      } else {
        setSendStatus({ kind: 'error', msg: r.detail ?? r.status ?? 'send failed' });
      }
    } catch (e: any) {
      setSendStatus({ kind: 'error', msg: e?.message ?? 'send failed' });
    }
  }, [recipientEmail, failure]);

  // The body of the LLM-written nudge for the current journey. Comes
  // from the agent.thinking event in the audit chain.
  const [nudgeBody, setNudgeBody] = useState<string>('');
  const [nudgeSubject, setNudgeSubject] = useState<string>('');
  useEffect(() => {
    if (!failure) { setNudgeBody(''); setNudgeSubject(''); return; }
    api.getJourneyReasoning(failure.journey_id).then((r) => {
      const llmStep = (r.steps ?? []).find((s: any) => s.role === 'agent_thinking');
      const body = llmStep?.detail ?? '';
      setNudgeBody(body);
      setNudgeSubject(llmStep?.channel ? `Your ${llmStep.channel} update` : 'Action needed on your Cadence subscription');
    }).catch(() => {});
  }, [failure?.journey_id]);

  // Stop polling on unmount.
  useEffect(() => () => {
    if (pollHandle !== null) window.clearInterval(pollHandle);
  }, [pollHandle]);

  const createCustomer = useCallback(async () => {
    setError(null); setStep('customer');
    try {
      const r = await api.createLiveCustomer({
        name: 'Judge (Buildathon)',
        email: 'judge@buildathon.local',
        contact: '+919999900000',
      });
      setCustomer(r);
    } catch (e: any) {
      setError(e?.message ?? 'create_customer failed');
      setStep('error');
    }
  }, []);

  const triggerFailure = useCallback(async () => {
    if (!customer) return;
    setError(null); setStep('failure');
    try {
      const r = await api.createLiveFailure({ customer_id: customer.id });
      setFailure(r);
      setJourneyState('INTERVENING');
      // Start polling the journey for the WAITING_OUTCOME -> RECOVERED flip.
      const handle = window.setInterval(async () => {
        try {
          const j = await api.getJourney(r.journey_id);
          setJourneyState(j.state);
          if (j.state === 'RECOVERED' || j.state === 'CLOSED_UNRECOVERED' || j.state === 'HUMAN_REVIEW') {
            window.clearInterval(handle);
            setPollHandle(null);
            setStep('paid');
          }
        } catch { /* keep polling */ }
      }, 2000);
      setPollHandle(handle);
    } catch (e: any) {
      setError(e?.message ?? 'create_live_failure failed');
      setStep('error');
    }
  }, [customer]);

  const markPaid = useCallback(async () => {
    // Convenience for the demo when there is no real Razorpay link
    // (sim mode). The SPA posts a payment_link.paid webhook into our
    // own gateway so the close-the-loop animation can play.
    if (!failure) return;
    setRecoverDisabled(true);
    try {
      // B-fix: let the backend generate a unique payment_id per
      // call (the old constant 'pay_LIVE_DEMO' deduplicated the
      // capture task on the second run, stranding the journey in
      // INTERVENING).
      await api.simulateLivePaymentLinkPaid({
        reference_id: failure.payment_link.reference_id,
      });
    } catch (e: any) {
      setError(e?.message ?? 'simulate_paid failed');
      setStep('error');
    }
  }, [failure]);

  const reset = useCallback(() => {
    if (pollHandle !== null) window.clearInterval(pollHandle);
    setPollHandle(null);
    setStep('idle');
    setError(null);
    setCustomer(null);
    setFailure(null);
    setJourneyState('OPENED');
    setRecoverDisabled(false);
  }, [pollHandle]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Live Recovery"
        description="Run the full recovery flow end-to-end. Real Razorpay test-mode customer and payment link, real HMAC-signed webhook."
        action={
          <div className="flex gap-2">
            <Button onClick={reset} variant="secondary" size="sm">
              <RotateCcw size={14} className="inline-block mr-1" />
              Reset
            </Button>
          </div>
        }
      />

      {error && (
        <Card className="p-4 border-2 border-[var(--color-coral)]/40 bg-[var(--color-coral)]/5">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-[var(--color-coral)]" />
            <div>
              <div className="text-sm font-medium text-[var(--color-ink)]">Step error</div>
              <div className="text-xs text-[var(--color-ink-muted)] mt-1 font-mono">{error}</div>
              <Button onClick={reset} size="sm" className="mt-3">Try again</Button>
            </div>
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: guided 3-step control */}
        <div className="space-y-4">
          <StepCard
            n={1}
            title="Create Razorpay customer"
            done={!!customer}
            active={step === 'customer'}
            cta={!customer ? (
              <Button onClick={createCustomer} disabled={step !== 'idle' && step !== 'error'} variant="primary" size="sm">
                <Play size={13} className="inline-block mr-1" />
                Create real customer
              </Button>
            ) : (
              <div className="space-y-1">
                <div className="text-[12px] text-[var(--color-ink-muted)]">id</div>
                <Copyable value={customer.id} />
                {customer.simulated && (
                  <Badge tone="info">simulated (no Razorpay keys)</Badge>
                )}
              </div>
            )}
          />

          <StepCard
            n={2}
            title="Trigger payment failure"
            done={!!failure}
            active={step === 'failure'}
            cta={customer && !failure ? (
              <Button onClick={triggerFailure} variant="primary" size="sm">
                <Play size={13} className="inline-block mr-1" />
                Create payment link + post failure webhook
              </Button>
            ) : failure ? (
              <div className="space-y-1 text-[12px] font-mono">
                <div>journey <Copyable value={failure.journey_id} /></div>
                <div>link <Copyable value={failure.payment_link.id} /></div>
                <div>ref <Copyable value={failure.payment_link.reference_id} /></div>
                <a
                  href={failure.payment_link.short_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-[var(--color-accent)] underline mt-2"
                >
                  <ExternalLink size={11} /> {failure.payment_link.short_url}
                </a>
              </div>
            ) : (
              <div className="text-[12px] text-[var(--color-ink-muted)]">Run step 1 first.</div>
            )}
          />

          <StepCard
            n={3}
            title="Pay now"
            done={step === 'paid' && journeyState === 'RECOVERED'}
            active={step === 'paid' && journeyState !== 'RECOVERED'}
            cta={failure ? (
              <div className="space-y-2">
                <Button onClick={markPaid} disabled={recoverDisabled} variant="primary" size="sm">
                  <CheckCircle2 size={13} className="inline-block mr-1" />
                  Simulate payment_link.paid (close-the-loop)
                </Button>
                <a
                  href={failure.payment_link.short_url}
                  target="_blank"
                  rel="noreferrer"
                  className="block text-[12px] text-[var(--color-ink-muted)] underline"
                >
                  Or open the real link in a new tab
                </a>
              </div>
            ) : (
              <div className="text-[12px] text-[var(--color-ink-muted)]">Run step 2 first.</div>
            )}
          />
        </div>

        {/* Center: live journey state */}
        <div>
          <Card className="p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold">
                Selected journey
              </div>
              {failure && journeyState !== 'RECOVERED' && (
                <span className="flex items-center gap-1.5 text-[11px] text-[var(--color-coral)] font-medium">
                  <span className="inline-block h-2 w-2 rounded-full bg-[var(--color-coral)] animate-pulse" />
                  {journeyState === 'WAITING_OUTCOME' || journeyState === 'INTERVENING'
                    ? 'Waiting for payment webhook… (auto-refresh)'
                    : `Live: ${journeyState}`}
                </span>
              )}
              {journeyState === 'RECOVERED' && (
                <Badge tone="approved">RECOVERED</Badge>
              )}
            </div>
            {failure ? (
              <div className="space-y-2 text-[12px] font-mono">
                <div><span className="text-[var(--color-ink-muted)]">journey_id:</span> {failure.journey_id}</div>
                <div><span className="text-[var(--color-ink-muted)]">subscription_id:</span> {failure.subscription_id}</div>
                <div><span className="text-[var(--color-ink-muted)]">state:</span> {journeyState}</div>
                <div className="pt-2 text-[var(--color-ink-muted)] text-[11px]">
                  The agent reasoning for this journey is in the
                  <a href="#/journeys" className="underline ml-1">Journeys &amp; Audit</a>
                  {' '}tab (click the journey row to open the chat panel).
                </div>
              </div>
            ) : (
              <EmptyState
                title="No live journey yet"
                description="Run step 1 and step 2 to create a customer + payment link. The journey will appear here and the SPA will poll for the outcome."
              />
            )}
          </Card>
        </div>

        {/* Right: live evidence */}
        <div>
          <Card className="p-5">
            <div className="text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold mb-3">
              Live evidence
            </div>
            {failure ? (
              <ul className="space-y-2 text-[12px] font-mono">
                <li><Copyable value={failure.event_id} label="event id" /></li>
                <li><Copyable value={customer?.id ?? ''} label="customer id" /></li>
                <li><Copyable value={failure.payment_link.id} label="payment link id" /></li>
                <li><Copyable value={failure.payment_link.short_url} label="short_url" /></li>
              </ul>
            ) : (
              <EmptyState
                title="No live data yet"
                description="Webhook event id, customer id, payment link id and the LLM-written nudge will appear here as the demo progresses."
              />
            )}
            {/* NEW: Email preview + send + Audio player */}
            <div className="mt-4 pt-4 border-t border-[var(--color-line)] space-y-3">
              <AudioCard nudgeBody={nudgeBody} nudgeSubject={nudgeSubject} />

              <div className="rounded-md border border-[var(--color-line)] p-3">
                <div className="text-[10px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold mb-1">Email preview</div>
                <div className="text-[12px]"><span className="text-[var(--color-ink-muted)]">Subject:</span> {nudgeSubject || '(subject appears after the LLM writes)'}</div>
                <pre className="text-[11px] font-mono mt-1 whitespace-pre-wrap text-[var(--color-ink)] max-h-32 overflow-auto">{nudgeBody || '(Hinglish body appears once the engine writes it; you can also send it to your email above)'}</pre>
              </div>

              <a href={RAZORPAY_DASHBOARD_LINKS.paymentLinks} target="_blank" rel="noreferrer"
                 className="flex items-center gap-1.5 text-[12px] text-[var(--color-accent)] underline">
                <ExternalLink size={11} /> Open this link in Razorpay Dashboard
              </a>
              <a href={failure?.payment_link.short_url ?? '#'} target="_blank" rel="noreferrer"
                 className="flex items-center gap-1.5 text-[12px] text-[var(--color-ink)] underline">
                <ExternalLink size={11} /> Open the payment page in a new tab
              </a>
              <a href="#/journeys" className="flex items-center gap-1.5 text-[12px] text-[var(--color-accent)] underline">
                <FileText size={11} /> View audit trail
              </a>
            </div>
          </Card>
        </div>
      </div>

      <Card className="p-5">
        <div className="flex items-start gap-3">
          <MessageCircle className="h-5 w-5 text-[var(--color-accent)] mt-0.5" />
          <div className="flex-1 space-y-3">
            <div>
              <div className="text-sm font-medium text-[var(--color-ink)]">
                Send the Hinglish nudge to your email (proof for the judge)
              </div>
              <div className="text-[12px] text-[var(--color-ink-muted)] mt-0.5">
                Type your email below. After step 2 the engine writes a real Hinglish body — press the
                button and the SPA POSTs it to the Resend live-send endpoint so the message lands in
                your inbox within a few seconds.
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-[10px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold mb-1">
                  Your email
                </label>
                <input
                  type="email"
                  value={recipientEmail}
                  onChange={(e) => setRecipientEmail(e.target.value)}
                  placeholder="you@yourcompany.com"
                  className="w-full rounded-md border border-[var(--color-line)] bg-[var(--color-paper)] px-3 py-2 text-[13px] focus:outline-none focus:border-[var(--color-accent)]"
                />
              </div>
              <div>
                <label className="block text-[10px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold mb-1">
                  Your phone (optional, for SMS)
                </label>
                <input
                  type="tel"
                  value={recipientPhone}
                  onChange={(e) => setRecipientPhone(e.target.value)}
                  placeholder="+91 99999 00000"
                  className="w-full rounded-md border border-[var(--color-line)] bg-[var(--color-paper)] px-3 py-2 text-[13px] focus:outline-none focus:border-[var(--color-accent)]"
                />
              </div>
            </div>
            <div className="flex items-center gap-3 pt-1">
              <Button
                onClick={sendToMyEmail}
                disabled={sendStatus.kind === 'sending' || !failure}
                variant="primary"
                size="sm"
              >
                <MessageCircle size={13} className="inline-block mr-1" />
                {sendStatus.kind === 'sending' ? 'Sending…' : 'Send Hinglish nudge to my email'}
              </Button>
              {sendStatus.kind === 'sent' && (
                <Badge tone="approved">{sendStatus.msg ?? 'Sent'}</Badge>
              )}
              {sendStatus.kind === 'error' && (
                <span className="text-[12px] text-[var(--color-rejected)]">{sendStatus.msg}</span>
              )}
              {!failure && sendStatus.kind === 'idle' && (
                <span className="text-[11px] text-[var(--color-ink-subtle)]">
                  Run steps 1 and 2 first to unlock the send button.
                </span>
              )}
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
};


const AudioCard: React.FC<{ nudgeBody: string; nudgeSubject: string }> = ({ nudgeBody, nudgeSubject }) => {
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [reason, setReason] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const play = useCallback(async () => {
    if (!nudgeBody) return;
    setLoading(true);
    try {
      const r = await api.playLiveVoice(nudgeBody);
      setAudioUrl(r.audio_data_url);
      setReason(r.reason);
    } catch (e: any) {
      setReason(`error: ${e?.message ?? 'unknown'}`);
    } finally {
      setLoading(false);
    }
  }, [nudgeBody]);

  if (!nudgeBody) {
    return (
      <div className="rounded-md border border-[var(--color-line)] p-3 text-[11px] text-[var(--color-ink-muted)]">
        Audio (Hinglish) — appears once the engine writes the body
      </div>
    );
  }
  return (
    <div className="rounded-md border border-[var(--color-line)] p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="text-[10px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold">Hinglish audio</div>
        {reason && <Badge tone={reason.includes('elevenlabs') ? 'approved' : reason.includes('sarvam') ? 'info' : 'pending'}>{reason}</Badge>}
      </div>
      {audioUrl ? (
        <audio controls src={audioUrl} className="w-full" />
      ) : (
        <Button onClick={play} disabled={loading} size="sm">
          {loading ? 'Loading...' : 'Play Hinglish'}
        </Button>
      )}
    </div>
  );
};

const StepCard: React.FC<{
  n: number; title: string; done: boolean; active: boolean; cta: React.ReactNode;
}> = ({ n, title, done, active, cta }) => (
  <Card className={`p-4 ${active ? 'border-2 border-[var(--color-accent)]/40 bg-[var(--color-accent)]/5' : ''}`}>
    <div className="flex items-center gap-2 mb-3">
      <div className={`flex items-center justify-center w-7 h-7 rounded-full text-[12px] font-mono font-semibold
        ${done ? 'bg-[var(--color-mint)] text-white' : 'bg-[var(--color-paper)] text-[var(--color-ink-muted)]'}`}>
        {done ? <CheckCircle2 size={14} /> : n}
      </div>
      <div className="text-sm font-medium text-[var(--color-ink)]">{title}</div>
      {active && (
        <span className="ml-auto flex items-center gap-1.5 text-[11px] text-[var(--color-coral)] font-medium">
          <span className="inline-block h-2 w-2 rounded-full bg-[var(--color-coral)] animate-pulse" />
          live
        </span>
      )}
    </div>
    {cta}
  </Card>
);
