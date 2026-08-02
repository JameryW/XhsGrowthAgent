<!-- frontend/src/components/ConnectionStatus.vue -->
<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { useRealtimeStore } from "@/stores/realtime"
import AppIcon from "@/components/AppIcon.vue"

const { t } = useI18n()
const realtimeStore = useRealtimeStore()

const statusStyles = computed(() => ({
  connected: {
    icon: "Wifi",
    iconVariant: "cyan" as const,
    animate: false,
    text: t('connection.connected'),
    borderClass: "border-neon-cyan/20",
    bgClass: "bg-white dark:bg-slate-900",
    textClass: "text-neon-cyan",
  },
  connecting: {
    icon: "Loader2",
    iconVariant: "peach" as const,
    animate: true,
    text: t('connection.connecting'),
    borderClass: "border-neon-peach/20",
    bgClass: "bg-white dark:bg-slate-900",
    textClass: "text-neon-peach",
  },
  reconnecting: {
    icon: "Loader2",
    iconVariant: "peach" as const,
    animate: true,
    text: t('connection.reconnecting'),
    borderClass: "border-neon-peach/20",
    bgClass: "bg-white dark:bg-slate-900",
    textClass: "text-neon-peach",
  },
  disconnected: {
    icon: "WifiOff",
    iconVariant: "pink" as const,
    animate: false,
    text: t('connection.disconnected'),
    borderClass: "border-neon-pink/20",
    bgClass: "bg-white dark:bg-slate-900",
    textClass: "text-neon-pink",
  },
}))

const currentStyle = computed(() => statusStyles.value[realtimeStore.connectionStatus])

const canReconnect = computed(() => realtimeStore.connectionStatus === 'disconnected')

</script>

<template>
  <div
    v-if="canReconnect || realtimeStore.connectionStatus === 'connecting' || realtimeStore.connectionStatus === 'reconnecting'"
    class="dark-explicit fixed top-4 right-4 z-modal px-4 py-2.5 rounded-xl flex items-center gap-3 backdrop-blur-sm bg-white/90 border border-slate-200/50 shadow-sm transition-all duration-200 dark:bg-slate-900/90 dark:border-slate-600/50"
    :class="[currentStyle.borderClass]"
    role="status"
    aria-live="polite"
    :aria-label="currentStyle.text"
  >
    <div class="dark-explicit w-6 h-6 rounded-lg flex items-center justify-center bg-slate-50 dark:bg-slate-800" aria-hidden="true">
      <AppIcon
        :name="currentStyle.icon"
        size="sm"
        :variant="currentStyle.iconVariant"
        :animate="currentStyle.animate"
      />
    </div>

    <span :class="currentStyle.textClass" class="text-xs font-medium">{{ currentStyle.text }}</span>

    <!-- DB-09: manual reconnect entry when auto-reconnect exhausted -->
    <button
      v-if="canReconnect"
      type="button"
      class="ml-1 px-2.5 py-1 rounded-lg text-xs font-medium bg-slate-900 text-white hover:bg-slate-700 active:scale-95 transition min-w-[44px] min-h-11 flex items-center justify-center"
      @click="realtimeStore.reconnect()"
    >
      {{ t('connection.reconnect') }}
    </button>

  </div>
</template>
