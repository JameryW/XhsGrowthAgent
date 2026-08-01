<script setup lang="ts">
import ContentCardSkeleton from './ContentCardSkeleton.vue'
</script>

<template>
  <div class="space-y-4 md:space-y-6">
    <!-- Header skeleton: mirrors the real state hero (icon box, eyebrow/title/
         description, status pill + progress text, full-width progress bar) so
         the swap doesn't jump. -->
    <div class="rounded-2xl p-4 md:p-6 bg-white/90 backdrop-blur-sm border border-slate-200/50 dark:bg-slate-900/90 dark:border-slate-700/55">
      <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div class="flex min-w-0 flex-1 items-start gap-3 md:gap-4">
          <div class="h-12 w-12 md:h-14 md:w-14 shrink-0 rounded-2xl bg-gradient-to-r from-teal-500/20 to-teal-400/20 animate-pulse" />
          <div class="min-w-0 flex-1 space-y-2">
            <div class="h-2.5 w-24 rounded bg-gradient-to-r animate-pulse from-teal-500/20 to-teal-400/20" />
            <div class="h-6 w-40 max-w-full rounded bg-gradient-to-r animate-pulse from-slate-300/30 to-slate-200/30" />
            <div class="h-3.5 w-3/4 rounded bg-gradient-to-r animate-pulse from-slate-300/30 to-slate-200/30" />
          </div>
        </div>
        <div class="flex shrink-0 items-center gap-3 sm:flex-col sm:items-end sm:gap-1">
          <div class="h-6 w-20 rounded-full bg-gradient-to-r animate-pulse from-slate-300/30 to-slate-200/30" />
          <div class="h-3 w-16 rounded bg-gradient-to-r animate-pulse from-slate-300/30 to-slate-200/30" />
        </div>
      </div>
      <div class="mt-4 h-2 w-full rounded-full bg-gradient-to-r animate-pulse from-teal-500/20 to-teal-400/20" />
    </div>

    <!-- Timeline skeleton (square nodes match the real WorkflowNode shape) -->
    <div class="bg-white/90 backdrop-blur-sm rounded-2xl p-6 border border-slate-200/50 dark:bg-slate-900/90 dark:border-slate-700/55">
      <div class="h-4 w-32 rounded bg-gradient-to-r animate-pulse mb-4 from-slate-300/30 to-slate-200/30" />
      <div class="flex justify-between gap-4">
        <div v-for="i in 6" :key="i" class="flex flex-col items-center gap-2">
          <div class="w-10 h-10 rounded-xl bg-gradient-to-r animate-pulse from-slate-300/30 to-slate-200/30" />
          <div class="h-3 w-16 rounded bg-gradient-to-r animate-pulse from-slate-300/30 to-slate-200/30" />
        </div>
      </div>
    </div>

    <!-- Cards skeleton -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <ContentCardSkeleton variant="pink" />
      <ContentCardSkeleton variant="cyan" />
      <ContentCardSkeleton variant="purple" />
    </div>

    <!-- Buttons skeleton -->
    <div class="flex flex-wrap gap-3">
      <div v-for="i in 3" :key="i" class="h-10 w-32 rounded-lg bg-gradient-to-r animate-pulse from-slate-300/30 to-slate-200/30" />
    </div>
  </div>
</template>