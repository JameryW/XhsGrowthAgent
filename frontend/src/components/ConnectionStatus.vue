<!-- frontend/src/components/ConnectionStatus.vue -->
<script setup lang="ts">
import { computed } from "vue"
import { useRealtimeStore } from "@/stores/realtime"

const realtimeStore = useRealtimeStore()

const statusConfig = {
  connected: {
    icon: "🟢",
    text: "实时连接",
    color: "neon-cyan",
  },
  connecting: {
    icon: "🟡",
    text: "连接中...",
    color: "neon-peach",
  },
  reconnecting: {
    icon: "🟡",
    text: "重连中...",
    color: "neon-peach",
  },
  disconnected: {
    icon: "🔴",
    text: "已断开",
    color: "neon-pink",
  },
} as const

const currentConfig = computed(() => statusConfig[realtimeStore.connectionStatus])
</script>

<template>
  <div
    class="fixed top-4 right-4 z-50 px-3 py-1.5 rounded-lg mono text-xs flex items-center gap-2 bg-black/80 border shadow-lg transition-colors"
    :class="[
      `border-${currentConfig.color}/50`,
      `text-${currentConfig.color}`,
    ]"
  >
    <span
      v-if="realtimeStore.connectionStatus === 'connecting' || realtimeStore.connectionStatus === 'reconnecting'"
      class="animate-pulse"
    >
      {{ currentConfig.icon }}
    </span>
    <span v-else>{{ currentConfig.icon }}</span>

    <span>{{ currentConfig.text }}</span>

    <span
      v-if="realtimeStore.connectionStatus === 'connected'"
      class="text-white/30"
    >
      · seq: {{ realtimeStore.getLastSeq() }}
    </span>
  </div>
</template>