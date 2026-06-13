<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { CheckpointSnapshot } from '@/types/workflow'

const { t } = useI18n()
defineProps<{ cp: CheckpointSnapshot }>()

function formatNum(n?: number): string {
  if (n === undefined || n === null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString()
}
</script>

<template>
  <div v-if="cp.analytics">
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
      <div v-if="(cp.analytics as any).views !== undefined" class="p-2.5 rounded-lg liquid-glass-inset text-center">
        <div class="text-[10px] text-slate-400">{{ t('replay.views') }}</div>
        <div class="text-base font-bold text-slate-700">{{ formatNum((cp.analytics as any).views) }}</div>
      </div>
      <div v-if="(cp.analytics as any).likes !== undefined" class="p-2.5 rounded-lg bg-pink-50 border border-pink-100 text-center">
        <div class="text-[10px] text-slate-400">{{ t('replay.likes') }}</div>
        <div class="text-base font-bold text-pink-600">{{ formatNum((cp.analytics as any).likes) }}</div>
      </div>
      <div v-if="(cp.analytics as any).collects !== undefined" class="p-2.5 rounded-lg bg-amber-50 border border-amber-100 text-center">
        <div class="text-[10px] text-slate-400">{{ t('replay.collects') }}</div>
        <div class="text-base font-bold text-amber-600">{{ formatNum((cp.analytics as any).collects) }}</div>
      </div>
      <div v-if="(cp.analytics as any).engagement_rate !== undefined" class="p-2.5 rounded-lg bg-teal-50 border border-teal-100 text-center">
        <div class="text-[10px] text-slate-400">{{ t('replay.engagement') }}</div>
        <div class="text-base font-bold text-teal-600">{{ ((cp.analytics as any).engagement_rate * 100).toFixed(1) }}%</div>
      </div>
    </div>
    <div v-if="(cp.analytics as any).comments !== undefined || (cp.analytics as any).shares !== undefined" class="grid grid-cols-2 gap-2">
      <div v-if="(cp.analytics as any).comments !== undefined" class="p-2 rounded-lg liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.comments') }}</div>
        <div class="text-xs font-semibold text-slate-700">{{ (cp.analytics as any).comments }}</div>
      </div>
      <div v-if="(cp.analytics as any).shares !== undefined" class="p-2 rounded-lg liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.shares') }}</div>
        <div class="text-xs font-semibold text-slate-700">{{ (cp.analytics as any).shares }}</div>
      </div>
    </div>
    <div v-if="(cp.analytics as any).insights?.length">
      <div class="text-xs text-slate-400 font-medium mb-1.5 uppercase tracking-wide">{{ t('showcase.detail.insights') }}</div>
      <ul class="space-y-1">
        <li v-for="(insight, i) in (cp.analytics as any).insights" :key="i" class="text-xs text-slate-500 flex gap-1.5">
          <span class="text-emerald-500">+</span>
          <span>{{ insight }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>
