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
  <div v-if="cp.analytics" class="replay-section">
    <!-- Core metrics -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
      <div v-if="(cp.analytics as any).views !== undefined" class="p-2.5 rounded-lg liquid-glass-inset text-center">
        <div class="text-[10px] text-slate-400">{{ t('replay.views') }}</div>
        <div class="text-sm font-bold text-slate-700">{{ formatNum((cp.analytics as any).views) }}</div>
      </div>
      <div v-if="(cp.analytics as any).likes !== undefined" class="p-2.5 rounded-lg liquid-glass-inset text-center">
        <div class="text-[10px] text-slate-400">{{ t('replay.likes') }}</div>
        <div class="text-sm font-bold text-slate-700">{{ formatNum((cp.analytics as any).likes) }}</div>
      </div>
      <div v-if="(cp.analytics as any).collects !== undefined" class="p-2.5 rounded-lg liquid-glass-inset text-center">
        <div class="text-[10px] text-slate-400">{{ t('replay.collects') }}</div>
        <div class="text-sm font-bold text-slate-700">{{ formatNum((cp.analytics as any).collects) }}</div>
      </div>
      <div v-if="(cp.analytics as any).engagement_rate !== undefined" class="p-2.5 rounded-lg liquid-glass-inset text-center">
        <div class="text-[10px] text-slate-400">{{ t('replay.engagement') }}</div>
        <div class="text-sm font-bold text-slate-700">{{ ((cp.analytics as any).engagement_rate * 100).toFixed(1) }}%</div>
      </div>
    </div>

    <!-- Secondary metrics — collapsible -->
    <details v-if="(cp.analytics as any).comments !== undefined || (cp.analytics as any).shares !== undefined || (cp.analytics as any).insights?.length" class="mt-3">
      <summary class="text-[10px] text-slate-400 font-medium cursor-pointer hover:text-slate-600">{{ t('replay.details') || 'Details' }}</summary>
      <div class="mt-2 space-y-2">
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
          <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('showcase.detail.insights') }}</div>
          <ul class="space-y-0.5">
            <li v-for="(insight, i) in (cp.analytics as any).insights" :key="i" class="text-xs text-slate-500 flex gap-1.5">
              <span class="text-emerald-500">+</span>
              <span>{{ insight }}</span>
            </li>
          </ul>
        </div>
      </div>
    </details>
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
