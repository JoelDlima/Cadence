import React, { useState } from 'react';
import { Play, FlaskConical, Sparkles, AlertCircle, Activity } from 'lucide-react';
import { Card, CardHeader, Badge, Button, Input, Select, PageHeader } from '../components/primitives';
import { api, formatINR } from '../services/api';

const DRILL_META: Record<string, { title: string; subtitle: string; icon: any }> = {
  duplicate_webhook: {
    title: '1. Duplicate Webhook Replay Attack',
    subtitle: 'Fires 5 simultaneous webhooks with identical payment IDs.',
    icon: Sparkles,
  },
  crash_resume: {
    title: '2. Process Crash & Mid-Flight Resume',
    subtitle: 'Simulates kill -9 mid-flight; rebuilds state from event log.',
    icon: Activity,
  },
  ai_provider_dead: {
    title: '3. Total AI Blackout (0 LLM Tokens)',
    subtitle: 'Revokes all AI keys; proves deterministic path still recovers.',
    icon: FlaskConical,
  },
  illegal_proposal_veto: {
    title: '4. Rogue Proposal Interception',
    subtitle: 'Injects illegal midnight outreach; proves Guardian veto.',
    icon: AlertCircle,
  },
};

interface DrillResult {
  status: 'idle' | 'running' | 'passed' | 'failed';
  detail?: string;
}

