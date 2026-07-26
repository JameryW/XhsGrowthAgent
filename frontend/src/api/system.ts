import client from './client'

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
  }
  version: string
  timestamp: string
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
