import client from './client'

export interface HealthCheck {
  status: 'ok' | 'degraded' | 'error'
  checks: {
    llm_providers: {
      status: string
      message: string
      providers: Record<string, { status: string; configured: boolean; preview: string | null }>
    }
    xhs_platform: {
      status: string
      configured: boolean
      cookie_set: boolean
      user_id_set: boolean
      message: string
    }
    ripple_cas: {
      status: string
      configured: boolean
      message: string
    }
    database: {
      status: string
      mode: string
      message: string
    }
  }
  version: string
  timestamp: string
}

export async function getSystemHealth(): Promise<HealthCheck> {
  return client.get('/system/health') as unknown as HealthCheck
}