export const TestbenchView: React.FC = () => {
  const [subId, setSubId] = useState('sub_judge_live');
  const [custId, setCustId] = useState('cust_judge_01');
  const [declineCode, setDeclineCode] = useState('insufficient_funds');
  const [amount, setAmount] = useState(1499);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);

  const [activeDrill, setActiveDrill] = useState<string | null>(null);
  const [drillOutputs, setDrillOutputs] = useState<Record<string, DrillResult>>({});

  const handleInjectWebhook = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setResult(null);
    try {
      const res = await api.injectFailure({
        subscription_id: subId,
        customer_id: custId,
        failure_code: declineCode,
        amount_minor: amount * 100,
        error_description: 'Simulated failure from testbench',
      });
      setResult({ success: res.http_status === 200, data: res });
    } catch (err: any) {
      setResult({ success: false, error: err?.message ?? 'Webhook injection failed' });
    } finally {
      setLoading(false);
    }
  };

  const runChaosDrill = async (id: string) => {
    setActiveDrill(id);
    setDrillOutputs((prev) => ({ ...prev, [id]: { status: 'running' } }));
    try {
      const res = await api.runChaosDrill(id);
      setDrillOutputs((prev) => ({
        ...prev,
        [id]: { status: res.passed ? 'passed' : 'failed', detail: res.detail },
      }));
    } catch (err: any) {
      setDrillOutputs((prev) => ({
        ...prev,
        [id]: { status: 'failed', detail: err?.message ?? 'drill request failed' },
      }));
    } finally {
      setActiveDrill(null);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Simulation & Chaos Drills"
        description="Verify recovery resilience live. Inject payment failure webhooks or run reproducible chaos drills against the real engine."
        action={<Badge tone="approved">Live</Badge>}
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="p-6">
          <CardHeader
            title="Simulate Razorpay Webhook"
            subtitle="Backend signs with the configured webhook secret and re-posts through the gateway"
          />
          <form onSubmit={handleInjectWebhook} className="space-y-4 pt-4">
            <div>
              <label className="block text-[12.5px] font-medium text-[var(--color-ink)] mb-1">
                Subscription
              </label>
              <Input
                value={subId}
                onChange={(e) => setSubId(e.target.value)}
                placeholder="sub_..."
                className="numeric text-[13px]"
                required
              />
            </div>

            <div>
              <label className="block text-[12.5px] font-medium text-[var(--color-ink)] mb-1">
                Customer
              </label>
              <Input
                value={custId}
                onChange={(e) => setCustId(e.target.value)}
                placeholder="cust_..."
                className="numeric text-[13px]"
                required
              />
            </div>

            <div>
              <label className="block text-[12.5px] font-medium text-[var(--color-ink)] mb-1">
                Why it failed
              </label>
              <Select
                value={declineCode}
                onChange={(e) => setDeclineCode(e.target.value)}
                className="text-[12.5px]"
              >
                <option value="insufficient_funds">insufficient_funds (NO_FUNDS)</option>
                <option value="bank_technical_error">bank_technical_error (BANK_DOWN)</option>
                <option value="payment_collect_request_expired">payment_collect_request_expired (TIMEOUT)</option>
                <option value="vpa_resolution_failed">vpa_resolution_failed (BAD_VPA)</option>
                <option value="card_declined">card_declined (EXPIRED_INSTRUMENT)</option>
                <option value="payment_cancelled_by_user">payment_cancelled_by_user (CUSTOMER_ABORTED)</option>
                <option value="authentication_failed">authentication_failed (HARD_DECLINE)</option>
                <option value="__unknown__">__unknown__ (forces LLM or human)</option>
              </Select>
            </div>

            <div>
              <div className="flex items-center justify-between text-[12.5px] font-medium text-[var(--color-ink)] mb-1">
                <span>Amount (INR):</span>
                <span className="numeric font-semibold text-[var(--color-ink)]">{formatINR(amount * 100)}</span>
              </div>
              <input
                type="range"
                min="99"
                max="9999"
                step="100"
                value={amount}
                onChange={(e) => setAmount(Number(e.target.value))}
                className="w-full accent-[var(--color-ink)] cursor-pointer"
              />
            </div>

            <Button
              variant="primary"
              size="md"
              type="submit"
              loading={loading}
              className="w-full mt-2"
            >
              <Play size={14} />
              <span>Simulate a real payment failure</span>
            </Button>
          </form>

          {result && (
            <div className="mt-4 p-3.5 rounded bg-[var(--color-surface-subtle)] border border-[var(--color-line)] text-xs font-mono">
              <div className="flex items-center gap-2 mb-1.5">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: result.success ? 'var(--color-approved)' : 'var(--color-rejected)' }}
                />
                <span
                  className="font-semibold"
                  style={{ color: result.success ? 'var(--color-approved)' : 'var(--color-rejected)' }}
                >
                  {result.success
                    ? `Webhook Ingested (HTTP ${result.data.http_status})`
                    : 'Injection failed'}
                </span>
              </div>
              <pre className="text-[11.5px] text-[var(--color-ink-muted)] overflow-x-auto whitespace-pre-wrap">
                {JSON.stringify(result.data ?? result.error, null, 2)}
              </pre>
            </div>
          )}
        </Card>

        <Card className="p-6">
          <CardHeader
            title="4 Automated Chaos Drills"
            subtitle="Real drills against the live engine (server-side, run via /api/chaos/{drill}/run)"
          />
          <div className="space-y-4 pt-4">
            {Object.entries(DRILL_META).map(([id, meta]) => {
              const Icon = meta.icon;
              const drillState = drillOutputs[id];
              return (
                <div key={id} className="p-3.5 rounded-md border border-[var(--color-line)] bg-[var(--color-surface-subtle)] space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-start gap-2 min-w-0">
                      <Icon size={14} className="text-[var(--color-ink-muted)] mt-0.5 shrink-0" />
                      <div className="min-w-0">
                        <h4 className="text-xs font-semibold text-[var(--color-ink)]">
                          {meta.title}
                        </h4>
                        <p className="text-[11.5px] text-[var(--color-ink-muted)]">
                          {meta.subtitle}
                        </p>
                      </div>
                    </div>
                    <Button
                      variant="secondary"
                      size="sm"
                      loading={activeDrill === id}
                      onClick={() => runChaosDrill(id)}
                    >
                      Run
                    </Button>
                  </div>
                  {drillState && drillState.status !== 'idle' && (
                    <div
                      className="p-2.5 rounded border text-[11px] font-mono whitespace-pre-wrap"
                      style={{
                        backgroundColor: drillState.status === 'running'
                          ? 'var(--color-info-wash)'
                          : drillState.status === 'passed'
                            ? 'var(--color-approved-wash)'
                            : 'var(--color-rejected-wash)',
                        borderColor: drillState.status === 'running'
                          ? 'var(--color-info)'
                          : drillState.status === 'passed'
                            ? 'var(--color-approved)'
                            : 'var(--color-rejected)',
                        color: drillState.status === 'running'
                          ? 'var(--color-info)'
                          : drillState.status === 'passed'
                            ? 'var(--color-approved)'
                            : 'var(--color-rejected)',
                      }}
                    >
                      <strong>
                        {drillState.status === 'running'
                          ? 'RUNNING...'
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
        </Card>
      </div>
    </div>
  );
};
