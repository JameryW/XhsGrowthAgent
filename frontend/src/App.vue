<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue"
import ConnectionStatus from "@/components/ConnectionStatus.vue"
import Toast from "@/components/Toast.vue"
import OfflineIndicator from "@/components/OfflineIndicator.vue"
import KeyboardShortcutsHelp from "@/components/KeyboardShortcutsHelp.vue"
import Navbar from "@/components/Navbar.vue"
import { useRealtimeStore, useOfflineStore } from "@/stores"

const realtimeStore = useRealtimeStore()
const offlineStore = useOfflineStore()

// Keyboard shortcuts help
const showShortcutsHelp = ref(false)

const handleGlobalKeyDown = (e: KeyboardEvent) => {
  // Show shortcuts help with "?" key (Shift+/)
  if (e.key === "?" || (e.shiftKey && e.key === "/")) {
    showShortcutsHelp.value = true
  }
}

onMounted(() => {
  // 应用启动时建立WebSocket连接
  realtimeStore.connect()
  // Add global keyboard listener
  window.addEventListener("keydown", handleGlobalKeyDown)
})

onUnmounted(() => {
  // 应用卸载时断开WebSocket
  realtimeStore.disconnect()
  // Remove keyboard listener
  window.removeEventListener("keydown", handleGlobalKeyDown)
})

const handleCloseShortcutsHelp = () => {
  showShortcutsHelp.value = false
}
</script>

<template>
  <div class="min-h-screen bg-gradient-to-br from-slate-50 via-white to-slate-100/80 flex relative overflow-hidden">
    <!-- Animated gradient mesh -->
    <div class="absolute inset-0 pointer-events-none overflow-hidden">
      <div class="absolute -top-40 -right-40 w-[500px] h-[500px] rounded-full opacity-70 animate-pulse" style="background: radial-gradient(circle, rgba(244,63,94,0.15) 0%, transparent 50%); animation-duration: 4s;" />
      <div class="absolute -bottom-40 -left-40 w-[400px] h-[400px] rounded-full opacity-60 animate-pulse" style="background: radial-gradient(circle, rgba(20,184,166,0.12) 0%, transparent 50%); animation-duration: 5s; animation-delay: 1s;" />
      <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[300px] h-[300px] rounded-full opacity-40 animate-pulse" style="background: radial-gradient(circle, rgba(139,92,246,0.1) 0%, transparent 50%); animation-duration: 6s; animation-delay: 2s;" />
    </div>

    <!-- Subtle grid -->
    <div class="absolute inset-0 pointer-events-none" style="background-image: linear-gradient(rgba(0,0,0,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,0,0.02) 1px, transparent 1px); background-size: 40px 40px;" />

    <!-- Status indicators -->
    <OfflineIndicator />
    <ConnectionStatus />
    <Toast />

    <!-- Keyboard shortcuts help -->
    <KeyboardShortcutsHelp :is-open="showShortcutsHelp" @close="handleCloseShortcutsHelp" />

    <!-- 左侧导航 -->
    <Navbar />

    <!-- 主内容区 -->
    <main class="flex-1 p-8 overflow-auto relative z-10">
      <router-view v-slot="{ Component }">
        <transition name="page-transition" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.page-transition-enter-active {
  transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}
.page-transition-leave-active {
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
.page-transition-enter-from {
  opacity: 0;
  transform: translateY(12px);
}
.page-transition-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>

<style scoped>
.slide-fade-enter-active {
  transition: all 0.4s ease-out;
}

.slide-fade-leave-active {
  transition: all 0.3s ease-in;
}

.slide-fade-enter-from {
  transform: translateY(20px);
  opacity: 0;
}

.slide-fade-leave-to {
  transform: translateY(-10px);
  opacity: 0;
}
</style>