<!-- frontend/src/components/ConnectionStatus.vue -->
<script setup lang="ts">
import { computed } from "vue"
import { useRealtimeStore } from "@/stores/realtime"
import AppIcon from "@/components/AppIcon.vue"

const realtimeStore = useRealtimeStore()

const statusStyles: Record<string, {
  icon: string
  iconVariant: 'pink' | 'cyan' | 'purple' | 'peach' | 'white'
  animate?: boolean
  text: string
  borderClass: string
  bgClass: string
  textClass: string
}> = {
  connected: {
    icon: "Wifi",
    iconVariant: "cyan",
    text: "实时连接",
    borderClass: "border-neon-cyan/20",
    bgClass: "bg-white",
    textClass: "text-neon-cyan",
  },
  connecting: {
    icon: "Loader2",
    iconVariant: "peach",
    animate: true,
    text: "连接中...",
    borderClass: "border-neon-peach/20",
    bgClass: "bg-white",
    textClass: "text-neon-peach",
  },
  reconnecting: {
    icon: "Loader2",
    iconVariant: "peach",
    animate: true,
    text: "重连中...",
    borderClass: "border-neon-peach/20",
    bgClass: "bg-white",
    textClass: "text-neon-peach",
  },
  disconnected: {
    icon: "WifiOff",
    iconVariant: "pink",
    text: "已断开",
    borderClass: "border-neon-pink/20",
    bgClass: "bg-white",
    textClass: "text-neon-pink",
  },
}

const currentStyle = computed(() => statusStyles[realtimeStore.connectionStatus])
</script>

<template>
  <div
    class="fixed top-4 right-4 z-50 px-4 py-2.5 rounded-xl flex items-center gap-3 backdrop-blur-sm bg-white/98 border border-slate-200/50 shadow-sm transition-all duration-200"
    :class="[currentStyle.borderClass]"
    role="status"
    aria-live="polite"
    aria-label="实时连接状态: {{ currentStyle.text }}"
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

    <span
      v-if="realtimeStore.connectionStatus === 'connected'"
      class="px-2 py-0.5 rounded bg-teal-50 text-teal-600/80 text-xs font-medium"
      aria-label="消息序列号"
    >
      seq: {{ realtimeStore.getLastSeq() }}
    </span>
  </div>
</template>