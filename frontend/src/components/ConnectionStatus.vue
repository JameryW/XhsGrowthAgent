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
    bgClass: "bg-white",
    textClass: "text-neon-cyan",
  },
  connecting: {
    icon: "Loader2",
    iconVariant: "peach" as const,
    animate: true,
    text: t('connection.connecting'),
    borderClass: "border-neon-peach/20",
    bgClass: "bg-white",
    textClass: "text-neon-peach",
  },
  reconnecting: {
    icon: "Loader2",
    iconVariant: "peach" as const,
    animate: true,
    text: t('connection.reconnecting'),
    borderClass: "border-neon-peach/20",
    bgClass: "bg-white",
    textClass: "text-neon-peach",
  },
  disconnected: {
    icon: "WifiOff",
    iconVariant: "pink" as const,
    animate: false,
    text: t('connection.disconnected'),
    borderClass: "border-neon-pink/20",
    bgClass: "bg-white",
    textClass: "text-neon-pink",
  },
}))

const currentStyle = computed(() => statusStyles.value[realtimeStore.connectionStatus])

</script>

<template>
  <div
    v-if="realtimeStore.connectionStatus === 'connecting' || realtimeStore.connectionStatus === 'reconnecting'"
    class="fixed top-4 right-4 z-50 px-4 py-2.5 rounded-xl flex items-center gap-3 backdrop-blur-sm bg-white/98 border border-slate-200/50 shadow-sm transition-all duration-200"
    :class="[currentStyle.borderClass]"
    role="status"
    aria-live="polite"
    :aria-label="currentStyle.text"
  >
    <div class="w-6 h-6 rounded-lg flex items-center justify-center bg-slate-50" aria-hidden="true">
      <AppIcon
        :name="currentStyle.icon"
        size="sm"
        :variant="currentStyle.iconVariant"
        :animate="currentStyle.animate"
      />
    </div>

    <span :class="currentStyle.textClass" class="text-xs font-medium">{{ currentStyle.text }}</span>

  </div>
</template>
