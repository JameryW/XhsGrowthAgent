import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  getSystemConfig,
  setSystemConfig,
  type SystemConfigItem,
  type SystemConfigGroup,
} from '@/api/system_config'

export const useSystemConfigStore = defineStore('system-config', () => {
  const items = ref<SystemConfigItem[]>([])
  const groups = ref<SystemConfigGroup[]>([])
  const isLoading = ref(false)

  async function fetchConfig() {
    isLoading.value = true
    try {
      const payload = await getSystemConfig()
      items.value = payload.items
      groups.value = payload.groups
    } finally {
      isLoading.value = false
    }
  }

  async function saveConfig(updates: Record<string, string>) {
    await setSystemConfig(updates)
    // Re-fetch to refresh masked values
    await fetchConfig()
  }

  function getItem(keyName: string): SystemConfigItem | undefined {
    return items.value.find(i => i.key_name === keyName)
  }

  return { items, groups, isLoading, fetchConfig, saveConfig, getItem }
})
