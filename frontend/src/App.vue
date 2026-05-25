<script setup lang="ts">
import { onMounted, onUnmounted } from "vue"
import ConnectionStatus from "@/components/ConnectionStatus.vue"
import Toast from "@/components/Toast.vue"
import Navbar from "@/components/Navbar.vue"
import { useRealtimeStore } from "@/stores/realtime"

const realtimeStore = useRealtimeStore()

onMounted(() => {
  // 应用启动时建立WebSocket连接
  realtimeStore.connect()
})

onUnmounted(() => {
  // 应用卸载时断开WebSocket
  realtimeStore.disconnect()
})
</script>

<template>
  <div class="min-h-screen bg-dark-bg flex">
    <!-- Status indicators -->
    <ConnectionStatus />
    <Toast />

    <!-- 左侧导航 -->
    <Navbar />

    <!-- 主内容区 -->
    <main class="flex-1 p-6 overflow-auto">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>