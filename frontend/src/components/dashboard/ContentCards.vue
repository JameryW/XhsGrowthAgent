<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import RipplePanel from '@/components/RipplePanel.vue'
import { useWorkflowStore } from '@/stores'
import { triggerAnalytics } from '@/api/workflow'

const { t, locale } = useI18n()
const workflowStore = useWorkflowStore()

// Phase order for status lookup
const phaseOrder = ['scouting', 'planning', 'briefing', 'creating', 'reviewing', 'publishing', 'analyzing', 'engaging', 'completed'] as const

const getNodeStatus = (phase: string) => {
  const currentPhase = workflowStore.currentPhase
  const currentIndex = phaseOrder.indexOf(currentPhase as any)
  const nodeIndex = phaseOrder.indexOf(phase as any)
  if (nodeIndex < currentIndex) return 'completed'
  if (nodeIndex === currentIndex) {
    // Check if we're at a gate (interrupt) — gate nodes mean we're waiting, not running
    const currentAgent = (workflowStore.workflowState as any)?.current_agent || ''
    if (currentAgent.includes('_gate')) return 'completed'
    return 'running'
  }
  return 'pending'
}

const isIdle = computed(() => workflowStore.currentPhase === 'idle')

// Detect when content_strategist is actively running (for early progress display)
const isStrategyRunning = computed(() =>
  workflowStore.currentPhase === 'planning' &&
  (workflowStore.workflowState as any)?.current_agent === 'content_strategist'
)

// Data accessors — use effectiveState (replay-aware) instead of workflowState
const es = computed(() => workflowStore.effectiveState as any)

const trendData = computed(() => workflowStore.trendData)
const contentPlan = computed(() => workflowStore.contentPlan)
const copyContent = computed(() => workflowStore.copyContent)
const shootingPlan = computed(() => {
  const sp = es.value?.shooting_plan
  // shooting_plan has real data — use it
  if (sp && Object.keys(sp).length > 0) return sp
  // ponytail: fallback — synthesize from draft_content when shooting_plan is empty
  // (older workflows where shooting_planner skipped due to empty content_plan)
  const dc = es.value?.draft_content
  if (dc && (dc.title || dc.text)) {
    const sb = es.value?.selected_blogger
    return {
      creator_nickname: sb?.nickname || '',
      content_direction: es.value?.content_plan?.selected_topic || '',
      title_candidates: dc.title ? [dc.title] : [],
      body_copy: dc.text || '',
      required_hashtags: (dc.hashtags || []),
    }
  }
  return {}
})
const publishResult = computed(() => es.value?.publish_result || {})
const analytics = computed(() => es.value?.analytics || {})
const optimizationAnalysis = computed(() => es.value?.optimization_analysis || {})
const contentVersions = computed(() => es.value?.content_versions || [])
const draftContent = computed(() => es.value?.draft_content || {})

// Ripple data
const ripplePrediction = computed(() => workflowStore.ripplePrediction)
const ripplePmf = computed(() => workflowStore.ripplePmf)
const rippleComparison = computed(() => workflowStore.rippleComparison)
const rippleReason = computed(() => workflowStore.rippleReason)
const rippleProgress = computed(() => workflowStore.rippleProgress)
const isAwaitingRippleDecision = computed(() => workflowStore.isAwaitingRippleDecision)
const reselectCount = computed(() => workflowStore.reselectCount)

// Brief content accessor
const briefContent = computed(() => es.value?.brief_content || {})
const hasBriefContent = computed(() => Object.keys(briefContent.value).length > 0)
const isBriefMode = computed(() => es.value?.workflow_mode === 'brief')

// Check if specific data exists
const hasTrendData = computed(() => Object.keys(trendData.value).length > 0)
const hasContentPlan = computed(() => Object.keys(contentPlan.value).length > 0)
const hasCopyContent = computed(() => Object.keys(copyContent.value).length > 0)
const hasShootingPlan = computed(() => Object.keys(shootingPlan.value).length > 0)
const hasPublishResult = computed(() => Object.keys(publishResult.value).length > 0)
const hasAnalytics = computed(() => Object.keys(analytics.value).length > 0)
const hasOptimizationAnalysis = computed(() => {
  const oa = optimizationAnalysis.value
  return (oa.gaps?.length > 0) || (oa.suggestions?.length > 0) || (oa.viral_patterns?.length > 0)
})
const hasContentVersions = computed(() => contentVersions.value.length > 0)
const hasRipplePrediction = computed(() => Object.keys(ripplePrediction.value).length > 0)
const hasRipplePmf = computed(() => Object.keys(ripplePmf.value).length > 0)
const hasRippleComparison = computed(() => Object.keys(rippleComparison.value).length > 0)

// Whether any content card data exists (including brief mode)
const hasAnyContent = computed(() =>
  hasTrendData.value || hasContentPlan.value || hasCopyContent.value ||
  hasShootingPlan.value || hasPublishResult.value || hasBriefContent.value
)

// Show a section only when its phase is active or completed
function showForPhase(phase: string): boolean {
  const current = workflowStore.currentPhase
  const ci = phaseOrder.indexOf(current as any)
  const pi = phaseOrder.indexOf(phase as any)
  return pi <= ci
}

