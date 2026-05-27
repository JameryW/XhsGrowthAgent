<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import { useToastStore } from '@/stores'

// Props
const props = defineProps<{
  isOnline?: boolean
}>()

// Emits
const emit = defineEmits<{
  online: []
  offline: []
}>()

// Stores
const toastStore = useToastStore()

// Internal state - initialize from navigator.onLine, default to true if undefined
const internalIsOnline = ref(typeof navigator !== 'undefined' ? navigator.onLine ?? true : true)
const wasOffline = ref(false)

// Use prop if provided, otherwise use internal state
const onlineStatus = computed(() => {
  return props.isOnline !== undefined ? props.isOnline : internalIsOnline.value
})

const isOffline = computed(() => !onlineStatus.value)

// Handle online/offline events
const handleOnline = () => {
  internalIsOnline.value = true
  emit('online')

  if (wasOffline.value) {
    toastStore.success('连接恢复', '网络已恢复，可以继续操作')
    wasOffline.value = false
  }
}

const handleOffline = () => {
  internalIsOnline.value = false
  wasOffline.value = true
  emit('offline')
  toastStore.warning('离线状态', '网络连接丢失，部分功能可能不可用')
}

// Watch prop changes
watch(() => props.isOnline, (newValue) => {
  if (newValue !== undefined) {
    if (newValue && wasOffline.value) {
      toastStore.success('连接恢复', '网络已恢复，可以继续操作')
      wasOffline.value = false
    } else if (!newValue) {
      wasOffline.value = true
      toastStore.warning('离线状态', '网络连接丢失，部分功能可能不可用')
    }
  }
})

// Lifecycle
onMounted(() => {
  window.addEventListener('online', handleOnline)
  window.addEventListener('offline', handleOffline)
})

onUnmounted(() => {
  window.removeEventListener('online', handleOnline)
  window.removeEventListener('offline', handleOffline)
})
</script>

<template>
  <Transition name="offline-recovery">
    <!-- Offline warning bar -->
    <div
      v-if="isOffline"
      class="fixed top-0 left-0 right-0 z-50 px-4 py-3 bg-gradient-to-r from-amber-500 to-amber-400 text-white shadow-lg"
      role="status"
      aria-live="assertive"
      aria-label="网络离线警告"
    >
      <div class="flex items-center justify-center gap-3">
        <AppIcon name="WifiOff" size="md" variant="white" />
        <span class="font-medium">网络连接已断开</span>
        <span class="text-sm opacity-80">请检查网络设置</span>
      </div>
    </div>
  </Transition>

  <!-- Reconnection success notification (handled by toast store) -->
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