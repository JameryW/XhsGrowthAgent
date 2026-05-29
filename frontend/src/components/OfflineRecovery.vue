<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import { useToastStore } from '@/stores'

const { t } = useI18n()

// Emits
const emit = defineEmits<{
  online: []
  offline: []
}>()

// Stores
const toastStore = useToastStore()

// Internal state - initialized from navigator.onLine after browser is ready
const internalIsOnline = ref(true) // Start with true to prevent false warning on initial render
const wasOffline = ref(false)
const initialized = ref(false)

const isOffline = computed(() => !internalIsOnline.value)

// Handle online/offline events
const handleOnline = () => {
  internalIsOnline.value = true
  emit('online')

  if (wasOffline.value) {
    toastStore.success(t('offline.recovered'), t('offline.recoveredMessage'))
    wasOffline.value = false
  }
}

const handleOffline = () => {
  internalIsOnline.value = false
  wasOffline.value = true
  emit('offline')
  toastStore.warning(t('offline.lost'), t('offline.lostMessage'))
}

// Lifecycle
onMounted(() => {
  // Register event listeners
  window.addEventListener('online', handleOnline)
  window.addEventListener('offline', handleOffline)

  // Initialize state from navigator.onLine immediately after mount
  // Use requestAnimationFrame to ensure DOM is ready
  requestAnimationFrame(() => {
    const currentOnlineStatus = navigator.onLine
    internalIsOnline.value = currentOnlineStatus
    initialized.value = true

    if (!currentOnlineStatus) {
      wasOffline.value = true
    }
  })
})

onUnmounted(() => {
  window.removeEventListener('online', handleOnline)
  window.removeEventListener('offline', handleOffline)
})
</script>

<template>
  <Transition name="offline-recovery">
    <!-- Only show offline warning after initialization AND when truly offline -->
    <div
      v-if="initialized && isOffline"
      class="fixed top-0 left-0 right-0 z-50 px-4 py-3 bg-gradient-to-r from-amber-500 to-amber-400 text-white shadow-lg"
      role="status"
      aria-live="assertive"
      :aria-label="t('offline.warning')"
    >
      <div class="flex items-center justify-center gap-3">
        <AppIcon name="WifiOff" size="md" variant="white" />
        <span class="font-medium">{{ t('offline.networkDisconnected') }}</span>
        <span class="text-sm opacity-80">{{ t('offline.checkNetwork') }}</span>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.offline-recovery-enter-active {
  transition: all 0.3s ease-out;
}

.offline-recovery-leave-active {
  transition: all 0.3s ease-in;
}

.offline-recovery-enter-from {
  transform: translateY(-100%);
  opacity: 0;
}

.offline-recovery-leave-to {
  transform: translateY(-100%);
  opacity: 0;
}
</style>