// Format number with K/M suffix
function formatNum(n?: number): string {
  if (n === undefined || n === null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString()
}

// Heat score color
function heatColor(score?: number): string {
  if (score === undefined) return 'text-slate-400'
  if (score >= 80) return 'text-rose-600'
  if (score >= 60) return 'text-amber-600'
  return 'text-slate-600'
}

// Heat score bg
function heatBg(score?: number): string {
  if (score === undefined) return 'bg-slate-100 dark:bg-slate-800'
  if (score >= 80) return 'bg-rose-50'
  if (score >= 60) return 'bg-amber-50'
  return 'bg-slate-50 dark:bg-slate-800/70'
}

// Trigger analyst node manually after publish
async function handleTriggerAnalytics() {
  const threadId = workflowStore.currentThreadId
  if (!threadId) return
  try {
    await triggerAnalytics(threadId)
  } catch (e: any) {
    console.error('Failed to trigger analytics:', e)
  }
}

// Raw enums never render directly — map through i18n with a raw-value
// fallback for values the backend adds later.
function severityLabel(severity?: string): string {
  if (!severity) return '—'
  const key = `dashboard.contentCards.severity.${severity}`
  const translated = t(key)
  return translated === key ? severity : translated
}

function publishStatusLabel(status?: string): string {
  if (!status) return '—'
  const key = `dashboard.publishResult.statusValues.${status}`
  const translated = t(key)
  return translated === key ? status : translated
}
</script>

<template>
  <!-- Empty state -->
  <div v-if="isIdle" class="text-center py-12" role="status">
    <div class="w-16 h-16 mx-auto rounded-full bg-slate-100 flex items-center justify-center mb-4 dark:bg-slate-800">
      <AppIcon name="Rocket" size="lg" variant="cyan" />
    </div>
    <p class="text-slate-500 text-lg mb-2">{{ t('dashboard.header.idle') }}</p>
    <p class="text-slate-400 text-sm">{{ t('home.startWorkflow') }}</p>
  </div>

  <!-- Loading state with skeleton -->
  <div v-else-if="!hasAnyContent" class="grid grid-cols-1 lg:grid-cols-3 gap-4" role="status">
    <div v-for="i in 3" :key="i" class="rounded-xl p-3 md:p-5 bg-white/90 border border-slate-200/50 dark:bg-slate-900/90 dark:border-slate-700/55">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-xl bg-slate-200 animate-pulse" />
        <div class="flex-1 space-y-2">
          <div class="h-4 w-24 rounded bg-slate-200 animate-pulse" />
          <div class="h-3 w-16 rounded bg-slate-100 animate-pulse dark:bg-slate-700" />
        </div>
      </div>
      <div class="space-y-2.5">
        <div class="h-3 w-full rounded bg-slate-100 animate-pulse dark:bg-slate-700" />
        <div class="h-3 w-3/4 rounded bg-slate-100 animate-pulse dark:bg-slate-700" />
        <div class="h-3 w-5/6 rounded bg-slate-100 animate-pulse dark:bg-slate-700" />
      </div>
    </div>
  </div>

  <!-- Phase-specific content -->
  <TransitionGroup v-else name="phase-card" tag="div" class="space-y-4">

    <!-- ═══ BRIEF MODE: Brief Content ═══ -->
    <div v-if="hasBriefContent && isBriefMode" class="rounded-xl p-3 md:p-5 bg-white/90 border border-pink-100/50 dark:bg-slate-900/90 dark:border-rose-500/25">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-pink-400 to-rose-400 flex items-center justify-center">
          <AppIcon name="FileText" size="md" variant="white" />
        </div>
        <div>
          <div class="text-base font-bold text-slate-900">{{ t('brief.contentTitle') }}</div>
          <div class="text-xs text-slate-400">{{ briefContent.brand_name || '' }}</div>
        </div>
        <span v-if="briefContent.confidence != null" class="ml-auto text-[10px] px-1.5 py-0.5 rounded-full"
          :class="briefContent.confidence >= 0.6 ? 'bg-teal-50 text-teal-600' : 'bg-amber-50 text-amber-600'">
          {{ Math.round(briefContent.confidence * 100) }}%
        </span>
      </div>

      <div class="space-y-2">
        <div v-if="briefContent.product_name" class="flex items-start gap-2">
          <span class="text-pink-500 font-medium shrink-0 text-xs mt-0.5">{{ t('brief.product') }}</span>
          <span class="text-sm font-semibold text-slate-700">{{ briefContent.product_name }}</span>
        </div>
        <div v-if="briefContent.content_direction" class="flex items-start gap-2">
          <span class="text-pink-500 font-medium shrink-0 text-xs mt-0.5">{{ t('brief.direction') }}</span>
          <span class="text-sm font-semibold text-slate-600">{{ briefContent.content_direction }}</span>
        </div>
        <div v-if="briefContent.target_audience" class="flex items-start gap-2 text-sm">
          <span class="text-pink-500 font-medium shrink-0">{{ t('brief.targetAudience') }}</span>
          <span class="text-slate-600">{{ briefContent.target_audience }}</span>
        </div>
        <div v-if="briefContent.selling_points?.length" class="mt-2">
          <div class="text-xs text-slate-500 uppercase tracking-wide font-medium mb-1.5">{{ t('brief.sellingPoints') }}</div>
          <div class="flex flex-wrap gap-1">
            <span v-for="sp in briefContent.selling_points" :key="sp" class="text-[11px] px-1.5 py-0.5 rounded bg-pink-50 text-pink-600">{{ sp }}</span>
          </div>
        </div>
        <div v-if="briefContent.required_keywords?.length" class="mt-2">
          <div class="flex flex-wrap gap-1">
            <span v-for="kw in briefContent.required_keywords" :key="kw" class="text-[11px] px-1.5 py-0.5 rounded bg-rose-50 text-rose-600 border border-rose-100 font-medium">{{ kw }}</span>
          </div>
        </div>
        <div v-if="briefContent.required_hashtags?.length || briefContent.optional_hashtags?.length" class="flex flex-wrap gap-1.5 mt-2">
          <span v-for="tag in (briefContent.required_hashtags || [])" :key="'r-'+tag" class="px-2 py-1 rounded-md bg-rose-50 text-rose-600 text-xs border border-rose-200 font-medium">#{{ tag }}</span>
          <span v-for="tag in (briefContent.optional_hashtags || [])" :key="'o-'+tag" class="px-2 py-1 rounded-md bg-slate-50 text-slate-500 text-xs border border-slate-200 dark:bg-slate-800/70 dark:border-slate-600 dark:text-slate-400">#{{ tag }}</span>
        </div>
      </div>
    </div>

    <!-- ═══ SCOUTING: Trend Data ═══ -->
    <div v-if="hasTrendData && showForPhase('scouting')" class="rounded-xl p-3 md:p-5 bg-white/90 border border-pink-100/50 dark:bg-slate-900/90 dark:border-rose-500/25">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-pink-400 to-rose-400 flex items-center justify-center">
          <AppIcon name="Search" size="md" variant="white" />
        </div>
        <div>
          <div class="text-sm font-semibold text-slate-800">{{ t('dashboard.contentCards.trendScouting') }}</div>
          <div class="text-xs text-slate-400">{{ getNodeStatus('scouting') === 'completed' ? t('common.completed') : t('dashboard.timeline.running') }}</div>
        </div>
      </div>

      <!-- Hot Topics with heat visualization -->
      <div v-if="trendData.hot_topics && trendData.hot_topics.length > 0" class="mb-4">
        <div class="text-xs text-slate-500 uppercase tracking-wide font-medium mb-2">{{ t('dashboard.scouting.hotTopics') }}</div>
        <div class="space-y-2">
          <div v-for="(topic, idx) in trendData.hot_topics.slice(0, 5)" :key="idx" class="flex items-center gap-3 p-2.5 rounded-lg bg-slate-50 border border-slate-100 dark:bg-slate-800/70 dark:border-slate-700/50">
            <span class="text-sm font-medium text-slate-700 flex-1 truncate">{{ topic.topic }}</span>
            <div class="flex items-center gap-2">
              <div :class="['px-2 py-0.5 rounded text-xs font-medium', heatBg(topic.heat_score), heatColor(topic.heat_score)]">
                {{ t('dashboard.scouting.heatScore') }} {{ topic.heat_score?.toFixed(0) || '—' }}
              </div>
              <div v-if="topic.growth_rate != null && !isNaN(topic.growth_rate)" class="text-xs" :class="topic.growth_rate > 0 ? 'text-emerald-600' : 'text-rose-600'">
                {{ topic.growth_rate > 0 ? '+' : '' }}{{ (topic.growth_rate * 100).toFixed(0) }}%
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Trending Keywords -->
      <div v-if="trendData.trending_keywords && trendData.trending_keywords.length > 0" class="mb-4">
        <div class="text-xs text-slate-500 uppercase tracking-wide font-medium mb-2">{{ t('dashboard.scouting.trendingKeywords') }}</div>
        <div class="flex flex-wrap gap-1.5">
          <span v-for="(kw, idx) in trendData.trending_keywords.slice(0, 10)" :key="idx" class="px-2 py-1 rounded-md bg-pink-50 text-pink-600 text-xs border border-pink-100">
            {{ kw }}
          </span>
        </div>
      </div>

      <!-- Niche Opportunities -->
      <div v-if="trendData.niche_opportunities && trendData.niche_opportunities.length > 0">
        <div class="text-xs text-slate-500 uppercase tracking-wide font-medium mb-2">{{ t('dashboard.scouting.nicheOpportunities') }}</div>
        <div class="space-y-1.5">
          <div v-for="(opp, idx) in trendData.niche_opportunities.slice(0, 3)" :key="idx" class="flex items-center justify-between p-2 rounded-lg bg-violet-50 border border-violet-100">
            <span class="text-sm text-slate-700">{{ opp.topic }}</span>
            <div class="flex items-center gap-2 text-xs">
              <span class="text-violet-600 font-medium">{{ t('dashboard.scouting.potentialScore') }} {{ opp.potential_score != null && !isNaN(opp.potential_score) ? opp.potential_score.toFixed(0) : '—' }}</span>
              <span class="text-slate-400">{{ opp.entry_barrier }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ PLANNING: Ripple Progress (shown while simulating, before content_plan arrives) ═══ -->
    <div v-if="isStrategyRunning && !hasContentPlan" class="rounded-xl p-3 md:p-5 bg-white/90 border border-cyan-100/50 dark:bg-slate-900/90 dark:border-cyan-500/25">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-400 to-teal-400 flex items-center justify-center">
          <AppIcon name="ClipboardList" size="md" variant="white" />
        </div>
        <div>
          <div class="text-sm font-semibold text-slate-800">{{ t('dashboard.contentCards.strategyPlanning') }}</div>
          <div class="text-xs text-slate-400">{{ t('dashboard.timeline.running') }}</div>
        </div>
      </div>
      <RipplePanel
        :progress="rippleProgress"
        :awaiting-decision="isAwaitingRippleDecision"
        :reselect-count="reselectCount"
        :max-reselect="2"
        :loading="isStrategyRunning && !rippleProgress"
        variant="planning"
      />
    </div>

    <!-- ═══ PLANNING: Content Plan + Ripple ═══ -->
    <div v-if="hasContentPlan && showForPhase('planning')" class="rounded-xl p-3 md:p-5 bg-white/90 border border-cyan-100/50 dark:bg-slate-900/90 dark:border-cyan-500/25">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-400 to-teal-400 flex items-center justify-center">
          <AppIcon name="ClipboardList" size="md" variant="white" />
        </div>
        <div>
          <div class="text-sm font-semibold text-slate-800">{{ t('dashboard.contentCards.strategyPlanning') }}</div>
          <div class="text-xs text-slate-400">{{ getNodeStatus('planning') === 'completed' ? t('common.completed') : t('dashboard.timeline.running') }}</div>
        </div>
      </div>

      <!-- Topic & Angle — L1/L2 hierarchy -->
      <div class="space-y-2 mb-4">
        <div v-if="contentPlan.selected_topic" class="flex items-start gap-2">
          <span class="text-cyan-500 font-medium shrink-0 text-xs mt-0.5">{{ t('dashboard.contentCards.topic') }}</span>
          <span class="text-base font-bold text-slate-900 leading-snug">{{ contentPlan.selected_topic }}</span>
        </div>
        <div v-if="contentPlan.content_angle" class="flex items-start gap-2">
          <span class="text-cyan-500 font-medium shrink-0 text-xs mt-0.5">{{ t('dashboard.contentCards.angle') }}</span>
          <span class="text-sm font-semibold text-slate-600">{{ contentPlan.content_angle }}</span>
        </div>
        <div v-if="contentPlan.target_audience" class="flex items-start gap-2 text-sm">
          <span class="text-cyan-500 font-medium shrink-0">{{ t('dashboard.contentCards.audience') }}</span>
          <span class="text-slate-500">{{ contentPlan.target_audience }}</span>
        </div>
      </div>

      <!-- Key Points -->
      <div v-if="contentPlan.key_points && contentPlan.key_points.length > 0" class="mb-4">
        <div class="text-xs text-slate-500 uppercase tracking-wide font-medium mb-2">{{ t('dashboard.contentCards.keyPoints') }}</div>
        <div class="space-y-1">
          <div v-for="(point, idx) in contentPlan.key_points" :key="idx" class="flex items-start gap-2 text-xs">
            <span class="text-cyan-400 mt-0.5">▸</span>
            <span class="text-slate-600">{{ point }}</span>
          </div>
        </div>
      </div>

      <!-- Hashtags -->
      <div v-if="contentPlan.hashtags && contentPlan.hashtags.length > 0" class="mb-4">
        <div class="flex flex-wrap gap-1.5">
          <span v-for="(tag, idx) in contentPlan.hashtags" :key="idx" class="px-2 py-1 rounded-md bg-cyan-50 text-cyan-600 text-xs border border-cyan-100">
            #{{ tag }}
          </span>
        </div>
      </div>

      <!-- Ripple Analysis (planning phase) -->
      <div v-if="hasRipplePrediction || hasRipplePmf || rippleProgress" class="mt-4 pt-4 border-t border-slate-100">
        <RipplePanel
          :prediction="ripplePrediction"
          :pmf="ripplePmf"
          :ripple-reason="rippleReason"
          :progress="rippleProgress"
          :awaiting-decision="isAwaitingRippleDecision"
          :reselect-count="reselectCount"
          :max-reselect="2"
          variant="planning"
        />
      </div>
    </div>

    <!-- ═══ COPYWRITING ═══ -->
    <div v-if="hasCopyContent && showForPhase('creating')" class="rounded-xl p-3 md:p-5 bg-white/90 border border-violet-100/50 dark:bg-slate-900/90 dark:border-violet-500/25">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-400 to-purple-400 flex items-center justify-center">
          <AppIcon name="Pencil" size="md" variant="white" />
        </div>
        <div>
          <div class="text-sm font-semibold text-slate-800">{{ t('dashboard.contentCards.copywriting') }}</div>
          <div class="text-xs text-slate-400">{{ getNodeStatus('creating') === 'completed' ? t('common.completed') : t('dashboard.timeline.running') }}</div>
        </div>
      </div>

      <!-- Title — L1 primary -->
      <div v-if="copyContent.selected_title" class="mb-3">
        <div class="text-base font-bold text-slate-900 leading-snug">{{ copyContent.selected_title }}</div>
      </div>

      <!-- Title candidates -->
      <div v-if="copyContent.title_candidates && copyContent.title_candidates.length > 1" class="mb-3">
        <div class="text-xs text-slate-500 mb-1.5">{{ t('dashboard.contentCards.titleCandidates') }}</div>
        <div class="space-y-1">
          <div v-for="(title, idx) in copyContent.title_candidates" :key="idx" class="text-xs text-slate-600" :class="title === copyContent.selected_title ? 'font-semibold text-violet-600' : ''">
            {{ idx + 1 }}. {{ title }}
          </div>
        </div>
      </div>

      <!-- Body preview -->
      <div v-if="copyContent.body_text" class="p-3 rounded-lg bg-slate-50 border border-slate-100 dark:bg-slate-800/70 dark:border-slate-700/50 mb-3">
        <p class="text-xs text-slate-600 line-clamp-4 whitespace-pre-line">{{ copyContent.body_text }}</p>
      </div>

      <!-- Hashtags -->
      <div v-if="copyContent.hashtags && copyContent.hashtags.length > 0" class="flex flex-wrap gap-1.5 mb-3">
        <span v-for="(tag, idx) in copyContent.hashtags" :key="idx" class="px-2 py-1 rounded-md bg-violet-50 text-violet-600 text-xs border border-violet-100">
          #{{ tag }}
        </span>
      </div>

      <!-- Draft content (user-submitted draft) -->
      <div v-if="draftContent.text" class="p-3 rounded-lg bg-blue-50 border border-blue-100 mb-3">
        <div class="text-[10px] text-blue-500 font-medium mb-1">{{ t('replay.draftContent') }}</div>
        <div v-if="draftContent.title" class="text-xs font-semibold text-blue-700 mb-0.5">{{ draftContent.title }}</div>
        <div class="text-xs text-blue-600 whitespace-pre-line line-clamp-6">{{ draftContent.text }}</div>
        <div v-if="draftContent.hashtags?.length" class="flex flex-wrap gap-1 mt-1">
          <span v-for="tag in draftContent.hashtags" :key="tag" class="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-600">#{{ tag }}</span>
        </div>
      </div>

      <!-- Optimization analysis -->
      <div v-if="hasOptimizationAnalysis" class="p-3 rounded-lg bg-violet-50 border border-violet-100 mb-3">
        <div class="text-[10px] text-violet-500 font-medium mb-1.5">{{ t('replay.optimizationAnalysis') }}</div>
        <div v-if="optimizationAnalysis.gaps?.length" class="mb-2">
          <div class="text-[10px] text-violet-400 mb-0.5">{{ t('replay.gapAnalysis') }}</div>
          <div class="space-y-1">
            <div v-for="(gap, i) in optimizationAnalysis.gaps" :key="i" class="text-xs flex gap-1.5">
              <span class="shrink-0 px-1 rounded text-[10px] font-medium" :class="gap.severity === 'high' ? 'bg-red-100 text-red-600' : gap.severity === 'medium' ? 'bg-amber-100 text-amber-600' : 'bg-green-100 text-green-600'">{{ severityLabel(gap.severity) }}</span>
              <div>
                <div class="text-slate-700 font-medium">{{ gap.dimension }}</div>
                <div class="text-slate-500">{{ gap.description }}</div>
              </div>
            </div>
          </div>
        </div>
        <div v-if="optimizationAnalysis.suggestions?.length" class="mb-2">
          <div class="text-[10px] text-violet-400 mb-0.5">{{ t('replay.suggestions') }}</div>
          <div class="space-y-1">
            <div v-for="(sug, i) in optimizationAnalysis.suggestions" :key="i" class="text-xs flex gap-1.5">
              <span class="shrink-0 text-violet-400">P{{ sug.priority }}</span>
              <div>
                <div class="text-slate-700">{{ sug.action }}</div>
                <div class="text-slate-500 text-[11px]">{{ sug.reasoning }}</div>
              </div>
            </div>
          </div>
        </div>
        <div v-if="optimizationAnalysis.viral_patterns?.length">
          <div class="text-[10px] text-violet-400 mb-0.5">{{ t('replay.viralPatterns') }}</div>
          <div class="flex flex-wrap gap-1">
            <span v-for="p in optimizationAnalysis.viral_patterns" :key="p" class="text-[11px] px-1.5 py-0.5 rounded-md bg-violet-100 text-violet-600">{{ p }}</span>
          </div>
        </div>
      </div>

      <!-- Content versions (A/B/C) -->
      <div v-if="hasContentVersions">
        <div class="text-xs text-slate-400 font-medium mb-1.5 uppercase tracking-wide">{{ t('replay.contentVersions') }} ({{ contentVersions.length }})</div>
        <div class="space-y-2">
          <div v-for="(ver, i) in contentVersions" :key="ver.version_id || i" class="p-2.5 rounded-lg border" :class="ver.version_type === 'A' ? 'bg-rose-50 border-rose-100' : ver.version_type === 'B' ? 'bg-blue-50 border-blue-100' : 'bg-emerald-50 border-emerald-100'">
            <div class="flex items-center justify-between mb-1">
              <div class="flex items-center gap-1.5">
                <span class="text-[10px] font-bold px-1.5 py-0.5 rounded" :class="ver.version_type === 'A' ? 'bg-rose-200 text-rose-700' : ver.version_type === 'B' ? 'bg-blue-200 text-blue-700' : 'bg-emerald-200 text-emerald-700'">{{ t('review.versionLabel', { n: ver.version_type || (i + 1) }) }}</span>
                <span class="text-xs font-semibold" :class="ver.version_type === 'A' ? 'text-rose-700' : ver.version_type === 'B' ? 'text-blue-700' : 'text-emerald-700'">{{ ver.title }}</span>
              </div>
              <span v-if="ver.predicted_score" class="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400">{{ ver.predicted_score }}{{ t('versionCompare.scoreUnit') }}</span>
            </div>
            <div v-if="ver.body" class="text-xs text-slate-600 whitespace-pre-line line-clamp-4 mb-1">{{ ver.body }}</div>
            <div v-if="ver.changes_summary" class="text-[11px] text-slate-400 mb-1">↻ {{ ver.changes_summary }}</div>
            <div class="flex flex-wrap gap-1">
              <span v-for="tag in ver.hashtags" :key="tag" class="text-[10px] px-1 py-0.5 rounded bg-teal-50 text-teal-600">#{{ tag }}</span>
              <span v-if="ver.style_suggestion" class="text-[10px] px-1 py-0.5 rounded bg-violet-50 text-violet-600">{{ ver.style_suggestion }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ SHOOTING PLAN ═══ -->
    <div v-if="hasShootingPlan && showForPhase('creating')" class="rounded-xl p-3 md:p-5 bg-white/90 border border-amber-100/50 dark:bg-slate-900/90 dark:border-amber-500/25">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-400 to-rose-400 flex items-center justify-center">
          <AppIcon name="Camera" size="md" variant="white" />
        </div>
        <div>
          <div class="text-sm font-semibold text-slate-800">{{ t('shootingPlan.title') }}</div>
          <div class="text-xs text-slate-400">{{ shootingPlan.creator_nickname || shootingPlan.content_direction || '' }}</div>
        </div>
      </div>

      <div class="space-y-3">
        <!-- Creator & type row -->
        <div v-if="shootingPlan.creator_nickname || shootingPlan.content_type_label || shootingPlan.planned_publish_date" class="flex flex-wrap gap-2 text-xs">
          <span v-if="shootingPlan.creator_nickname" class="px-2 py-0.5 rounded-md bg-amber-50 text-amber-700 border border-amber-100">{{ shootingPlan.creator_nickname }}</span>
          <span v-if="shootingPlan.content_type_label" class="px-2 py-0.5 rounded-md bg-rose-50 text-rose-600 border border-rose-100">{{ shootingPlan.content_type_label }}</span>
          <span v-if="shootingPlan.planned_publish_date" class="px-2 py-0.5 rounded-md bg-slate-50 text-slate-500 border border-slate-100 dark:bg-slate-800/70 dark:border-slate-700/50 dark:text-slate-400">{{ shootingPlan.planned_publish_date }}</span>
        </div>

        <!-- Product spec -->
        <div v-if="shootingPlan.product_specification" class="flex items-start gap-2 text-sm">
          <span class="text-amber-500 font-medium shrink-0 text-xs mt-0.5">{{ t('shootingPlan.product') }}</span>
          <span class="text-slate-600">{{ shootingPlan.product_specification }}</span>
        </div>

        <!-- Direction -->
        <div v-if="shootingPlan.content_direction" class="flex items-start gap-2 text-sm">
          <span class="text-amber-500 font-medium shrink-0 text-xs mt-0.5">{{ t('shootingPlan.direction') }}</span>
          <span class="text-slate-600">{{ shootingPlan.content_direction }}</span>
        </div>

        <!-- Title candidates -->
        <div v-if="shootingPlan.title_candidates?.length" class="space-y-1">
          <div class="text-xs text-slate-500 uppercase tracking-wide font-medium mb-1">{{ t('shootingPlan.titleCandidates') }}</div>
          <div v-for="(title, idx) in shootingPlan.title_candidates" :key="idx" class="text-xs text-slate-700 pl-2 border-l-2 border-amber-200">
            {{ title }}
          </div>
        </div>

        <!-- Body copy -->
        <div v-if="shootingPlan.body_copy" class="p-3 rounded-lg bg-slate-50 border border-slate-100 dark:bg-slate-800/70 dark:border-slate-700/50">
          <p class="text-xs text-slate-600 line-clamp-4 whitespace-pre-line">{{ shootingPlan.body_copy }}</p>
        </div>

        <!-- Hashtags -->
        <div v-if="shootingPlan.required_hashtags?.length || shootingPlan.optional_hashtags?.length || shootingPlan.suggested_hashtags?.length" class="flex flex-wrap gap-1.5">
          <span v-for="tag in (shootingPlan.required_hashtags || [])" :key="'r-'+tag" class="px-2 py-1 rounded-md bg-rose-50 text-rose-600 text-xs border border-rose-200 font-medium">#{{ tag }}</span>
          <span v-for="tag in (shootingPlan.suggested_hashtags || [])" :key="'s-'+tag" class="px-2 py-1 rounded-md bg-amber-50 text-amber-600 text-xs border border-amber-100">#{{ tag }}</span>
          <span v-for="tag in (shootingPlan.optional_hashtags || [])" :key="'o-'+tag" class="px-2 py-1 rounded-md bg-slate-50 text-slate-500 text-xs border border-slate-200 dark:bg-slate-800/70 dark:border-slate-600 dark:text-slate-400">#{{ tag }}</span>
        </div>

        <!-- Outfits -->
        <div v-if="shootingPlan.outfits && Object.keys(shootingPlan.outfits).length > 0" class="space-y-1.5">
          <div class="text-xs text-slate-500 uppercase tracking-wide font-medium">{{ t('shootingPlan.outfits') }}</div>
          <div v-for="(items, category) in shootingPlan.outfits" :key="category" class="flex items-start gap-2 text-xs">
            <span class="text-amber-500 font-medium shrink-0">{{ category }}</span>
            <div class="flex flex-wrap gap-1">
              <span v-for="item in (items as string[])" :key="item" class="px-1.5 py-0.5 rounded bg-amber-50 text-amber-600 border border-amber-100">{{ item }}</span>
            </div>
          </div>
        </div>

        <!-- Shooting angles -->
        <div v-if="shootingPlan.shooting_angles?.length" class="space-y-1.5">
          <div class="text-xs text-slate-500 uppercase tracking-wide font-medium">{{ t('shootingPlan.shootingAngles') }}</div>
          <div v-for="(angle, idx) in shootingPlan.shooting_angles" :key="idx" class="p-2 rounded-lg bg-slate-50 border border-slate-100 dark:bg-slate-800/70 dark:border-slate-700/50">
            <div class="text-xs font-semibold text-slate-700">{{ angle.angle }}</div>
            <div class="text-[11px] text-slate-500">{{ angle.description }}</div>
            <div v-if="angle.tips" class="text-[11px] text-amber-500 mt-0.5">{{ t('shootingPlan.tip') }}: {{ angle.tips }}</div>
          </div>
        </div>

        <!-- Draft requirements & notes -->
        <div v-if="shootingPlan.draft_requirements?.length" class="space-y-1">
          <div class="text-xs text-slate-500 uppercase tracking-wide font-medium">{{ t('shootingPlan.requirements') }}</div>
          <div v-for="(req, idx) in shootingPlan.draft_requirements" :key="idx" class="text-xs text-slate-600 flex items-start gap-1.5">
            <span class="text-amber-400 mt-0.5">▸</span>
            <span>{{ req }}</span>
          </div>
        </div>
        <div v-if="shootingPlan.draft_notes?.length" class="space-y-1">
          <div v-for="(note, idx) in shootingPlan.draft_notes" :key="idx" class="text-[11px] text-slate-400 flex items-start gap-1.5">
            <span class="text-amber-300 mt-0.5">▸</span>
            <span>{{ note }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ PUBLISHING: Publish Result ═══ -->
    <div v-if="hasPublishResult && showForPhase('publishing')" class="rounded-xl p-3 md:p-5 bg-white/90 border border-emerald-100/50 dark:bg-slate-900/90 dark:border-emerald-500/25">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-400 to-teal-400 flex items-center justify-center">
          <AppIcon name="Upload" size="md" variant="white" />
        </div>
        <div>
          <div class="text-sm font-semibold text-slate-800">{{ t('dashboard.publishResult.title') }}</div>
          <div class="text-xs text-slate-400">{{ getNodeStatus('publishing') === 'completed' ? t('common.completed') : t('dashboard.timeline.running') }}</div>
        </div>
      </div>

      <div class="space-y-2">
        <div v-if="publishResult.post_id" class="flex items-center justify-between text-sm">
          <span class="text-slate-500">{{ t('dashboard.publishResult.postId') }}</span>
          <span class="font-mono text-xs text-slate-700">{{ publishResult.post_id }}</span>
        </div>
        <div v-if="publishResult.status" class="flex items-center justify-between text-sm">
          <span class="text-slate-500">{{ t('dashboard.publishResult.status') }}</span>
          <span :class="['px-2 py-0.5 rounded text-xs font-medium', publishResult.status === 'published' ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600']">
            {{ publishStatusLabel(publishResult.status) }}
          </span>
        </div>
        <div v-if="publishResult.published_at" class="flex items-center justify-between text-sm">
          <span class="text-slate-500">{{ t('dashboard.publishResult.publishedAt') }}</span>
          <span class="text-xs text-slate-600">{{ new Date(publishResult.published_at).toLocaleString(locale || undefined) }}</span>
        </div>
        <div v-if="publishResult.post_url" class="mt-3">
          <a :href="publishResult.post_url" target="_blank" rel="noopener" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-50 text-emerald-600 text-xs font-medium hover:bg-emerald-100 transition-colors border border-emerald-100">
            <AppIcon name="ExternalLink" size="sm" variant="cyan" />
            {{ t('dashboard.publishResult.viewPost') }}
          </a>
        </div>
      </div>
    </div>

    <!-- ═══ Manual analyst trigger (after publish, before analytics) ═══ -->
    <div v-if="!workflowStore.isReplayMode && hasPublishResult && !hasAnalytics && (workflowStore.currentPhase === 'completed' || workflowStore.currentPhase === 'analyzing')" class="mt-4 rounded-xl p-4 bg-gradient-to-br from-amber-50 to-orange-50 border border-amber-200/60 dark:from-amber-950/50 dark:to-orange-950/40 dark:border-amber-500/30">
      <div class="flex items-center gap-3">
        <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-400 to-orange-400 flex items-center justify-center">
          <AppIcon name="BarChart3" size="sm" variant="white" />
        </div>
        <div class="flex-1">
          <div class="text-sm font-semibold text-slate-800 dark:text-amber-100">{{ t('dashboard.contentCards.runAnalytics') || '分析传播效果' }}</div>
          <div class="text-[10px] text-slate-400">{{ t('dashboard.contentCards.runAnalyticsDesc') || '使用 Ripple 分析预测与实际数据对比' }}</div>
        </div>
        <NeonButton variant="peach" size="sm" :loading="workflowStore.currentPhase === 'analyzing'" @click="handleTriggerAnalytics">
          <AppIcon name="Play" size="xs" variant="white" />
          <span class="ml-1">{{ t('common.run') || '运行' }}</span>
        </NeonButton>
      </div>
    </div>

    <!-- ═══ ANALYZING: Ripple Comparison ═══ -->
    <div v-if="hasRippleComparison && showForPhase('analyzing')" class="mt-4">
      <RipplePanel
        :comparison="rippleComparison"
        :ripple-reason="rippleReason"
        :progress="rippleProgress"
        variant="analyzing"
      />
    </div>

    <!-- ═══ ANALYTICS summary (if no comparison but has analytics) ═══ -->
    <div v-else-if="hasAnalytics && showForPhase('analyzing')" class="rounded-xl p-3 md:p-5 bg-white/90 border border-teal-100/50 dark:bg-slate-900/90 dark:border-teal-500/25">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-teal-400 to-emerald-400 flex items-center justify-center">
          <AppIcon name="BarChart3" size="md" variant="white" />
        </div>
        <div>
          <div class="text-sm font-semibold text-slate-800">{{ t('dashboard.contentCards.analytics') }}</div>
        </div>
      </div>
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div v-if="analytics.views !== undefined" class="rounded-lg p-3 bg-slate-50 border border-slate-100 text-center dark:bg-slate-800/70 dark:border-slate-700/50">
          <div class="text-[10px] text-slate-400 uppercase tracking-wide">{{ t('dashboard.contentCards.views') }}</div>
          <div class="text-lg font-bold text-slate-700">{{ formatNum(analytics.views) }}</div>
        </div>
        <div v-if="analytics.likes !== undefined" class="rounded-lg p-3 bg-pink-50 border border-pink-100 text-center">
          <div class="text-[10px] text-slate-400 uppercase tracking-wide">{{ t('dashboard.contentCards.likes') }}</div>
          <div class="text-lg font-bold text-pink-600">{{ formatNum(analytics.likes) }}</div>
        </div>
        <div v-if="analytics.collects !== undefined" class="rounded-lg p-3 bg-amber-50 border border-amber-100 text-center">
          <div class="text-[10px] text-slate-400 uppercase tracking-wide">{{ t('dashboard.contentCards.collects') }}</div>
          <div class="text-lg font-bold text-amber-600">{{ formatNum(analytics.collects) }}</div>
        </div>
        <div v-if="analytics.engagement_rate !== undefined" class="rounded-lg p-3 bg-teal-50 border border-teal-100 text-center">
          <div class="text-[10px] text-slate-400 uppercase tracking-wide">{{ t('dashboard.contentCards.engagement') }}</div>
          <div class="text-lg font-bold text-teal-600">{{ (analytics.engagement_rate * 100).toFixed(1) }}%</div>
        </div>
      </div>
    </div>

    <!-- ═══ Ripple Retry Progress (shown at any phase when retry is running) ═══ -->
    <div v-if="rippleProgress && !isStrategyRunning && !(hasContentPlan && (hasRipplePrediction || hasRipplePmf || rippleProgress))" class="rounded-xl p-3 md:p-5 bg-white/90 border border-violet-100/50 dark:bg-slate-900/90 dark:border-violet-500/25">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-400 to-indigo-400 flex items-center justify-center">
          <AppIcon name="Zap" size="md" variant="white" />
        </div>
        <div>
          <div class="text-sm font-semibold text-slate-800">{{ t('dashboard.ripple.title') }}</div>
          <div class="text-xs text-violet-500">{{ t('dashboard.ripple.simulating') }}</div>
        </div>
      </div>
      <RipplePanel
        :prediction="ripplePrediction"
        :pmf="ripplePmf"
        :ripple-reason="rippleReason"
        :progress="rippleProgress"
        :awaiting-decision="isAwaitingRippleDecision"
        :reselect-count="reselectCount"
        :max-reselect="2"
        variant="planning"
      />
    </div>
  </TransitionGroup>
</template>

<style scoped>
.phase-card-enter-active {
  transition: all 0.4s ease-out;
}
.phase-card-leave-active {
  transition: all 0.3s ease-in;
}
.phase-card-enter-from {
  opacity: 0;
  transform: translateY(12px);
}
.phase-card-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
.phase-card-move {
  transition: transform 0.3s ease;
}
</style>
