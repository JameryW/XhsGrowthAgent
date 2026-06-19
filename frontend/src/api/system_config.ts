import client from './client'

// ── Types ──

export interface SystemConfigItem {
  key_name: string
  masked_value: string
  is_set: boolean
  updated_at: string
}

export interface SystemConfigGroup {
  id: string
  keys: string[]
}

export interface SystemConfigPayload {
  items: SystemConfigItem[]
  groups: SystemConfigGroup[]
}

// ── Read / write ──

export async function getSystemConfig(): Promise<SystemConfigPayload> {
  return client.get('/system-config') as unknown as SystemConfigPayload
}

export async function setSystemConfig(config: Record<string, string>): Promise<{ updated_keys: string[] }> {
  return client.put('/system-config', { config }) as unknown as { updated_keys: string[] }
}
