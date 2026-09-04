import {
  Journey,
  TimelineEvent,
  Metrics,
  KillSwitchStatus,
  Status,
  Attention,
  Bank,
  AuditVerify,
  LlmSpend,
  GuardianStats,
  EvalSummary,
  ChaosResult,
  PayLink,
  CloudStatus,
  BanditRanking,
  InjectRequest,
  InjectResponse,
  AgentCompare,
  CheckoutIdleScan,
  SimulateCustomerReplyResult,
  PromiseList,
  PreDebitHistory,
  AgentReasoning,
  MerchantSummary,
  Anomaly,
  PaymentLinkRow,
  DashboardStats,
  CloudPlinks,
} from '../types';

export const inrFormatter = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
});

export const formatINR = (minor?: number | null) => {
  if (minor == null) return '—';
  return inrFormatter.format(minor / 100);
};

async function jsonFetch<T>(input: string, init?: RequestInit): Promise<T> {
  const res = await fetch(input, init);
  if (!res.ok) {
    let body = '';
    try { body = await res.text(); } catch {}
    throw new Error(`HTTP ${res.status}${body ? `: ${body.slice(0, 200)}` : ''}`);
  }
  return res.json() as Promise<T>;
}

async function postJson<T>(url: string, body: unknown): Promise<T> {
  return jsonFetch<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export const api = {


  async lifecycleForce(body: { reference_id: string; operation: string }): Promise<any> {
    return postJson('/api/live/lifecycle/' + body.operation.replace('force_', 'force-').replace('complete_journey', 'complete-journey'), body);
  },

  async lifecycleSmart(body: { reference_id: string; customer_hint?: string }): Promise<any> {
    return postJson('/api/live/lifecycle/smart', body);
  },

  async getStatus(): Promise<Status> {
    return jsonFetch<Status>('/api/status');
  },

  async getCloudStatus(): Promise<CloudStatus> {
    return jsonFetch<CloudStatus>('/api/cloud/status');
  },

  async getJourneys(): Promise<Journey[]> {
    return jsonFetch<Journey[]>('/api/journeys');
  },

  async getJourney(key: string): Promise<Journey> {
    return jsonFetch<Journey>(`/api/journey/${encodeURIComponent(key)}`);
  },

  async getTimeline(key: string): Promise<TimelineEvent[]> {
    const data = await jsonFetch<{ events: TimelineEvent[] }>(
      `/api/journeys/${encodeURIComponent(key)}/timeline`,
    );
    return data.events || [];
  },

  async getMetrics(): Promise<Metrics> {
    return jsonFetch<Metrics>('/api/metrics');
  },

  async getAttention(): Promise<Attention[]> {
    return jsonFetch<Attention[]>('/api/attention');
  },

  async getBanks(): Promise<Bank[]> {
    return jsonFetch<Bank[]>('/api/banks');
  },

  async getAuditVerify(): Promise<AuditVerify> {
    return jsonFetch<AuditVerify>('/api/audit/verify');
  },

  async getBanditRanked(limit: number = 25): Promise<{ rankings: BanditRanking[]; count: number }> {
    return jsonFetch<{ rankings: BanditRanking[]; count: number }>(
      `/api/bandit/ranked?limit=${limit}`,
    );
  },

  async getMerchantSummary(): Promise<MerchantSummary> {
    return jsonFetch<MerchantSummary>('/api/merchant/summary');
  },

  // --- Dashboard (Razorpay-style payment links + money counters) ---

  /** Every payment link the agent created, newest first. `status` filters to
   *  one tab; omit (or 'all') for everything. */
  async getPaymentLinks(limit: number = 50, status?: string): Promise<PaymentLinkRow[]> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (status && status !== 'all') params.set('status', status);
    return jsonFetch<PaymentLinkRow[]>(`/api/dashboard/payment-links?${params.toString()}`);
  },

  /** Money counters. `since` (ISO 8601) bounds the windowed numbers; the
   *  backend defaults to 24 h ago, the RBI mandate-revoke window. */
  async getDashboardStats(since?: string): Promise<DashboardStats> {
    const params = new URLSearchParams();
    if (since) params.set('since', since);
    const qs = params.toString();
    return jsonFetch<DashboardStats>(`/api/dashboard/stats${qs ? `?${qs}` : ''}`);
  },

  /** Server-side proxy of the Supabase cadence_payment_links mirror; the
   *  service_role key never reaches the browser. */
  async getCloudPlinks(limit: number = 50): Promise<CloudPlinks> {
    return jsonFetch<CloudPlinks>(`/api/cloud/plinks?limit=${limit}`);
  },

  async getAnomaly(windowMinutes: number = 10, threshold: number = 3): Promise<Anomaly[]> {
    return jsonFetch<Anomaly[]>(
      `/api/anomaly?window_minutes=${windowMinutes}&threshold=${threshold}`
    );
  },

  // R2: live recovery endpoints.
  async createLiveCustomer(body: { name?: string; email?: string; contact?: string } = {}): Promise<{
    id: string; email: string; contact: string; simulated: boolean;
  }> {
    return postJson('/api/live/customer', body);
  },

  async createLiveFailure(body: { customer_id: string }): Promise<{
    journey_id: string; event_id: string; subscription_id: string;
    payment_link: {
      id: string; short_url: string; reference_id: string;
      amount_minor: number; status: string; simulated: boolean;
    };
  }> {
    return postJson('/api/live/failure', body);
  },

  async sendLiveEmail(body: { reference_id: string; to: string; subject?: string; text?: string }): Promise<{ status: string; http: number; detail?: string }> {
    return postJson('/api/live/send-email', body);
  },

  async playLiveVoice(text: string, language: string = 'hinglish'): Promise<{ reason: string; is_stub: boolean; audio_data_url: string }> {
    const params = new URLSearchParams({ text, language });
    return jsonFetch<{ reason: string; is_stub: boolean; audio_data_url: string }>(`/api/voice/preview?${params.toString()}`);
  },

  async simulateLivePaymentLinkPaid(body: { reference_id: string; payment_id?: string }): Promise<{
    status: string; http: number; event_id: string; journey_id: string; subscription_id: string;
  }> {
    return postJson('/api/live/payment-paid', body);
  },

  async getNudgePreview(
    language: string = 'hinglish',
    amount_minor: number = 49900,
    link_url: string | null = null,
  ): Promise<{
    language: string;
    amount_minor: number;
    link_url: string | null;
    text: string;
    supported_languages: string[];
  }> {
    const params = new URLSearchParams({
      language,
      amount_minor: String(amount_minor),
    });
    if (link_url) {
      params.set('link_url', link_url);
    }
    return jsonFetch(`/api/nudge/preview?${params.toString()}`);
  },

  async getVoicePreview(
    language: string = 'hinglish',
    amount_minor: number = 49900,
    link_url: string | null = null,
  ): Promise<{
    language: string;
    text: string;
    amount_minor: number;
    link_url: string | null;
    sample_rate: number;
    duration_seconds: number;
    pcm_payload_b64: string;
    is_stub: boolean;
    reason: string;
  }> {
    const params = new URLSearchParams({
      language,
      amount_minor: String(amount_minor),
    });
    if (link_url) {
      params.set('link_url', link_url);
    }
    return jsonFetch(`/api/voice/preview?${params.toString()}`);
  },

  // --- Checkout drop-off recovery ---

  async getCheckoutSessions(limit: number = 50): Promise<any[]> {
    return jsonFetch(`/api/checkout/sessions?limit=${limit}`);
  },
  async getCheckoutFunnel(): Promise<{ counts: Record<string, number> }> {
    return jsonFetch('/api/checkout/funnel');
  },
  async abandonCheckout(body: { customer_id: string; amount_minor: number; currency?: string }): Promise<any> {
    return postJson('/api/checkout/abandon', body);
  },
  async recoverCheckout(id: string, body: { payment_id: string }): Promise<any> {
    return postJson(`/api/checkout/recover/${encodeURIComponent(id)}`, body);
  },
  async tickCheckout(): Promise<any> {
    return postJson('/api/checkout/tick', {});
  },

  // --- B2B receivables chaser ---

  async getB2BInvoices(status: string | null = null, limit: number = 50): Promise<any[]> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (status) params.set('status', status);
    return jsonFetch(`/api/b2b/invoices?${params.toString()}`);
  },
  async getB2BFunnel(): Promise<{ counts: Record<string, number> }> {
    return jsonFetch('/api/b2b/funnel');
  },
  async createB2BInvoice(body: any): Promise<any> {
    return postJson('/api/b2b/invoice/create', body);
  },
  async chaseB2BInvoice(id: string): Promise<any> {
    return postJson(`/api/b2b/invoice/${encodeURIComponent(id)}/chase`, {});
  },
  async tickB2B(): Promise<any> {
    return postJson('/api/b2b/tick', {});
  },

  // --- Mandate retry sequencer ---

  async getMandateSequenced(limit: number = 25): Promise<any[]> {
    return jsonFetch(`/api/mandate/sequenced?limit=${limit}`);
  },
  async getMandateSequencedSummary(): Promise<{ counts: Record<string, number>; total: number }> {
    return jsonFetch('/api/mandate/sequenced/summary');
  },
  async mandateFailed(body: {
    subscription_id: string;
    customer_id: string;
    mandate_id: string;
    cause: string;
    mandate_status?: string;
    paused_at?: string;
    recent_failures?: Array<{ cause: string; occurred_at: string }>;
  }): Promise<any> {
    return postJson('/api/mandate/failed', body);
  },

  async getLlmSpend(): Promise<LlmSpend> {
    return jsonFetch<LlmSpend>('/api/llm-spend');
  },

  async getGuardianStats(): Promise<GuardianStats> {
    return jsonFetch<GuardianStats>('/api/guardian-stats');
  },

  async getEvalSummary(): Promise<EvalSummary> {
    return jsonFetch<EvalSummary>('/api/eval-summary');
  },

  async getAgentCompare(n: number = 100, seed: number = 42, seeds?: number[]): Promise<AgentCompare> {
    const params = new URLSearchParams({ n: String(n), seed: String(seed) });
    if (seeds && seeds.length > 0) params.set('seeds', seeds.join(','));
    return jsonFetch<AgentCompare>(`/api/eval/agent-compare?${params.toString()}`);
  },

  /** Cadence's local created-link idle scan; this is not Magic Checkout data. */
  async scanCheckoutIdle(idleMinutes?: number): Promise<CheckoutIdleScan> {
    const qs = idleMinutes === undefined ? '' : `?idle_minutes=${encodeURIComponent(String(idleMinutes))}`;
    return postJson<CheckoutIdleScan>(`/api/checkout-idle/scan${qs}`, {});
  },

  /** Feeds free text through the real ptp_parser/dispatcher path. No Resend
   *  inbound webhook is wired (no verified domain with Inbound enabled), so
   *  this is a Cadence-only simulated entry point, not a live inbound email. */
  async simulateCustomerReply(payload: { reference_id: string; text: string }): Promise<SimulateCustomerReplyResult> {
    return postJson<SimulateCustomerReplyResult>('/api/promises/simulate-reply', payload);
  },

  async getPromises(limit: number = 100): Promise<PromiseList> {
    return jsonFetch<PromiseList>(`/api/promises?limit=${limit}`);
  },

  async getPreDebitHistory(limit: number = 100): Promise<PreDebitHistory> {
    return jsonFetch<PreDebitHistory>(`/api/predebit/history?limit=${limit}`);
  },

  async runChaosDrill(drill: string): Promise<ChaosResult> {
    return postJson<ChaosResult>(`/api/chaos/${encodeURIComponent(drill)}/run`, {});
  },

  async getKillSwitch(): Promise<boolean> {
    const data = await jsonFetch<KillSwitchStatus>('/api/flags/kill-switch');
    return data.kill_switch;
  },

  async setKillSwitch(enabled: boolean): Promise<boolean> {
    const data = await postJson<KillSwitchStatus>('/api/flags/kill-switch', { enabled });
    return data.kill_switch;
  },

  /** Real injection. Backend signs the webhook with the configured secret. */
  async injectFailure(payload: InjectRequest): Promise<InjectResponse> {
    return postJson<InjectResponse>('/api/test/inject', payload);
  },

  /** Preventive pre-debit nudge: fire a proactive notice BEFORE a scheduled
   *  debit (the RBI 24h pre-debit notice). Test-safe — appends audit events
   *  only, never touches Razorpay. Distinct from injectFailure (reactive). */
  async schedulePreDebitNudge(payload: {
    subscription_id: string;
    customer_id: string;
    amount_minor: number;
    debit_at: string;
    currency?: string;
    channel?: string;
  }): Promise<{
    subscription_id: string;
    notified: boolean;
    reason: string;
    channel: string;
    debit_at: string;
    scheduled_event: boolean;
    notified_event: boolean;
    ref: string | null;
  }> {
    return postJson('/api/predebit/schedule', payload);
  },

  async createPayLink(journeyId: string): Promise<PayLink> {
    return postJson<PayLink>(
      `/api/pay/${encodeURIComponent(journeyId)}/link`,
      {},
    );
  },

  /** DEMO-only: synthesize a customer payment, close the journey RECOVERED.
   *  Returns 410 in LIVE mode. */
  async simulatePaid(journeyId: string, note?: string): Promise<{
    simulated: boolean;
    journey_id: string;
    state_after: string;
    note: string | null;
  }> {
    return postJson(`/api/pay/${encodeURIComponent(journeyId)}/simulate-paid`, {
      note: note ?? null,
    });
  },

  async getJourneyReasoning(journeyId: string): Promise<AgentReasoning> {
    return jsonFetch<AgentReasoning>(`/api/journey/${encodeURIComponent(journeyId)}/reasoning`);
  },
};
