import { defineStore } from 'pinia'
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useToastStore } from './toast'

export const useOfflineStore = defineStore('offline', () => {
  const toastStore = useToastStore()

  // State - default to true (online) to avoid false warnings during browser initialization
  // (Playwright and some browsers may report offline during initialization)
  // We rely on actual offline events to update state, not the initial navigator.onLine value
  const isOnline = ref(true)
  const wasOffline = ref(false)
  const actionQueue = ref<Array<{ id: string; action: () => Promise<void>; description: string }>>([])

  // Computed
  const hasPendingActions = computed(() => actionQueue.value.length > 0)
  const pendingActionCount = computed(() => actionQueue.value.length)

  // Action queue operations
  function queueAction(id: string, action: () => Promise<void>, description: string) {
    const existingIndex = actionQueue.value.findIndex(a => a.id === id)
    if (existingIndex === -1) {
      actionQueue.value.push({ id, action, description })
      toastStore.warning('离线状态', `${description} 已加入队列，连接恢复后自动执行`)
    }
  }

  function removeAction(id: string) {
    actionQueue.value = actionQueue.value.filter(a => a.id !== id)
  }

  async function executeQueue() {
    if (actionQueue.value.length === 0) return

    toastStore.info('恢复连接', `正在执行 ${actionQueue.value.length} 个待处理操作...`)

    const actions = [...actionQueue.value]
    actionQueue.value = []

    for (const { action, description } of actions) {
      try {
        await action()
        toastStore.success('操作完成', description)
      } catch (e) {
        toastStore.error('操作失败', `${description} 执行失败`)
      }
    }
  }

  // Online/offline event handlers
  function handleOnline() {
    isOnline.value = true
    if (wasOffline.value) {
      toastStore.success('连接恢复', '网络已恢复')
      executeQueue()
    }
    wasOffline.value = false
  }

  function handleOffline() {
    isOnline.value = false
    wasOffline.value = true
    toastStore.warning('离线状态', '网络连接丢失，操作将自动排队')
  }

  // Lifecycle hooks
  onMounted(() => {
    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    // Delayed check to handle browser initialization timing issues
    // Some browsers may report offline during initialization but become online shortly after
    setTimeout(() => {
      const currentOnlineStatus = navigator.onLine ?? true
      if (currentOnlineStatus !== isOnline.value) {
        isOnline.value = currentOnlineStatus
        if (currentOnlineStatus) {
          wasOffline.value = false
        }
      }
    }, 100)
  })

  onUnmounted(() => {
    window.removeEventListener('online', handleOnline)
    window.removeEventListener('offline', handleOffline)
  })

  return {
    isOnline,
    wasOffline,
    actionQueue,
    hasPendingActions,
    pendingActionCount,
    queueAction,
    removeAction,
    executeQueue,
  }
})