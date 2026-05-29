<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import { useOfflineStore } from '@/stores'

const { t } = useI18n()

const offlineStore = useOfflineStore()

const isOffline = computed(() => !offlineStore.isOnline)
const pendingCount = computed(() => offlineStore.pendingActionCount)
</script>

<template>
  <Transition name="offline-indicator">
    <div
      v-if="isOffline"
      class="fixed top-0 left-0 right-0 z-40 px-4 py-2 bg-gradient-to-r from-rose-500 to-rose-400 text-white text-sm flex items-center justify-center gap-2 shadow-md"
      role="status"
      aria-live="assertive"
      :aria-label="t('offlineIndicator.networkOffline')"
    >
      <AppIcon name="Wifi" size="sm" variant="white" animate aria-hidden="true" />
      <span class="font-medium">{{ t('offlineIndicator.networkOffline') }}</span>
      <span v-if="pendingCount > 0" class="opacity-80">
        · {{ t('offlineIndicator.pendingActions', { count: pendingCount }) }}
      </span>
    </div>
  </Transition>
</template>

<style scoped>
.offline-indicator-enter-active {
  transition: all 0.3s ease-out;
}

.offline-indicator-leave-active {
  transition: all 0.3s ease-in;
}

.offline-indicator-enter-from {
  transform: translateY(-100%);
  opacity: 0;
}

.offline-indicator-leave-to {
  transform: translateY(-100%);
  opacity: 0;
}
</style>