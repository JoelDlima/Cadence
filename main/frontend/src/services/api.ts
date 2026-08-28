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
  InjectRequest,
  InjectResponse,
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

  async getLlmSpend(): Promise<LlmSpend> {
    return jsonFetch<LlmSpend>('/api/llm-spend');
  },

  async getGuardianStats(): Promise<GuardianStats> {
    return jsonFetch<GuardianStats>('/api/guardian-stats');
  },

  async getEvalSummary(): Promise<EvalSummary> {
    return jsonFetch<EvalSummary>('/api/eval-summary');
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
};
