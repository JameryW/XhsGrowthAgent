<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWorkflowStore } from '@/stores'

const { t, locale } = useI18n()
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
  return d.toLocaleString(locale.value || undefined, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

const checkpointItems = computed(() =>
  checkpoints.value.map((cp) => ({
    id: cp.checkpoint_id,
    label: agentLabel(cp.current_agent),
    step: cp.step,
    date: formatDate(cp.created_at),
    isActive: cp.checkpoint_id === activeId.value,
    phase: cp.phase,
    hasData: [cp.trend_data, cp.content_plan, cp.copy_content, cp.visual_plan, cp.publish_result, cp.analytics, cp.ripple_prediction, cp.ripple_pmf].some((value) => {
      if (!value) return false
      if (Array.isArray(value)) return value.length > 0
      return typeof value === 'object' ? Object.keys(value as Record<string, unknown>).length > 0 : true
    }),
  }))
)

const phaseLabelKeys: Record<string, string> = {
  scouting: 'showcase.phase.scouting',
  planning: 'showcase.phase.planning',
  briefing: 'dashboard.timeline.briefing',
  creating: 'showcase.phase.creating',
  reviewing: 'showcase.phase.reviewing',
  publishing: 'showcase.phase.publishing',
  analyzing: 'showcase.phase.analyzing',
}

const groupedCheckpoints = computed(() => {
  const groups: Array<{ phase: string; label: string; items: typeof checkpointItems.value }> = []
  for (const item of checkpointItems.value) {
    let group = groups.find(entry => entry.phase === item.phase)
    if (!group) {
      group = { phase: item.phase, label: phaseLabelKeys[item.phase] ? t(phaseLabelKeys[item.phase]) : item.phase, items: [] }
      groups.push(group)
    }
    group.items.push(item)
  }
  return groups
})
</script>

<template>
  <div class="replay-checkpoint-rail space-y-2" role="list" :aria-label="t('replay.checkpoints')">
    <div class="replay-checkpoint-heading text-[10px] text-slate-400 font-medium uppercase tracking-widest mb-2">{{ t('replay.checkpoints') }}</div>
    <section v-for="group in groupedCheckpoints" :key="group.phase" class="space-y-0.5" role="group" :aria-label="group.label">
      <h3 class="px-2 pt-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">{{ group.label }}</h3>
      <button
        v-for="item in group.items"
        :key="item.id"
        v-memo="[item.isActive, item.label, item.hasData]"
        type="button"
        @click="selectCp(item.id)"
        class="replay-checkpoint-item w-full flex items-center gap-2 py-1.5 px-2 rounded-lg transition-colors text-left"
        :class="item.isActive ? 'bg-slate-800 text-white dark:bg-slate-100 dark:text-slate-900' : 'hover:bg-slate-50 text-slate-600 dark:hover:bg-slate-800/80 dark:text-slate-300'"
        :aria-pressed="item.isActive"
        :aria-current="item.isActive ? 'step' : undefined"
        role="listitem"
      >
        <span class="text-[10px] font-mono shrink-0" :class="item.isActive ? 'text-slate-300 dark:text-slate-600' : 'text-slate-400'">{{ item.step }}</span>
        <span class="text-xs font-medium truncate" :class="item.isActive ? 'text-white dark:text-slate-900' : 'text-slate-700'">{{ item.label }}</span>
        <span class="ml-auto flex shrink-0 items-center gap-1">
          <span class="h-1.5 w-1.5 rounded-full" :class="item.hasData ? 'bg-emerald-400' : 'bg-slate-300 dark:bg-slate-600'" :aria-label="item.hasData ? t('replay.dataAvailable') : t('replay.noData')" />
          <span v-if="item.date" class="text-[10px]" :class="item.isActive ? 'text-slate-300 dark:text-slate-600' : 'text-slate-400'">{{ item.date }}</span>
        </span>
      </button>
    </section>
    <button
      v-if="hasMore"
      @click="loadMore"
      :disabled="isLoading"
      class="replay-checkpoint-load-more w-full min-h-11 py-1.5 text-[10px] text-slate-500 hover:text-slate-700 font-medium transition-colors disabled:opacity-50 dark:hover:text-slate-300"
    >
      {{ isLoading ? t('common.loadingState') : t('replay.loadMore') }}
    </button>
  </div>
</template>

<style scoped>
.replay-checkpoint-heading {
  padding: 0 0.45rem 0.45rem;
  letter-spacing: 0.18em;
}

.replay-checkpoint-heading::before {
  content: '';
  display: inline-block;
  width: 0.35rem;
  height: 0.35rem;
  margin-right: 0.45rem;
  border-radius: 999px;
  background: #14b8a6;
  box-shadow: 0 0 0 4px rgba(20, 184, 166, 0.1), 0 0 10px rgba(20, 184, 166, 0.3);
}

.replay-checkpoint-item {
  min-height: 2.75rem;
  border: 1px solid transparent;
}

.replay-checkpoint-item:hover {
  border-color: rgba(148, 163, 184, 0.22);
  box-shadow: 0 5px 12px rgba(15, 23, 42, 0.05);
  transform: translateX(1px);
}

.replay-checkpoint-item.bg-slate-800 {
  border-color: rgba(30, 41, 59, 0.72);
  background: linear-gradient(135deg, #1e293b, #334155);
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.16), inset 0 1px 0 rgba(255, 255, 255, 0.12);
}

.replay-checkpoint-load-more {
  margin-top: 0.25rem;
  border-top: 1px solid rgba(148, 163, 184, 0.14);
}

@media (prefers-reduced-motion: reduce) {
  .replay-checkpoint-item:hover {
    transform: none;
  }
}
</style>
