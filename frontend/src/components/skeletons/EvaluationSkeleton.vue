<script setup lang="ts">
// INF-02 / EV-11: structured skeleton for the Evaluation view's loading state.
// Shapes mirror the real content so the swap doesn't jump: the list state is
// eval-item rows, the detail state is the score + radar blocks.
interface Props {
  variant?: 'list' | 'detail'
}

withDefaults(defineProps<Props>(), {
  variant: 'list',
})
</script>

<template>
  <div class="space-y-4" role="status" aria-live="polite" :aria-label="$t('evaluation.list.loading')">
    <span class="sr-only">{{ $t('evaluation.list.loading') }}</span>

    <!-- 列表态：eval-item 行形状（EvaluationView 列表加载） -->
    <template v-if="variant === 'list'">
      <div
        v-for="i in 5"
        :key="i"
        class="flex items-center justify-between gap-3 rounded-[0.625rem] border border-slate-200 bg-white px-4 py-3 dark:border-slate-700 dark:bg-slate-900"
      >
        <div class="flex-1 space-y-2">
          <div class="h-4 w-2/3 rounded bg-slate-100 animate-pulse dark:bg-slate-800" />
          <div class="h-3 w-1/3 rounded bg-slate-100 animate-pulse dark:bg-slate-800" />
        </div>
        <div class="h-6 w-12 rounded bg-slate-100 animate-pulse dark:bg-slate-800" />
      </div>
    </template>

    <!-- 详情态：总分块 + 雷达块（对齐 .result-grid 双列与 320px 雷达高度） -->
    <div v-else class="grid grid-cols-1 gap-4 md:grid-cols-2">
      <div class="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
        <div class="h-3 w-24 rounded bg-slate-100 animate-pulse dark:bg-slate-800" />
        <div class="mt-3 h-10 w-20 rounded bg-slate-100 animate-pulse dark:bg-slate-800" />
        <div class="mt-3 h-6 w-28 rounded-full bg-slate-100 animate-pulse dark:bg-slate-800" />
        <div class="mt-4 space-y-2">
          <div class="h-3 w-full rounded bg-slate-100 animate-pulse dark:bg-slate-800" />
          <div class="h-3 w-2/3 rounded bg-slate-100 animate-pulse dark:bg-slate-800" />
        </div>
      </div>
      <div class="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
        <div class="h-4 w-32 rounded bg-slate-100 animate-pulse dark:bg-slate-800" />
        <div class="mt-3 h-[260px] min-[381px]:h-[320px] rounded-lg bg-slate-100 animate-pulse dark:bg-slate-800" />
      </div>
    </div>
  </div>
</template>
