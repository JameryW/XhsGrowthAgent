<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { CheckpointSnapshot } from '@/types/workflow'

const { t } = useI18n()
defineProps<{ cp: CheckpointSnapshot }>()
</script>

<template>
  <div v-if="cp.content_plan" class="replay-section">
    <!-- Topic — L1 -->
    <div class="text-base font-bold text-slate-800 leading-snug">{{ cp.content_plan.selected_topic }}</div>
    <div class="text-xs text-slate-500 mt-1">{{ cp.content_plan.content_angle }}</div>

    <!-- Key attributes — L4 label + L2 value -->
    <div class="grid grid-cols-2 md:grid-cols-3 gap-2 mt-3">
      <div v-if="cp.content_plan.content_type" class="p-2 rounded-lg liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.contentType') }}</div>
        <div class="text-xs font-semibold text-slate-700">{{ cp.content_plan.content_type }}</div>
      </div>
      <div v-if="cp.content_plan.target_audience" class="p-2 rounded-lg liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.targetAudience') }}</div>
        <div class="text-xs font-semibold text-slate-700">{{ cp.content_plan.target_audience }}</div>
      </div>
      <div v-if="cp.content_plan.urgency" class="p-2 rounded-lg liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.urgency') }}</div>
        <div class="text-xs font-semibold text-slate-700">{{ cp.content_plan.urgency }}</div>
      </div>
      <div v-if="cp.content_plan.suggested_timing" class="p-2 rounded-lg liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.suggestedTiming') }}</div>
        <div class="text-xs font-semibold text-slate-700">{{ cp.content_plan.suggested_timing }}</div>
      </div>
    </div>

    <!-- Key points -->
    <div v-if="cp.content_plan.key_points?.length" class="mt-3">
      <div class="text-[10px] text-slate-400 font-medium mb-1.5 uppercase tracking-wide">{{ t('replay.keyPoints') }}</div>
      <div class="space-y-1">
        <div v-for="(point, i) in cp.content_plan.key_points" :key="i" class="text-xs text-slate-600 flex gap-1.5">
          <span class="text-slate-300">&#9656;</span>
          <span>{{ point }}</span>
        </div>
      </div>
    </div>

    <!-- Hashtags -->
    <div v-if="cp.content_plan.hashtags?.length" class="flex flex-wrap gap-1.5 mt-3">
      <span v-for="tag in cp.content_plan.hashtags" :key="tag" class="text-[10px] px-1.5 py-0.5 rounded bg-teal-50 text-teal-600 dark:bg-teal-950/50 dark:text-teal-300">#{{ tag }}</span>
    </div>
  </div>
</template>

<style scoped>
.replay-section {
  border-radius: 0.75rem;
  background: rgba(248, 250, 252, 0.66);
  border: 1px solid rgba(226, 232, 240, 0.72);
  padding: 0.75rem 1rem;
  box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.04);
}
</style>
