<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import { useToastStore } from '@/stores'

const { t } = useI18n()

interface Props {
  /** Optional controlled connectivity state for shells and deterministic tests. */
  isOnline?: boolean
}

const props = defineProps<Props>()

// Emits
const emit = defineEmits<{
  online: []
  offline: []
}>()

// Stores
const toastStore = useToastStore()

// Internal state - initialized from navigator.onLine after browser is ready when
// the component is uncontrolled. A supplied prop takes precedence immediately.
const internalIsOnline = ref(props.isOnline ?? true)
const wasOffline = ref(false)
const initialized = ref(props.isOnline !== undefined)
// ponytail: cancel the deferred onLine probe so a rAF scheduled before
// unmount can't fire after the test env (happy-dom) tears down — that reads
// navigator in a bare Node global and crashes the process with exit 1.
let rafHandle: number | null = null

const isOffline = computed(() => !(props.isOnline ?? internalIsOnline.value))

watch(
  () => props.isOnline,
  (nextOnline, previousOnline) => {
    if (nextOnline === undefined) {
      // Preserve the last internal value when switching back to browser events.
      initialized.value = true
      return
    }

    internalIsOnline.value = nextOnline
    initialized.value = true
    if (!nextOnline) {
      wasOffline.value = true
    } else if (previousOnline === false) {
      wasOffline.value = false
    }
  },
)

// Handle online/offline events
const handleOnline = () => {
  internalIsOnline.value = true
  initialized.value = true
  emit('online')

  if (wasOffline.value) {
    toastStore.success(t('offline.recovered'), t('offline.recoveredMessage'))
    wasOffline.value = false
  }
}

const handleOffline = () => {
  internalIsOnline.value = false
  initialized.value = true
  wasOffline.value = true
  emit('offline')
  toastStore.warning(t('offline.lost'), t('offline.lostMessage'))
}

// Lifecycle
onMounted(() => {
  // Register event listeners
  window.addEventListener('online', handleOnline)
  window.addEventListener('offline', handleOffline)

  // Initialize state from navigator.onLine immediately after mount when no
  // controlled prop was supplied. Use requestAnimationFrame so the first
  // browser paint is not blocked by a connectivity probe.
  if (props.isOnline === undefined) {
    rafHandle = requestAnimationFrame(() => {
      rafHandle = null
      // A parent may have supplied a prop while the frame was pending, or the
      // component may have unmounted; guard navigator for the bare-Node case.
      if (props.isOnline !== undefined || typeof navigator === 'undefined') return
      const currentOnlineStatus = navigator.onLine
      internalIsOnline.value = currentOnlineStatus
      initialized.value = true

      if (!currentOnlineStatus) {
        wasOffline.value = true
      }
    })
  }
})

onUnmounted(() => {
  window.removeEventListener('online', handleOnline)
  window.removeEventListener('offline', handleOffline)
  if (rafHandle !== null) {
    cancelAnimationFrame(rafHandle)
    rafHandle = null
  }
})
</script>

<template>
  <Transition name="offline-recovery">
    <!-- Only show offline warning after initialization AND when truly offline -->
    <div
      v-if="initialized && isOffline"
      class="fixed top-0 left-0 right-0 z-modal px-4 py-3 bg-gradient-to-r from-amber-500 to-amber-400 text-white shadow-lg"
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
