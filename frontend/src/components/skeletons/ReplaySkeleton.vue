<script setup lang="ts">
// INF-02: structured skeleton for the WorkflowReplay initial manifest load.
// Reuses the global shimmer-surface (styles/public-pages.css) so dark mode
// and reduced-motion behavior stay centralized.
</script>

<template>
  <section class="glass-panel rounded-3xl p-6" role="status" aria-live="polite" aria-busy="true">
    <span class="sr-only">{{ $t('replay.loadingWorkflow') }}</span>
    <div class="dark-explicit shimmer-surface h-5 w-2/3 rounded bg-slate-200 dark:bg-slate-800" />
    <div class="dark-explicit shimmer-surface mt-4 h-3 w-full rounded bg-slate-100 dark:bg-slate-800" />
    <div class="dark-explicit shimmer-surface mt-8 h-64 rounded-2xl bg-slate-100 dark:bg-slate-800" />
    <p class="mt-4 text-sm text-slate-500">{{ $t('replay.loadingWorkflow') }}</p>
  </section>
</template>
