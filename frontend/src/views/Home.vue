<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ref } from 'vue'
import NeonButton from '@/components/NeonButton.vue'
import { useWorkflowStore } from '@/stores'

const router = useRouter()
const workflowStore = useWorkflowStore()
const isStarting = ref(false)

const goToDashboard = () => {
  router.push('/dashboard')
}

const startNewWorkflow = async () => {
  isStarting.value = true
  try {
    await workflowStore.startWorkflow('default', 'scouting')
    router.push('/dashboard')
  } finally {
    isStarting.value = false
  }
}
</script>

<template>
  <div class="min-h-[80vh] flex flex-col items-center justify-center">
    <!-- 主卡片 -->
    <div class="glass rounded-2xl p-8 max-w-md w-full relative overflow-hidden">
      <!-- 扫描线 -->
      <div class="absolute top-0 left-0 right-0 h-2 bg-gradient-to-r from-transparent via-neon-cyan/30 to-transparent animate-scan" />

      <div class="text-center mb-8">
        <div class="w-20 h-20 rounded-2xl bg-gradient-to-br from-neon-pink to-neon-peach flex items-center justify-center mx-auto mb-4 shadow-neon-pink text-4xl">
          🚀
        </div>
        <h1 class="text-2xl font-bold text-white mb-2">小红书增长引擎</h1>
        <p class="text-sm text-white/60 mono">AI驱动的自动化内容创作平台</p>
      </div>

      <div class="space-y-4">
        <NeonButton variant="pink" size="lg" class="w-full" @click="startNewWorkflow" :loading="isStarting">
          🚀 启动新工作流
        </NeonButton>

        <NeonButton variant="ghost" size="md" class="w-full" @click="goToDashboard" :disabled="isStarting">
          📊 查看现有工作流
        </NeonButton>
      </div>

      <div class="mt-8 text-center mono text-xs text-white/40">
        Account: default | Phase: scouting
      </div>
    </div>
  </div>
</template>