<script setup lang="ts">
// INF-02: structured skeleton for the Showcase case grid loading state.
// Shapes mirror the real case cards (first card spans two columns) so the
// swap doesn't jump.
</script>

<template>
  <div class="grid gap-4 md:grid-cols-3" role="status" aria-live="polite" :aria-label="$t('showcase.loadingCases')">
    <span class="sr-only">{{ $t('showcase.loadingCases') }}</span>
    <div
      v-for="index in 6"
      :key="index"
      class="dark-explicit h-72 animate-pulse rounded-2xl bg-white/80 dark:bg-slate-900/80"
      :class="index === 1 ? 'md:col-span-2' : ''"
      aria-busy="true"
    />
  </div>
</template>
