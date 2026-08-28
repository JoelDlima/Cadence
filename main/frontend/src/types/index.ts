export type JourneyState =
  | "OPENED"
  | "CLASSIFIED"
  | "INTERVENING"
  | "WAITING_OUTCOME"
  | "RECOVERED"
  | "CLOSED_UNRECOVERED"
  | "HUMAN_REVIEW";

export type RootCause =
  | "NO_FUNDS"
  | "BANK_DOWN"
  | "TIMEOUT"
  | "CUSTOMER_ABORTED"
  | "HARD_DECLINE"
  | "BAD_VPA"
  | "EXPIRED_INSTRUMENT"
  | "UNKNOWN";

export interface Journey {
  journey_id: string;
  subscription_id: string;
  customer_id: string;
  state: JourneyState;
  root_cause?: RootCause | string | null;
  amount_minor?: number | null;
  currency: string;
  attempts_used: number;
  touches_used: number;
  score: number | null;
  opened_at: string;
  updated_at: string;
}

export interface TimelineEvent {
  seq: number;
  occurred_at: string;
  type: string;
  payload: Record<string, any>;
}

export interface Metrics {
  recovered_inr_major: number;
  journeys_by_state: Record<string, number>;
  llm_requests_today: number;
  violations: number;
}

export interface KillSwitchStatus {
  kill_switch: boolean;
}

export interface Status {
  mode: 'DEMO' | 'LIVE';
  razorpay_keys_present: boolean;
  resend_key_present: boolean;
  supabase_keys_present: boolean;
  llm_keys_present: boolean;
  db_event_count: number;
  db_path: string;
}

export interface Attention {
  journey_id: string;
  subscription_id: string;
  customer_id: string;
  amount_minor: number;
  state: string;
  root_cause: string | null;
  reason: 'human_review' | 'high_value' | 'bank_outage';
  updated_at: string;
}

export interface Bank {
  bank_name: string;
  failure_count: number;
  threshold: number;
  is_holding: boolean;
}

export interface AuditVerify {
  chain_ok: boolean;
  event_count: number;
  last_hash: string;
  verified_at: string;
  first_bad_seq: number | null;
}

export interface LlmProviderSpend {
  provider: string;
  requests: number;
  tokens_in: number;
  tokens_out: number;
  cap: number;
}

export interface LlmSpend {
  providers: LlmProviderSpend[];
}

export interface GuardianStats {
  total_vetoes: number;
  by_reason: Record<string, number>;
}

export interface EvalSummary {
  n: number;
  seed: number;
  naive_recovered_inr: number;
  naive_recovery_pct: number;
  revive_recovered_inr: number;
  revive_recovery_pct: number;
  uplift_pct: number;
  contacts_naive: number;
  contacts_recovery_naive: number;
  contacts_recovery_revive: number;
  fast_path_pct: number;
  source: 'live' | 'cached' | 'missing';
}

export interface ChaosResult {
  drill: string;
  passed: boolean;
  detail: string;
}

export interface InjectRequest {
  subscription_id: string;
  customer_id: string;
  failure_code: string;
  error_description?: string | null;
  amount_minor: number;
  currency?: string;
}

export interface InjectResponse {
  http_status: number;
  body: Record<string, any>;
  signature_prefix: string;
}

export interface PayLink {
  short_url: string;
  mode: 'DEMO' | 'LIVE';
  simulated: boolean;
}

export interface CloudStatus {
  enabled: boolean;
  sync_state: 'offline' | 'online' | 'error';
  last_journeys_sync_at: string | null;
  last_metrics_sync_at: string | null;
  last_journeys_pushed: number;
  last_metrics_pushed: number;
  last_journeys_error: string | null;
  last_metrics_error: string | null;
  supabase_url_configured: boolean;
  service_key_configured: boolean;
}

export interface BanditRanking {
  occurred_at: string;
  cause: string;
  top: string;
  ranked: string[];
  scores: Record<string, number>;
  reason: string[];
  feature_importances: Record<string, Record<string, number>>;
}
