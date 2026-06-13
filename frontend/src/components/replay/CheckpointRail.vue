<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWorkflowStore } from '@/stores'
import type { CheckpointSnapshot } from '@/types/workflow'

const { t } = useI18n()
const store = useWorkflowStore()

const checkpoints = computed(() => store.replayCheckpoints)
const activeId = computed(() => store.activeCheckpointId)
const hasMore = computed(() => store.hasMoreCheckpoints)
const isLoading = computed(() => store.isLoadingCheckpoints)

function selectCp(id: string) {
  store.selectCheckpoint(id)
}

async function loadMore() {
  await store.loadMoreCheckpoints()
}

function formatDate(iso: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

const agentLabelMap: Record<string, string> = {
  trend_scout: t('showcase.phase.scouting'),
  content_strategist: t('showcase.phase.planning'),
  copywriter: t('showcase.phase.creating'),
  draft_gate: t('dashboard.timeline.short.draft'),
  brief_analyzer: t('dashboard.timeline.short.briefAnalyze'),
  brief_gate: t('dashboard.timeline.short.briefGate'),
  viral_matcher: t('dashboard.timeline.short.viralMatch'),
  blogger_scout: t('dashboard.timeline.short.bloggerScout'),
  blogger_gate: t('dashboard.timeline.short.bloggerGate'),
  shooting_planner: t('dashboard.timeline.short.shootingPlan'),
  visual_designer: t('dashboard.timeline.short.visual'),
  content_analyzer: t('dashboard.timeline.short.contentAnalysis'),
  version_generator: t('dashboard.timeline.short.versionGen'),
  choice_gate: t('dashboard.timeline.short.choiceGate'),
  review_gate: t('showcase.phase.reviewing'),
  revise_content: t('dashboard.timeline.short.reviseContent'),
  publisher: t('showcase.phase.publishing'),
  engagement: t('dashboard.timeline.short.engagement'),
  analyst: t('showcase.phase.analyzing'),
  orchestrator: t('dashboard.timeline.orchestrator'),
}

function agentLabel(agent: string): string {
  return agentLabelMap[agent] || agent
}

function hasData(cp: CheckpointSnapshot): boolean {
  const check = (v: unknown) => !!v && typeof v === 'object' && Object.keys(v as Record<string, unknown>).length > 0
  return check(cp.trend_data) || check(cp.content_plan) || check(cp.copy_content) || check(cp.visual_plan) || check(cp.publish_result) || check(cp.analytics) || check(cp.ripple_prediction) || check(cp.ripple_pmf) || check((cp as any).brief_content) || check((cp as any).shooting_plan)
}

function dataBadges(cp: CheckpointSnapshot): string[] {
  const badges: string[] = []
  const check = (v: unknown) => !!v && typeof v === 'object' && Object.keys(v as Record<string, unknown>).length > 0
  if (check(cp.trend_data)) badges.push(t('replay.badgeTrend'))
  if (check(cp.content_plan)) badges.push(t('replay.badgeStrategy'))
  if (check(cp.copy_content)) badges.push(t('replay.badgeCopy'))
  if (check((cp as any).brief_content)) badges.push('Brief')
  if (check((cp as any).shooting_plan)) badges.push(t('replay.badgeShooting'))
  if (check(cp.visual_plan)) badges.push(t('replay.badgeVisual'))
  if (check(cp.publish_result)) badges.push(t('replay.badgePublish'))
  if (check(cp.analytics)) badges.push(t('replay.badgeAnalytics'))
  if (check(cp.ripple_prediction) || check(cp.ripple_pmf)) badges.push('Ripple')
  return badges
}

function phaseColor(phase: string): string {
  const map: Record<string, string> = {
    scouting: 'bg-rose-100 text-rose-700 border-rose-200',
    planning: 'bg-teal-100 text-teal-700 border-teal-200',
    briefing: 'bg-pink-100 text-pink-700 border-pink-200',
    creating: 'bg-amber-100 text-amber-700 border-amber-200',
    reviewing: 'bg-violet-100 text-violet-700 border-violet-200',
    publishing: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    analyzing: 'bg-sky-100 text-sky-700 border-sky-200',
    completed: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    error: 'bg-rose-100 text-rose-700 border-rose-200',
    paused: 'bg-slate-100 text-slate-700 border-slate-200',
    cancelled: 'bg-slate-100 text-slate-600 border-slate-200',
  }
  return map[phase] || 'bg-slate-100 text-slate-600 border-slate-200'
}

const checkpointItems = computed(() =>
  checkpoints.value.map((cp) => ({
    cp,
    label: agentLabel(cp.current_agent),
    badges: dataBadges(cp),
    hasData: hasData(cp),
    phaseClass: phaseColor(cp.phase),
    isActive: cp.checkpoint_id === activeId.value,
    dateLabel: formatDate(cp.created_at),
  }))
)
</script>

<template>
  <div class="space-y-1">
    <div class="text-[10px] text-slate-400 font-medium uppercase tracking-widest mb-2">{{ t('replay.checkpoints') }}</div>
    <div
      v-for="item in checkpointItems"
      :key="item.cp.checkpoint_id"
      v-memo="[item.isActive, item.label, item.badges.length, item.hasData]"
      class="p-2 rounded-lg cursor-pointer transition-all duration-150 border"
      :class="item.isActive
        ? 'liquid-glass-violet border-violet-200 shadow-sm'
        : 'border-transparent hover:bg-slate-50'"
      @click="selectCp(item.cp.checkpoint_id)"
    >
      <div class="flex items-center gap-1.5 mb-0.5">
        <span class="text-[10px] font-medium px-1.5 py-0.5 rounded border" :class="item.phaseClass">{{ item.label }}</span>
        <span class="text-[10px] text-slate-400 ml-auto">{{ t('replay.step') }} {{ item.cp.step }}</span>
      </div>
      <div v-if="item.cp.created_at" class="text-[10px] text-slate-400">{{ item.dateLabel }}</div>
      <div v-if="item.badges.length" class="flex flex-wrap gap-0.5 mt-1">
        <span v-for="badge in item.badges" :key="badge" class="text-[9px] px-1 py-0 rounded bg-slate-100 text-slate-500">{{ badge }}</span>
      </div>
      <div v-if="!item.hasData" class="text-[9px] text-slate-300 mt-0.5">{{ t('replay.noData') }}</div>
    </div>
    <button
      v-if="hasMore"
      @click="loadMore"
      :disabled="isLoading"
      class="w-full py-1.5 text-[10px] text-slate-500 hover:text-slate-700 font-medium transition-colors disabled:opacity-50"
    >
      {{ isLoading ? t('common.loadingState') : t('replay.loadMore') }}
    </button>
  </div>
</template>
