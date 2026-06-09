<script setup lang="ts">
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const router = useRouter()

const goHome = () => {
  router.push('/start')
}
</script>

<template>
  <div class="min-h-[80vh] flex flex-col items-center justify-center relative overflow-hidden">
    <!-- Elegant gradient orbs -->
    <div class="absolute top-1/3 left-1/3 w-[400px] h-[400px] rounded-full opacity-40 pointer-events-none" style="background: radial-gradient(circle, rgba(244,63,94,0.1) 0%, transparent 60%); filter: blur(80px);" />
    <div class="absolute bottom-1/3 right-1/3 w-[350px] h-[350px] rounded-full opacity-30 pointer-events-none" style="background: radial-gradient(circle, rgba(20,184,166,0.08) 0%, transparent 60%); filter: blur(100px);" />

    <div class="rounded-2xl p-8 max-w-md w-full text-center relative overflow-hidden bg-white/98 backdrop-blur-sm border border-slate-200/50 shadow-lg">
      <!-- Error icon -->
      <div class="w-20 h-20 rounded-2xl bg-gradient-to-br from-rose-400 to-amber-400 flex items-center justify-center mx-auto mb-6 shadow-sm">
        <AppIcon name="SearchX" size="xl" variant="white" aria-label="404" />
      </div>

      <!-- Error code -->
      <h1 class="text-5xl font-bold text-slate-800 mb-3">404</h1>

      <!-- Message -->
      <p class="text-xs text-slate-500 mb-2 uppercase tracking-wide font-medium">PAGE_NOT_FOUND</p>
      <p class="text-sm text-slate-400 mb-8">{{ t('notFound.message') }}</p>

      <!-- Navigation buttons -->
      <div class="flex gap-3 justify-center">
        <NeonButton variant="cyan" size="lg" @click="goHome">
          <span class="inline-flex items-center gap-2">
            <AppIcon name="Home" size="md" variant="white" />
            <span>{{ t('notFound.backHome') }}</span>
          </span>
        </NeonButton>
        <NeonButton variant="ghost" size="lg" @click="router.back()">
          <span class="inline-flex items-center gap-2">
            <AppIcon name="ArrowLeft" size="md" variant="cyan" />
            <span>{{ t('notFound.backPrev') }}</span>
          </span>
        </NeonButton>
      </div>
    </div>
  </div>
</template>