<script setup lang="ts">
</script>

<template>
  <div class="relative space-y-5 md:space-y-5">
    <!-- Review status bar skeleton -->
    <div class="rounded-2xl p-4 md:p-5 relative overflow-hidden bg-white/90 backdrop-blur-sm border border-slate-200/50 shadow-sm dark:bg-slate-900/90 dark:border-slate-700/55">
      <div class="flex flex-col sm:flex-row items-start sm:items-center gap-4 sm:gap-5">
        <div class="w-14 h-14 rounded-xl bg-slate-200 animate-pulse" />
        <div class="flex-1 space-y-2">
          <div class="h-5 w-20 rounded bg-slate-200 animate-pulse" />
          <div class="h-6 w-32 rounded bg-slate-200 animate-pulse" />
          <div class="h-4 w-48 rounded bg-slate-200 animate-pulse" />
        </div>
      </div>
    </div>

    <!-- Content preview skeleton -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <!-- Copy content skeleton -->
      <div class="rounded-xl p-5 border border-slate-200/50 bg-white/90 backdrop-blur-sm dark:bg-slate-900/90 dark:border-slate-700/55">
        <div class="flex items-center gap-3 mb-4">
          <div class="w-10 h-10 rounded-xl bg-slate-200 animate-pulse" />
          <div class="flex-1 space-y-1">
            <div class="h-4 w-20 rounded bg-slate-200 animate-pulse" />
            <div class="h-3 w-16 rounded bg-slate-200 animate-pulse" />
          </div>
        </div>

        <div class="bg-slate-50 rounded-lg p-4 border-l-2 border-slate-200 dark:bg-slate-800/70 dark:border-slate-600">
          <div class="space-y-3">
            <div class="h-5 w-3/4 rounded bg-slate-200 animate-pulse" />
            <div class="h-4 w-full rounded bg-slate-200 animate-pulse" />
            <div class="h-4 w-2/3 rounded bg-slate-200 animate-pulse" />
            <div class="flex gap-2 mt-3">
              <div class="h-6 w-16 rounded bg-slate-200 animate-pulse" />
              <div class="h-6 w-20 rounded bg-slate-200 animate-pulse" />
              <div class="h-6 w-14 rounded bg-slate-200 animate-pulse" />
            </div>
          </div>
        </div>
      </div>

      <!-- Visual plan skeleton -->
      <div class="rounded-xl p-5 border border-slate-200/50 bg-white/90 backdrop-blur-sm dark:bg-slate-900/90 dark:border-slate-700/55">
        <div class="flex items-center gap-3 mb-4">
          <div class="w-10 h-10 rounded-xl bg-slate-200 animate-pulse" />
          <div class="flex-1 space-y-1">
            <div class="h-4 w-20 rounded bg-slate-200 animate-pulse" />
            <div class="h-3 w-16 rounded bg-slate-200 animate-pulse" />
          </div>
        </div>

        <div class="bg-slate-50 rounded-lg p-4 border-l-2 border-slate-200 dark:bg-slate-800/70 dark:border-slate-600">
          <div class="space-y-3">
            <div class="h-5 w-1/2 rounded bg-slate-200 animate-pulse" />
            <div class="h-4 w-full rounded bg-slate-200 animate-pulse" />
            <div class="flex gap-2 mt-3">
              <div class="w-6 h-6 rounded-lg bg-slate-200 animate-pulse" />
              <div class="w-6 h-6 rounded-lg bg-slate-200 animate-pulse" />
              <div class="w-6 h-6 rounded-lg bg-slate-200 animate-pulse" />
              <div class="w-6 h-6 rounded-lg bg-slate-200 animate-pulse" />
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Action buttons skeleton -->
    <div class="rounded-2xl p-5 border border-slate-200/50 bg-white/90 backdrop-blur-sm shadow-sm dark:bg-slate-900/90 dark:border-slate-700/55">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-lg bg-slate-200 animate-pulse" />
        <div class="space-y-1">
          <div class="h-4 w-24 rounded bg-slate-200 animate-pulse" />
          <div class="h-3 w-16 rounded bg-slate-200 animate-pulse" />
        </div>
      </div>

      <!-- Buttons skeleton -->
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
        <div class="h-32 rounded-lg bg-slate-200 animate-pulse" />
        <div class="h-32 rounded-lg bg-slate-200 animate-pulse" />
        <div class="h-32 rounded-lg bg-slate-200 animate-pulse" />
      </div>

      <!-- Feedback input skeleton -->
      <div class="bg-slate-50 rounded-lg p-4 border border-slate-100 dark:bg-slate-800/70 dark:border-slate-700/50">
        <div class="flex items-center gap-2 mb-2">
          <div class="w-4 h-4 rounded bg-slate-200 animate-pulse" />
          <div class="h-3 w-24 rounded bg-slate-200 animate-pulse" />
        </div>
        <div class="h-20 w-full rounded bg-slate-200 animate-pulse" />
      </div>
    </div>
  </div>
</template>
