<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { CheckpointSnapshot } from '@/types/workflow'

const { t } = useI18n()
defineProps<{ cp: CheckpointSnapshot }>()
</script>

<template>
  <div v-if="cp.content_plan">
    <div>
      <div class="text-base font-bold text-slate-800 leading-snug">{{ cp.content_plan.selected_topic }}</div>
      <div class="text-xs text-slate-500 mt-1">{{ cp.content_plan.content_angle }}</div>
    </div>
    <div class="grid grid-cols-2 md:grid-cols-3 gap-2">
      <div v-if="cp.content_plan.content_type" class="p-2 rounded-lg bg-teal-50 border border-teal-100">
        <div class="text-[10px] text-teal-500 font-medium">{{ t('replay.contentType') }}</div>
        <div class="text-xs text-teal-700 font-medium">{{ cp.content_plan.content_type }}</div>
      </div>
      <div v-if="cp.content_plan.target_audience" class="p-2 rounded-lg liquid-glass-inset">
        <div class="text-[10px] text-slate-400 font-medium">{{ t('replay.targetAudience') }}</div>
        <div class="text-xs text-slate-700">{{ cp.content_plan.target_audience }}</div>
      </div>
      <div v-if="cp.content_plan.urgency" class="p-2 rounded-lg bg-rose-50 border border-rose-100">
        <div class="text-[10px] text-rose-500 font-medium">{{ t('replay.urgency') }}</div>
        <div class="text-xs text-rose-700 font-medium">{{ cp.content_plan.urgency }}</div>
      </div>
      <div v-if="cp.content_plan.suggested_timing" class="p-2 rounded-lg bg-amber-50 border border-amber-100">
        <div class="text-[10px] text-amber-500 font-medium">{{ t('replay.suggestedTiming') }}</div>
        <div class="text-xs text-amber-700">{{ cp.content_plan.suggested_timing }}</div>
      </div>
    </div>
    <div v-if="cp.content_plan.key_points?.length">
      <div class="text-xs text-slate-400 font-medium mb-1.5 uppercase tracking-wide">{{ t('replay.keyPoints') }}</div>
      <div class="space-y-1">
        <div v-for="(point, i) in cp.content_plan.key_points" :key="i" class="text-xs text-slate-600 flex gap-1.5">
          <span class="text-cyan-400">&#9656;</span>
          <span>{{ point }}</span>
        </div>
      </div>
    </div>
    <div v-if="cp.content_plan.hashtags?.length" class="flex flex-wrap gap-1.5">
      <span v-for="tag in cp.content_plan.hashtags" :key="tag" class="text-[11px] px-2 py-0.5 rounded-md bg-cyan-50 text-cyan-600 border border-cyan-100">#{{ tag }}</span>
    </div>
  </div>
</template>
