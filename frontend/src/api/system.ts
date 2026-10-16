import client from './client'

export interface CdpSessionRow {
  key: string
  holder: string
  held_since?: string | null
  held_for_seconds?: number | null
}

export interface ActiveCooldownEntry {
  kind: string
  key: string
  owner?: string
  reason?: string
  retry_after_seconds: number
  message?: string
}

export interface RiskGatesSnapshot {
  browser_action_cooldown_seconds?: number
  publish_cooldown_seconds?: number
  engagement_account_cooldown_seconds?: number
  active_browser_cooldowns?: number
  active_sync_auth_blocks?: number
  active_qr_risk_blocks?: number
  durable?: boolean
  browser_action_keys?: number
  publish_keys?: number
  engagement_keys?: number
  active?: ActiveCooldownEntry[]
  active_count?: number
  max_retry_after_seconds?: number
}

export interface HealthCheck {
  status: 'ok' | 'degraded' | 'error'
  checks: {
    llm_providers: {
      status: string
      message: string
      providers: Record<string, { status: string; configured: boolean; preview: string | null }>
    }
    ripple_cas: {
      status: string
      configured: boolean
      message: string
      reason?: string  // "disabled" | "unconfigured" | "ok"
    }
    database: {
      status: string
      mode: string
      message: string
    }
    memory_store: {
      status: string
      backend: string
      semantic_index: boolean
      message: string
      embed_model?: string
      embed_dims?: number
      namespace_counts?: Record<string, number>
      total_items?: number
    }
    creator_stats_scheduler?: {
      status: string
      message?: string
      interval_hours?: number
      next_run_at?: string
      last_finished_at?: string
      run_count?: number
    }
    risk_control?: {
      status: string
      message?: string
      cdp_sessions?: CdpSessionRow[]
      risk_gates?: RiskGatesSnapshot
      active?: ActiveCooldownEntry[]
      active_count?: number
      max_retry_after_seconds?: number
      active_browser_cooldowns?: number
      active_sync_auth_blocks?: number
      durable?: boolean
    }
  }
  version: string
  timestamp: string
  active_account?: { id: string; name: string }
}

export interface EngagementPauseStatus {
  account_id?: string | null
  paused: boolean
  reason?: string | null
  retry_after_seconds?: number
  pause_until?: string | null
  message?: string
}

/** P1-1: account health panel from GET /system/risk-gates?account_id=… */
export interface AccountHealthSafeMode {
  env_enabled: boolean
  min_risk_pressure: number
  active: boolean
  list_only: boolean
}

export interface AccountHealth {
  account_id?: string | null
  policy?: CooldownPolicy
  last_risk_hit?: { at?: string | null; reason?: string | null; kind?: string | null } | null
  remaining_ban_seconds?: number
  current_ban?: {
    kind?: string
    reason?: string
    retry_after_seconds?: number
    message?: string
  } | null
  safe_mode?: AccountHealthSafeMode
  engagement_pause?: EngagementPauseStatus
  active?: ActiveCooldownEntry[]
}

export interface RiskGatesResponse {
  risk_gates: RiskGatesSnapshot
  active: ActiveCooldownEntry[]
  cdp_sessions: CdpSessionRow[]
  account_id?: string | null
  /** Effective cool-down policy when account_id is set. */
  policy?: CooldownPolicy
  /** P0-3: Settings-visible engagement risk pause (reason + remaining). */
  engagement_pause?: EngagementPauseStatus
  /** P1-1: full health snapshot (policy / last hit / ban / SAFE_MODE). */
  account_health?: AccountHealth | null
}

export interface ClearRiskGatesResult {
  account_id?: string | null
  cleared: Record<string, number>
  total: number
  remaining_active: ActiveCooldownEntry[]
}

export async function getRiskGates(accountId?: string): Promise<RiskGatesResponse> {
  const q = accountId ? `?account_id=${encodeURIComponent(accountId)}` : ''
  return client.get(`/system/risk-gates${q}`) as unknown as Promise<RiskGatesResponse>
}

