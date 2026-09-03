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
  cadence_recovered_inr: number;
  cadence_recovery_pct: number;
  uplift_pct: number;
  contacts_naive: number;
  contacts_recovery_naive: number;
  contacts_recovery_cadence: number;
  fast_path_pct: number;
  source: 'live' | 'cached' | 'missing';
}

export interface AgentComparePerSeed {
  seed: number;
  n: number;
  naive_recovery_pct: number;
  cadence_recovery_pct: number;
  naive_recovered_inr: number;
  cadence_recovered_inr: number;
  naive_contacts: number;
  cadence_contacts: number;
}

export interface AgentCompare {
  n: number;
  seed: number;
  seeds: number[];
  naive_recovered_inr: number;
  naive_recovery_pct: number;
  naive_contacts: number;
  naive_attempts: number;
  cadence_recovered_inr: number;
  cadence_recovery_pct: number;
  cadence_contacts: number;
  cadence_attempts: number;
  uplift_pct: number;
  recovered_delta: number;
  fast_path_pct: number;
  cohort: string;
  runtime_ms: number;
  source: 'live_experiment';
  mean_naive_recovery_pct: number;
  mean_cadence_recovery_pct: number;
  mean_uplift_pct: number;
  mean_recovered_delta_inr: number;
  per_seed: AgentComparePerSeed[];
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
  delivery_count?: number;
}

export interface InjectResponse {
  http_status: number;
  body: Record<string, any>;
  signature_prefix: string;
  delivery_statuses: string[];
  journey_id?: string | null;
  journey_state?: string | null;
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


export interface ReasoningStep {
  step: number;
  role: "observation" | "decision" | "action" | "agent_thinking";
  title: string;
  detail: string;
  event_refs: { seq: number; type: string; ts: string }[];
  timestamp?: string;
  source?: string;
  channel?: string;
}

export interface AgentReasoning {
  journey_id: string;
  steps: ReasoningStep[];
  has_llm_thought: boolean;
}

export interface MerchantSummary {
  total_journeys: number;
  total_recovered: number;
  total_lost: number;
  recovery_rate_pct: number;
  recovered_amount_inr: number;
  lost_amount_inr: number;
  avg_time_to_recover_minutes: number;
  top_root_causes: { root_cause: string; count: number; recovered: number; lost: number }[];
  state_distribution: Record<string, number>;
  intervention_performance: { intervention: string; count: number; recovered: number }[];
  generated_at: string;
}

export interface Anomaly {
  cause: string;
  count: number;
  severity: string; // "info" | "warn" | "alert"
  window_minutes: number;
  threshold: number;
  recommendation: string;
}

/** Razorpay Payment Links statuses, mirrored 1:1 so the Dashboard table
 *  reads like the merchant dashboard a judge already knows. */
export type PlinkStatus =
  | 'created'
  | 'partially_paid'
  | 'paid'
  | 'cancelled'
  | 'expired';

export interface PlinkLifecycleEntry {
  at: string;
  to_status: string;
  source: string;
  detail: Record<string, any>;
}

export interface PaymentLinkRow {
  plink_id: string;
  journey_id: string;
  subscription_id?: string | null;
  customer_id?: string | null;
  reference_id: string;
  short_url: string;
  amount_minor: number;
  amount_inr: number;
  currency: string;
  status: PlinkStatus;
  amount_paid_minor: number;
  journey_state?: string | null;
  root_cause?: string | null;
  failure_code?: string | null;
  attempts_used: number;
  touches_used: number;
  simulated: boolean;
  created_at: string;
  updated_at: string;
  lifecycle: PlinkLifecycleEntry[];
}

export interface DashboardStats {
  recovered_inr: number;
  lost_inr: number;
  at_risk_inr: number;
  open_count: number;
  recovered_count: number;
  lost_count: number;
  recovered_since: number;
  recovered_inr_since: number;
  mean_time_to_recover_min: number;
  plink_count: number;
  plink_paid_count: number;
  recovery_rate_pct: number;
  since: string;
  generated_at: string;
}

export interface CloudPlinks {
  enabled: boolean;
  count: number;
  rows: Record<string, any>[];
  mirror: Record<string, any>;
  table_url: string | null;
}