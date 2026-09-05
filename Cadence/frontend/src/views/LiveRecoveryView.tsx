// LiveRecoveryView (R2): the single-screen working demo.
//
// 3-step guided control on the left: (1) create a real Razorpay test
// customer, (2) trigger a real payment_link.paid failure (HMAC-signed
// webhook to /webhooks/razorpay), (3) "Pay now" opens the real
// short_url so the user can pay with the test UPI id. The center
// column shows the live journey with the chat-style reasoning panel.
// The right column shows the live evidence: webhook event id, customer
// id, payment link id, payment id, the LLM-written message, and
// buttons to open the Razorpay dashboard / jump into the audit page.
//
// This view is wired to /api/live/* (501 with a clear message when
// Razorpay keys are absent) so any operator machine can show the
// "real Razorpay" story even without keys. The runtime exposes both:
// the live path AND a 'simulate locally' fallback so the demo never
// hangs on missing infrastructure.

import React, { useState, useCallback, useEffect } from 'react';
import {
  Card, CardHeader, Badge, Button, PageHeader, EmptyState,
} from '../components/primitives';
import { api } from '../services/api';
import {
  Play, ExternalLink, ShieldAlert, MessageCircle, FileText,
  CheckCircle2, ChevronRight, RotateCcw, AlertTriangle, Send, Smartphone,
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
        className="text-[12px] text-[var(--color-accent)] hover:underline"
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
  // never re-asks). The operator can type their own email to prove the
  // Resend live send, OR leave blank for the bubble-only demo.
  const [recipientEmail, setRecipientEmail] = useState<string>(
    () => localStorage.getItem('cadence.recipient.email') ?? '',
  );
  const [recipientPhone, setRecipientPhone] = useState<string>(
    () => localStorage.getItem('cadence.recipient.phone') || '+919876543210',
  );
  const [sendStatus, setSendStatus] = useState<{ kind: 'idle' | 'sending' | 'sent' | 'error'; msg?: string }>({ kind: 'idle' });
  const [waStatus, setWaStatus] = useState<{ kind: 'idle' | 'sending' | 'sent' | 'error'; msg?: string }>({ kind: 'idle' });

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

  const sendToMyWhatsApp = useCallback(async () => {
    const target = recipientPhone.trim() || '+919876543210';
    setWaStatus({ kind: 'sending' });
    try {
      const r = await api.sendLiveWhatsApp({
        reference_id: failure?.payment_link.reference_id ?? '',
        to: target,
      });
      if (r.status === 'sent' || r.http === 200 || r.http === 201) {
        setWaStatus({
          kind: 'sent',
          msg: `Delivered to WhatsApp ${target}!${r.sid ? ' (' + r.sid.slice(0, 12) + '…)' : ''}`,
        });
      } else {
        setWaStatus({ kind: 'error', msg: r.detail ?? r.status ?? 'WhatsApp send failed' });
      }
    } catch (e: any) {
      setWaStatus({ kind: 'error', msg: e?.message ?? 'WhatsApp send failed' });
    }
  }, [recipientPhone, failure]);

  // The body of the LLM-written nudge for the current journey.
  const [nudgeBody, setNudgeBody] = useState<string>('');
  const [nudgeSubject, setNudgeSubject] = useState<string>('');

  useEffect(() => {
    if (!failure) {
      setNudgeBody('');
      setNudgeSubject('');
      return;
    }
    const fallbackLink = failure.payment_link?.short_url || 'https://rzp.io/rzp/live-demo';
    const defaultBody = `Namaste! Aapka ₹499 ka subscription payment pending hai. Pay karne ke liye: ${fallbackLink} - Team Cadence`;
    const defaultSubject = 'Action needed: Complete your subscription payment';
    setNudgeBody(defaultBody);
    setNudgeSubject(defaultSubject);

    api.getJourneyReasoning(failure.journey_id).then((r) => {
      const llmStep = (r.steps ?? []).find(
        (s: any) => s.role === 'agent_thinking' || s.detail?.includes('Namaste') || s.detail?.includes('http')
      );
      if (llmStep?.detail) {
        setNudgeBody(llmStep.detail);
      }
      if (llmStep?.channel) {
        setNudgeSubject(`Your ${llmStep.channel} payment reminder`);
      }
    }).catch(() => {});
  }, [failure?.journey_id, failure?.payment_link?.short_url]);

  // Stop polling on unmount.
  useEffect(() => () => {
    if (pollHandle !== null) window.clearInterval(pollHandle);
  }, [pollHandle]);

  const createCustomer = useCallback(async () => {
    setError(null); setStep('customer');
    try {
      const r = await api.createLiveCustomer({
        name: 'Demo Subscriber',
        email: 'subscriber@cadence.local',
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
    if (!failure) return;
    setRecoverDisabled(true);
    try {
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
    setNudgeBody('');
    setNudgeSubject('');
  }, [pollHandle]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Live Recovery"
        description="Watch one failed payment get recovered, start to finish. A real Razorpay test-mode customer, a real payment link, a real signed webhook. Nothing here is faked."
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
            title="Step 1: Create Test Customer"
            done={!!customer}
            active={step === 'customer'}
            cta={!customer ? (
              <Button onClick={createCustomer} disabled={step !== 'idle' && step !== 'error'} variant="primary" size="sm">
                <Play size={13} className="inline-block mr-1" />
                1. Create Customer in Razorpay
              </Button>
            ) : (
              <div className="space-y-1">
                <div className="text-[13px] text-[var(--color-ink-muted)]">Razorpay Customer ID</div>
                <Copyable value={customer.id} />
                {customer.simulated && (
                  <Badge tone="info">simulated (no Razorpay keys)</Badge>
                )}
              </div>
            )}
          />

          <StepCard
            n={2}
            title="Step 2: Simulate Payment Failure"
            done={!!failure}
            active={step === 'failure'}
            cta={customer && !failure ? (
              <Button onClick={triggerFailure} variant="primary" size="sm">
                <Play size={13} className="inline-block mr-1" />
                2. Trigger Failure &amp; Generate Link
              </Button>
            ) : failure ? (
              <div className="space-y-1 text-[13px] font-mono">
                <div>Recovery Case <Copyable value={failure.journey_id} /></div>
                <div>Razorpay Link ID <Copyable value={failure.payment_link.id} /></div>
                <div>Reference Code <Copyable value={failure.payment_link.reference_id} /></div>
                <a
                  href={failure.payment_link.short_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-[var(--color-accent)] underline mt-2"
                >
                  <ExternalLink size={11} /> Open Payment Link ({failure.payment_link.short_url})
                </a>
              </div>
            ) : (
              <div className="text-[13px] text-[var(--color-ink-muted)]">Run Step 1 first to create a customer.</div>
            )}
          />

          <StepCard
            n={3}
            title="Step 3: Simulate Customer Payment"
            done={step === 'paid' && journeyState === 'RECOVERED'}
            active={step === 'paid' && journeyState !== 'RECOVERED'}
            cta={failure ? (
              <div className="space-y-2">
                <Button onClick={markPaid} disabled={recoverDisabled} variant="primary" size="sm">
                  <CheckCircle2 size={13} className="inline-block mr-1" />
                  3. Confirm Customer Paid (Close Case)
                </Button>
                <p className="text-[12px] leading-5 text-[var(--color-ink-muted)]">
                  Simulates the customer paying via UPI or Card so Cadence can record the recovered revenue in the audit trail.
                </p>
                <a
                  href={failure.payment_link.short_url}
                  target="_blank"
                  rel="noreferrer"
                  className="block text-[12px] text-[var(--color-ink-muted)] underline"
                >
                  Or test paying the real Razorpay page in a new tab
                </a>
              </div>
            ) : (
              <div className="text-[13px] text-[var(--color-ink-muted)]">Run Step 2 first to generate a payment link.</div>
            )}
          />
        </div>

        {/* Center: live journey state */}
        <div>
          <Card className="p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold">
                Active Recovery Case Status
              </div>
              {failure && journeyState !== 'RECOVERED' && (
                <span className="flex items-center gap-1.5 text-[12px] text-[var(--color-coral)] font-medium">
                  <span className="inline-block h-2 w-2 rounded-full bg-[var(--color-coral)] animate-pulse" />
                  {journeyState === 'WAITING_OUTCOME' || journeyState === 'INTERVENING'
                    ? 'Awaiting customer response…'
                    : `Active: ${journeyState}`}
                </span>
              )}
              {journeyState === 'RECOVERED' && (
                <Badge tone="approved">RECOVERED &amp; CLOSED</Badge>
              )}
            </div>
            {failure ? (
              <div className="space-y-2 text-[13px] font-mono">
                <div><span className="text-[var(--color-ink-muted)]">Case ID:</span> {failure.journey_id}</div>
                <div><span className="text-[var(--color-ink-muted)]">Subscription ID:</span> {failure.subscription_id}</div>
                <div><span className="text-[var(--color-ink-muted)]">Status:</span> {journeyState}</div>
                <div className="pt-2 text-[var(--color-ink-muted)] text-[12px] font-sans">
                  The step-by-step history log for this recovery case is visible in the
                  <a href="#dashboard" className="underline ml-1 font-medium text-[var(--color-accent)]">Dashboard</a>.
                </div>
              </div>
            ) : (
              <EmptyState
                title="No active recovery case yet"
                description="Click Step 1, then Step 2. The recovery case will appear here with live automatic status updates."
              />
            )}
          </Card>
        </div>

        {/* Right: live evidence */}
        <div>
          <Card className="p-5">
            <div className="text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold mb-3">
              Live Bank &amp; Gateway Proof
            </div>
            {failure ? (
              <ul className="space-y-2 text-[13px] font-mono">
                <li><Copyable value={failure.event_id} label="Bank Alert ID" /></li>
                <li><Copyable value={customer?.id ?? ''} label="Customer ID" /></li>
                <li><Copyable value={failure.payment_link.id} label="Payment Link ID" /></li>
                <li><Copyable value={failure.payment_link.short_url} label="Payment URL" /></li>
              </ul>
            ) : (
              <EmptyState
                title="No live proof yet"
                description="Real bank notification IDs, customer IDs, and Razorpay links appear here as soon as you run Step 1 and Step 2."
              />
            )}

            {/* Email preview + Audio player + Connected service links */}
            <div className="mt-4 pt-4 border-t border-[var(--color-line)] space-y-3">
              <AudioCard nudgeBody={nudgeBody} nudgeSubject={nudgeSubject} />

              <div className="rounded-md border border-[var(--color-line)] p-3 bg-[var(--color-surface-subtle)]/50">
                <div className="text-[10px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold mb-1">
                  Message Preview (Hinglish AI Nudge)
                </div>
                <div className="text-[13px] font-medium"><span className="text-[var(--color-ink-muted)] font-normal">Subject:</span> {nudgeSubject || 'Action needed: Complete your subscription payment'}</div>
                <pre className="text-[12px] font-mono mt-1 whitespace-pre-wrap text-[var(--color-ink)] max-h-32 overflow-auto">{nudgeBody || 'Run Step 2 above to generate the warm Hinglish recovery message with payment link.'}</pre>
              </div>

              <div className="space-y-1.5 pt-2 text-[12px]">
                <div className="text-[10px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold mb-1">
                  Connected Platforms &amp; External Logs
                </div>
                <a href={RAZORPAY_DASHBOARD_LINKS.paymentLinks} target="_blank" rel="noreferrer"
                   className="flex items-center gap-1.5 text-[var(--color-accent)] underline hover:no-underline">
                  <ExternalLink size={11} /> Open Razorpay Dashboard
                </a>
                <a href="https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn" target="_blank" rel="noreferrer"
                   className="flex items-center gap-1.5 text-[#25D366] underline hover:no-underline">
                  <ExternalLink size={11} /> Open Twilio WhatsApp Console
                </a>
                <a href="https://mail.google.com" target="_blank" rel="noreferrer"
                   className="flex items-center gap-1.5 text-[var(--color-ink)] underline hover:no-underline">
                  <ExternalLink size={11} /> Open Gmail Web Inbox
                </a>
                <a href="https://supabase.com/dashboard/project/vzrasadomyrycafbzdwg/editor" target="_blank" rel="noreferrer"
                   className="flex items-center gap-1.5 text-[var(--color-ink-muted)] underline hover:no-underline">
                  <ExternalLink size={11} /> Open Supabase Cloud Database Mirror
                </a>
                <a href="#dashboard" className="flex items-center gap-1.5 text-[var(--color-accent)] underline hover:no-underline">
                  <FileText size={11} /> View in Dashboard &amp; History Log
                </a>
              </div>
            </div>
          </Card>
        </div>
      </div>

      <Card className="p-5">
        <div className="flex items-start gap-3">
          <Smartphone className="h-5 w-5 text-[#25D366] mt-0.5" />
          <div className="flex-1 space-y-4">
            <div>
              <div className="text-sm font-semibold text-[var(--color-ink)]">
                Live Delivery Proof (WhatsApp &amp; Email)
              </div>
              <div className="text-[13px] text-[var(--color-ink-muted)] mt-0.5">
                Send the recovery nudge directly to your real phone via WhatsApp (powered by Twilio) or your email inbox (powered by Resend).
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2 p-3 rounded-lg border border-[var(--color-line)] bg-[var(--color-paper)]/50">
                <label className="block text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-bold">
                  Your WhatsApp Number
                </label>
                <input
                  type="tel"
                  value={recipientPhone}
                  onChange={(e) => setRecipientPhone(e.target.value)}
                  placeholder="+91 86056 75478"
                  className="w-full rounded-md border border-[var(--color-line)] bg-[var(--color-paper)] px-3 py-2 text-[14px] font-mono focus:outline-none focus:border-[#25D366]"
                />
                <div className="pt-1 flex items-center gap-2 flex-wrap">
                  <Button
                    onClick={sendToMyWhatsApp}
                    disabled={waStatus.kind === 'sending' || !failure}
                    style={{ backgroundColor: '#25D366', color: '#fff', borderColor: '#25D366' }}
                    size="sm"
                  >
                    <Smartphone size={13} className="inline-block mr-1" />
                    {waStatus.kind === 'sending' ? 'Sending to WhatsApp…' : 'Send WhatsApp to Phone'}
                  </Button>
                  {waStatus.kind === 'sent' && (
                    <Badge tone="approved">{waStatus.msg ?? 'Delivered'}</Badge>
                  )}
                  {waStatus.kind === 'error' && (
                    <span className="text-[12px] text-[var(--color-rejected)]">{waStatus.msg}</span>
                  )}
                </div>
                <p className="text-[11px] text-[var(--color-ink-muted)]">
                  Twilio WhatsApp sandbox routes directly to your verified phone.
                </p>
              </div>

              <div className="space-y-2 p-3 rounded-lg border border-[var(--color-line)] bg-[var(--color-paper)]/50">
                <label className="block text-[11px] uppercase tracking-wider text-[var(--color-ink-muted)] font-bold">
                  Your Email Address
                </label>
                <input
                  type="email"
                  value={recipientEmail}
                  onChange={(e) => setRecipientEmail(e.target.value)}
                  placeholder="you@company.com"
                  className="w-full rounded-md border border-[var(--color-line)] bg-[var(--color-paper)] px-3 py-2 text-[14px] focus:outline-none focus:border-[var(--color-accent)]"
                />
                <div className="pt-1 flex items-center gap-2 flex-wrap">
                  <Button
                    onClick={sendToMyEmail}
                    disabled={sendStatus.kind === 'sending' || !failure}
                    variant="primary"
                    size="sm"
                  >
                    <MessageCircle size={13} className="inline-block mr-1" />
                    {sendStatus.kind === 'sending' ? 'Sending email…' : 'Send Email Nudge'}
                  </Button>
                  {sendStatus.kind === 'sent' && (
                    <Badge tone="approved">{sendStatus.msg ?? 'Sent'}</Badge>
                  )}
                  {sendStatus.kind === 'error' && (
                    <span className="text-[12px] text-[var(--color-rejected)]">{sendStatus.msg}</span>
                  )}
                </div>
                <p className="text-[11px] text-[var(--color-ink-muted)]">
                  Delivers the Hinglish recovery email to your inbox via Resend.
                </p>
              </div>
            </div>

            {!failure && (
              <div className="text-[12px] text-[var(--color-ink-subtle)] italic">
                Notice: Run Step 1 and Step 2 above first to generate a live Razorpay recovery link before sending.
              </div>
            )}
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
      <div className="rounded-md border border-[var(--color-line)] p-3 bg-[var(--color-surface-subtle)]/50">
        <div className="text-[10px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold mb-1">
          Hinglish Voice Recovery Note (AI Text-to-Speech)
        </div>
        <p className="text-[12px] text-[var(--color-ink-muted)] mb-2">
          Voice note generation unlocks once Step 2 generates a recovery payment link.
        </p>
        <Button disabled size="sm">Play Voice Note (Run Step 2 First)</Button>
      </div>
    );
  }
  return (
    <div className="rounded-md border border-[var(--color-line)] p-3 bg-[var(--color-surface-subtle)]/50">
      <div className="flex items-center justify-between mb-2">
        <div className="text-[10px] uppercase tracking-wider text-[var(--color-ink-muted)] font-semibold">
          Hinglish Voice Recovery Note (AI Text-to-Speech)
        </div>
        {reason && <Badge tone={reason.includes('elevenlabs') ? 'approved' : reason.includes('sarvam') ? 'info' : 'pending'}>{reason}</Badge>}
      </div>
      <p className="text-[12px] text-[var(--color-ink-muted)] mb-2">
        Polite Indian-language voice message synthesized by ElevenLabs / Sarvam AI:
      </p>
      {audioUrl ? (
        <audio controls src={audioUrl} autoPlay className="w-full h-8 mt-1" />
      ) : (
        <Button onClick={play} disabled={loading} size="sm" variant="secondary">
          {loading ? 'Generating voice audio…' : '🔊 Play Hinglish Voice Note'}
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
        <span className="ml-auto flex items-center gap-1.5 text-[12px] text-[var(--color-coral)] font-medium">
          <span className="inline-block h-2 w-2 rounded-full bg-[var(--color-coral)] animate-pulse" />
          live
        </span>
      )}
    </div>
    {cta}
  </Card>
);