/** P2-2: niche compliance tier for Start / Settings high-risk notices. */
export interface NicheComplianceTier {
  niche: string
  tier: 'high' | 'standard' | string
  is_high_risk: boolean
  lexicon_stricter: boolean
  qualification_hint: string | null
  lexicon_overlay: string | null
  high_risk_niches?: string[]
}

export async function getNicheCompliance(niche: string): Promise<NicheComplianceTier> {
  return client.get('/system/niche-compliance', {
    params: { niche },
  }) as unknown as Promise<NicheComplianceTier>
}

/** P2-3: read-only Acceptance signoff board (docs mirror). */
export interface AcceptanceSignoffGate {
  id: string
  title: string
  task?: string
  owner_role: string
  status: string
  conclusion: string
  signed_by: string
  signed_at: string
  evidence?: string[]
  notes?: string
}

export interface AcceptanceSignoffBoard {
  ok: boolean
  version?: number
  source_doc?: string
  disclaimer: string
  updated_at?: string
  gates: AcceptanceSignoffGate[]
  waiver?: Record<string, unknown> | null
  replaces_human_signoff?: boolean
  error?: string
}

export async function getAcceptanceSignoff(): Promise<AcceptanceSignoffBoard> {
  return client.get('/system/acceptance-signoff') as unknown as Promise<AcceptanceSignoffBoard>
}

export async function clearRiskGates(payload?: {
  account_id?: string
  kinds?: string[]
}): Promise<ClearRiskGatesResult> {
  return client.post('/system/risk-gates/clear', payload || {}) as unknown as Promise<ClearRiskGatesResult>
}

export interface CooldownPolicy {
  account_id?: string | null
  defaults: Record<string, number>
  overrides: Record<string, number>
  effective: Record<string, number>
}

export async function getRiskGatePolicy(accountId?: string): Promise<CooldownPolicy> {
  const q = accountId ? `?account_id=${encodeURIComponent(accountId)}` : ''
  return client.get(`/system/risk-gates/policy${q}`) as unknown as Promise<CooldownPolicy>
}

export async function setRiskGatePolicy(payload: {
  account_id: string
  browser_action_seconds?: number | null
  publish_seconds?: number | null
  engagement_seconds?: number | null
  sync_auth_minutes?: number | null
  qr_cooldown_seconds?: number | null
  qr_risk_block_seconds?: number | null
  min_risk_pressure?: number | null
  replace?: boolean
}): Promise<CooldownPolicy> {
  return client.put('/system/risk-gates/policy', payload) as unknown as Promise<CooldownPolicy>
}

export async function deleteRiskGatePolicy(accountId?: string): Promise<{
  account_id?: string | null
  removed: number
  policy: CooldownPolicy
}> {
  const q = accountId ? `?account_id=${encodeURIComponent(accountId)}` : ''
  return client.delete(`/system/risk-gates/policy${q}`) as unknown as Promise<{
    account_id?: string | null
    removed: number
    policy: CooldownPolicy
  }>
}

/** Client-side cache so PreLaunchChecklist remounts don't re-hit the API. */
const HEALTH_CACHE_TTL_MS = 30_000
let healthCache: { data: HealthCheck; at: number } | null = null
let healthInFlight: Promise<HealthCheck> | null = null

export function clearSystemHealthCache(): void {
  healthCache = null
  healthInFlight = null
}

export async function getSystemHealth(options?: { fresh?: boolean }): Promise<HealthCheck> {
  const fresh = options?.fresh === true
  const now = Date.now()
  if (
    !fresh
    && healthCache
    && now - healthCache.at < HEALTH_CACHE_TTL_MS
  ) {
    return healthCache.data
  }
  if (!fresh && healthInFlight) {
    return healthInFlight
  }

  const path = fresh ? '/system/health?fresh=1' : '/system/health'
  healthInFlight = (client.get(path) as unknown as Promise<HealthCheck>)
    .then((data) => {
      healthCache = { data, at: Date.now() }
      return data
    })
    .finally(() => {
      healthInFlight = null
    })

  return healthInFlight
}
