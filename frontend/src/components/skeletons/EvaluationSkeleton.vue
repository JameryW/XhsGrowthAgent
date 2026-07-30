<script setup lang="ts">
// INF-02 / EV-11: structured skeleton for the Evaluation view's loading state
// (list + trend), replacing plain text placeholders.
</script>

<template>
  <div class="space-y-4" role="status" aria-live="polite" :aria-label="$t('evaluation.list.loading')">
    <span class="sr-only">{{ $t('evaluation.list.loading') }}</span>
    <!-- trend card skeleton -->
    <div class="rounded-xl border border-slate-200/50 bg-white/90 p-6 dark:border-slate-700/55 dark:bg-slate-900/90">
      <div class="h-4 w-40 rounded bg-slate-100 animate-pulse dark:bg-slate-800" />
      <div class="mt-4 h-[220px] w-full rounded-lg bg-slate-100 animate-pulse dark:bg-slate-800" />
    </div>
    <!-- table skeleton -->
    <div class="rounded-xl border border-slate-200/50 bg-white/90 p-4 dark:border-slate-700/55 dark:bg-slate-900/90">
      <div v-for="i in 5" :key="i" class="mb-3 flex items-center gap-3">
        <div class="h-4 flex-1 rounded bg-slate-100 animate-pulse dark:bg-slate-800" />
        <div class="h-4 w-16 rounded bg-slate-100 animate-pulse dark:bg-slate-800" />
      </div>
    </div>
  </div>
</template>
