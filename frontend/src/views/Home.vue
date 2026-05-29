<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import LoadingOverlay from '@/components/LoadingOverlay.vue'
import { useWorkflowStore } from '@/stores'

const { t } = useI18n()

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
  <div class="min-h-[80vh] flex flex-col items-center justify-center relative overflow-hidden">
    <!-- Animated gradient mesh -->
    <div class="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden="true">
      <div class="absolute top-1/4 left-1/4 w-[400px] h-[400px] rounded-full opacity-60 animate-pulse" style="background: radial-gradient(circle, rgba(244,63,94,0.12) 0%, transparent 50%); animation-duration: 4s;" />
      <div class="absolute bottom-1/4 right-1/4 w-[350px] h-[350px] rounded-full opacity-50 animate-pulse" style="background: radial-gradient(circle, rgba(20,184,166,0.1) 0%, transparent 50%); animation-duration: 5s; animation-delay: 1s;" />
      <div class="absolute top-1/2 right-1/3 w-[250px] h-[250px] rounded-full opacity-40 animate-pulse" style="background: radial-gradient(circle, rgba(139,92,246,0.08) 0%, transparent 50%); animation-duration: 6s; animation-delay: 2s;" />
    </div>

    <!-- 主卡片 -->
    <div class="rounded-2xl p-10 max-w-lg w-full relative overflow-hidden bg-white/85 backdrop-blur-xl border border-white/50 shadow-2xl shadow-rose-500/5 transition-all duration-300 hover:shadow-rose-500/10 group" role="region" :aria-label="t('home.systemStatus')">
      <!-- Glow effect -->
      <div class="absolute -inset-px rounded-2xl bg-gradient-to-r from-rose-400/20 via-teal-400/20 to-violet-400/20 opacity-0 group-hover:opacity-100 transition-opacity duration-500 -z-10 blur-xl" aria-hidden="true" />

      <div class="text-center mb-10 relative">
        <div class="relative inline-block mb-6 group/icon">
          <div class="w-24 h-24 rounded-2xl bg-gradient-to-br from-rose-400 via-rose-500 to-amber-400 flex items-center justify-center shadow-xl shadow-rose-500/30 transition-all duration-300 group-hover/icon:shadow-rose-500/50 group-hover/icon:scale-105 group-hover/icon:-translate-y-1" aria-hidden="true">
            <AppIcon name="Rocket" size="xl" variant="white" />
          </div>
          <!-- Floating particles -->
          <div class="absolute -top-2 -right-2 w-4 h-4 rounded-full bg-rose-400 opacity-60 animate-ping" style="animation-duration: 2s;" aria-hidden="true" />
          <div class="absolute -bottom-1 -left-3 w-3 h-3 rounded-full bg-teal-400 opacity-50 animate-ping" style="animation-duration: 2.5s; animation-delay: 0.5s;" aria-hidden="true" />
        </div>
        <h1 class="text-3xl font-bold mb-3 text-slate-800 tracking-tight">{{ t('home.title') }}</h1>
        <p class="text-base text-slate-500 font-medium">{{ t('home.subtitle') }}</p>
      </div>

      <div class="space-y-4">
        <NeonButton variant="pink" size="lg" class="w-full group/btn" @click="startNewWorkflow" :loading="isStarting" :aria-label="t('home.startWorkflow')">
          <span class="inline-flex items-center gap-3 transition-transform duration-200 group-hover/btn:translate-x-1">
            <AppIcon name="Rocket" size="md" variant="white" aria-hidden="true" />
            <span class="font-medium">{{ t('home.startWorkflow') }}</span>
          </span>
        </NeonButton>

        <NeonButton variant="ghost" size="md" class="w-full" @click="goToDashboard" :disabled="isStarting" :aria-label="t('home.viewDashboard')">
          <span class="inline-flex items-center gap-3">
            <AppIcon name="BarChart3" size="md" variant="cyan" aria-hidden="true" />
            <span>{{ t('home.viewDashboard') }}</span>
          </span>
        </NeonButton>
      </div>

      <div class="mt-8 bg-gradient-to-r from-slate-50/80 to-white rounded-xl p-4 text-center border border-slate-100 hover:border-slate-200 transition-all duration-200" role="status" aria-live="polite" :aria-label="t('home.systemStatus')">
        <div class="flex items-center justify-center gap-6 text-xs text-slate-500">
          <div class="flex items-center gap-2 group hover:scale-105 transition-transform">
            <div class="w-2 h-2 rounded-full bg-teal-500 animate-pulse" aria-hidden="true" />
            <span>{{ t('home.account') }}: <span class="text-teal-600 font-medium">default</span></span>
          </div>
          <div class="flex items-center gap-2 group hover:scale-105 transition-transform">
            <AppIcon name="Zap" size="sm" variant="peach" aria-hidden="true" />
            <span>{{ t('home.phase') }}: <span class="text-amber-600 font-medium">scouting</span></span>
          </div>
        </div>
      </div>
    </div>

    <!-- Loading Overlay -->
    <LoadingOverlay
      :is-visible="workflowStore.isOverlayLoading"
      :message="t('home.loadingOverlay', { phase: workflowStore.currentPhase })"
      @cancel="workflowStore.cancelWorkflow"
    />
  </div>
</template>