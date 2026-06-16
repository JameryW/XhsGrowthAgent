<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWorkflowStore } from '@/stores'

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

function formatDate(iso: string | null) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

const checkpointItems = computed(() =>
  checkpoints.value.map((cp) => ({
    id: cp.checkpoint_id,
    label: agentLabel(cp.current_agent),
    step: cp.step,
    date: formatDate(cp.created_at),
    isActive: cp.checkpoint_id === activeId.value,
  }))
)
</script>

<template>
  <div class="space-y-0.5">
    <div class="text-[10px] text-slate-400 font-medium uppercase tracking-widest mb-2">{{ t('replay.checkpoints') }}</div>
    <button
      v-for="item in checkpointItems"
      :key="item.id"
      v-memo="[item.isActive, item.label]"
      @click="selectCp(item.id)"
      class="w-full flex items-center gap-2 py-1.5 px-2 rounded-lg transition-colors text-left"
      :class="item.isActive
        ? 'bg-slate-800 text-white'
        : 'hover:bg-slate-50 text-slate-600'"
    >
      <!-- Step number -->
      <span class="text-[10px] font-mono shrink-0" :class="item.isActive ? 'text-slate-300' : 'text-slate-400'">{{ item.step }}</span>
      <!-- Agent label -->
      <span class="text-xs font-medium truncate" :class="item.isActive ? 'text-white' : 'text-slate-700'">{{ item.label }}</span>
      <!-- Date (only on active or hover) -->
      <span v-if="item.date" class="text-[10px] ml-auto shrink-0" :class="item.isActive ? 'text-slate-300' : 'text-slate-400'">{{ item.date }}</span>
    </button>
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
