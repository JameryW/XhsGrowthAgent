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

const goBack = () => {
  // Direct hits on a bad link have no in-app history — fall back to /start.
  if (window.history.state?.back) router.back()
  else router.push('/start')
}
</script>

<template>
  <main class="relative flex min-h-[80vh] flex-col items-center justify-center overflow-hidden px-4 py-10" aria-labelledby="not-found-title">
    <!-- Elegant gradient orbs -->
    <div class="absolute top-1/3 left-1/3 w-[400px] h-[400px] rounded-full opacity-40 pointer-events-none" style="background: radial-gradient(circle, rgba(244,63,94,0.1) 0%, transparent 60%); filter: blur(80px);" />
    <div class="absolute bottom-1/3 right-1/3 w-[350px] h-[350px] rounded-full opacity-30 pointer-events-none" style="background: radial-gradient(circle, rgba(20,184,166,0.08) 0%, transparent 60%); filter: blur(100px);" />

    <div class="relative w-full max-w-lg overflow-hidden rounded-3xl border border-white/80 bg-white/75 p-8 text-center shadow-xl shadow-slate-200/60 backdrop-blur-xl md:p-10 dark:border-slate-700/60 dark:bg-slate-900/90 dark:shadow-slate-950/50">
      <!-- Error icon -->
      <div class="w-20 h-20 rounded-2xl bg-gradient-to-br from-rose-400 to-amber-400 flex items-center justify-center mx-auto mb-6 shadow-sm">
        <AppIcon name="SearchX" size="xl" variant="white" :aria-label="t('notFound.title')" />
      </div>

      <!-- Error code -->
      <h1 id="not-found-title" class="mb-3 text-4xl font-bold tracking-tight text-slate-800">{{ t('notFound.title') }}</h1>

      <!-- Message -->
      <p class="mb-2 text-xs font-bold uppercase tracking-[0.18em] text-rose-400">{{ t('notFound.label') }}</p>
      <p class="text-sm text-slate-400 mb-8">{{ t('notFound.message') }}</p>

      <!-- Navigation buttons -->
      <div class="flex flex-wrap justify-center gap-3">
        <NeonButton variant="cyan" size="lg" class="min-h-11" @click="goHome">
          <span class="inline-flex items-center gap-2">
            <AppIcon name="Home" size="md" variant="white" />
            <span>{{ t('notFound.backHome') }}</span>
          </span>
        </NeonButton>
        <NeonButton variant="ghost" size="lg" class="min-h-11" @click="goBack">
          <span class="inline-flex items-center gap-2">
            <AppIcon name="ArrowLeft" size="md" variant="cyan" />
            <span>{{ t('notFound.backPrev') }}</span>
          </span>
        </NeonButton>
      </div>
    </div>
  </main>
</template>
