<script setup lang="ts">
import MetricCardSkeleton from './MetricCardSkeleton.vue'
import DataTableSkeleton from './DataTableSkeleton.vue'
</script>

<template>
  <div class="relative space-y-6 md:space-y-8">
    <!-- Header skeleton -->
    <div class="rounded-2xl p-4 md:p-5 relative overflow-hidden bg-white/98 backdrop-blur-sm border border-slate-200/50 shadow-sm dark:bg-slate-900/90 dark:border-slate-700/55">
      <div class="flex flex-col sm:flex-row items-start sm:items-center gap-4 sm:gap-5">
        <div class="w-14 h-14 rounded-xl bg-slate-200 animate-pulse" />
        <div class="flex-1 space-y-2">
          <div class="h-5 w-20 rounded bg-slate-200 animate-pulse" />
          <div class="h-6 w-32 rounded bg-slate-200 animate-pulse" />
          <div class="h-4 w-48 rounded bg-slate-200 animate-pulse" />
        </div>
        <!-- Mirrors the live header actions: refresh + 3 period buttons. -->
        <div class="flex gap-2">
          <div class="h-8 w-16 rounded bg-slate-200 animate-pulse" />
          <div class="h-8 w-16 rounded bg-slate-200 animate-pulse" />
          <div class="h-8 w-16 rounded bg-slate-200 animate-pulse" />
          <div class="h-8 w-16 rounded bg-slate-200 animate-pulse" />
        </div>
      </div>
    </div>

    <!-- Metrics skeleton: mirrors the live page's 5-card grid to avoid a
         layout jump when loading finishes. -->
    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-3 xl:grid-cols-5 gap-3 md:gap-5">
      <MetricCardSkeleton v-for="i in 5" :key="i" />
    </div>

    <!-- Charts skeleton (live charts render at 220px) -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
      <div class="rounded-2xl p-5 bg-white/98 border border-slate-200/50 shadow-sm dark:bg-slate-900/90 dark:border-slate-700/55">
        <div class="flex items-center gap-3 mb-4">
          <div class="w-10 h-10 rounded-lg bg-slate-200 animate-pulse" />
          <div class="h-5 w-20 rounded bg-slate-200 animate-pulse" />
        </div>
        <div class="h-[220px] rounded-lg bg-slate-100 animate-pulse dark:bg-slate-800" />
      </div>
      <div class="rounded-2xl p-5 bg-white/98 border border-slate-200/50 shadow-sm dark:bg-slate-900/90 dark:border-slate-700/55">
        <div class="flex items-center gap-3 mb-4">
          <div class="w-10 h-10 rounded-lg bg-slate-200 animate-pulse" />
          <div class="h-5 w-20 rounded bg-slate-200 animate-pulse" />
        </div>
        <div class="h-[220px] rounded-lg bg-slate-100 animate-pulse dark:bg-slate-800" />
      </div>
    </div>

    <!-- Table skeleton -->
    <div class="rounded-2xl p-5 bg-white/98 border border-slate-200/50 shadow-sm dark:bg-slate-900/90 dark:border-slate-700/55">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-lg bg-slate-200 animate-pulse" />
        <div class="space-y-1">
          <div class="h-4 w-24 rounded bg-slate-200 animate-pulse" />
          <div class="h-3 w-12 rounded bg-slate-200 animate-pulse" />
        </div>
      </div>
      <DataTableSkeleton :rows="10" :columns="6" />
    </div>
  </div>
</template>
