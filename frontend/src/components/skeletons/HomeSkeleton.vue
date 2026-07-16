<script setup lang="ts">
</script>

<template>
  <div class="min-h-[80vh] flex flex-col items-center justify-center relative overflow-hidden">
    <!-- Animated gradient mesh skeleton -->
    <div class="absolute inset-0 pointer-events-none overflow-hidden">
      <div class="absolute top-1/4 left-1/4 w-[400px] h-[400px] rounded-full opacity-60 bg-slate-200 animate-pulse" />
      <div class="absolute bottom-1/4 right-1/4 w-[350px] h-[350px] rounded-full opacity-50 bg-slate-100 animate-pulse" />
    </div>

    <!-- Main card skeleton -->
    <div class="rounded-2xl p-10 max-w-lg w-full relative overflow-hidden bg-white/85 backdrop-blur-xl border border-white/50 shadow-xl dark:bg-slate-900/90 dark:border-slate-700/50">
      <!-- Logo skeleton -->
      <div class="text-center mb-10">
        <div class="relative inline-block mb-6">
          <div class="w-24 h-24 rounded-2xl bg-slate-200 animate-pulse mx-auto" />
        </div>
        <div class="h-8 w-48 rounded bg-slate-200 animate-pulse mx-auto mb-3" />
        <div class="h-5 w-56 rounded bg-slate-200 animate-pulse mx-auto" />
      </div>

      <!-- Buttons skeleton -->
      <div class="space-y-4">
        <div class="h-12 w-full rounded-lg bg-slate-200 animate-pulse" />
        <div class="h-10 w-full rounded-lg bg-slate-100 animate-pulse" />
      </div>

      <!-- Status bar skeleton -->
      <div class="mt-8 bg-gradient-to-r from-slate-50/80 to-white rounded-xl p-4 border border-slate-100 dark:from-slate-800 dark:to-slate-900 dark:border-slate-700">
        <div class="flex items-center justify-center gap-6">
          <div class="flex items-center gap-2">
            <div class="w-2 h-2 rounded-full bg-slate-200 animate-pulse" />
            <div class="h-4 w-24 rounded bg-slate-200 animate-pulse" />
          </div>
          <div class="flex items-center gap-2">
            <div class="w-4 h-4 rounded bg-slate-200 animate-pulse" />
            <div class="h-4 w-20 rounded bg-slate-200 animate-pulse" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>