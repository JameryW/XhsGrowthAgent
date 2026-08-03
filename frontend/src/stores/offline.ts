import { defineStore } from 'pinia'
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useToastStore } from './toast'
import i18n from '@/locales'

const { t } = i18n.global

export const useOfflineStore = defineStore('offline', () => {
  // ponytail: hoisted so onUnmounted can clear it — same navigator-after-teardown
  // flake as OfflineRecovery: a 100ms setTimeout reading navigator.onLine fires
  // after happy-dom tears down in slow CI → ReferenceError → exit 1.
  let initTimer: ReturnType<typeof setTimeout> | null = null
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
      toastStore.warning(t('offline.lost'), `${description}`)
    }
  }

  function removeAction(id: string) {
    actionQueue.value = actionQueue.value.filter(a => a.id !== id)
  }

  async function executeQueue() {
    if (actionQueue.value.length === 0) return

    toastStore.info(t('offline.recovered'), `${actionQueue.value.length}`)

    const actions = [...actionQueue.value]
    actionQueue.value = []

    for (const { action, description } of actions) {
      try {
        await action()
        toastStore.success(t('common.success'), description)
      } catch (e) {
        toastStore.error(t('common.error'), `${description}`)
      }
    }
  }

  // Online/offline event handlers
  function handleOnline() {
    isOnline.value = true
    if (wasOffline.value) {
      toastStore.success(t('offline.recovered'), t('offline.recoveredMessage'))
      executeQueue()
    }
    wasOffline.value = false
  }

  function handleOffline() {
    isOnline.value = false
    wasOffline.value = true
    toastStore.warning(t('offline.lost'), t('offline.lostMessage'))
  }

  // Lifecycle hooks
  onMounted(() => {
    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    // Delayed check to handle browser initialization timing issues
    // Some browsers may report offline during initialization but become online shortly after
    initTimer = setTimeout(() => {
      if (typeof navigator === 'undefined') return
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
    if (initTimer !== null) {
      clearTimeout(initTimer)
      initTimer = null
    }
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