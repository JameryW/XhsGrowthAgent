<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import RipplePanel from '@/components/RipplePanel.vue'
import { useWorkflowStore } from '@/stores'

const { t } = useI18n()
const workflowStore = useWorkflowStore()

// Phase order for status lookup
const phaseOrder = ['scouting', 'planning', 'creating', 'reviewing', 'publishing', 'analyzing', 'engaging', 'completed'] as const

const getNodeStatus = (phase: string) => {
  const currentPhase = workflowStore.currentPhase
  const currentIndex = phaseOrder.indexOf(currentPhase as any)
  const nodeIndex = phaseOrder.indexOf(phase as any)
  if (nodeIndex < currentIndex) return 'completed'
  if (nodeIndex === currentIndex) return 'running'
  return 'pending'
}

const isIdle = computed(() => workflowStore.currentPhase === 'idle')

// Data accessors
const trendData = computed(() => workflowStore.trendData)
const contentPlan = computed(() => workflowStore.contentPlan)
const copyContent = computed(() => workflowStore.copyContent)
const publishResult = computed(() => (workflowStore.workflowState as any)?.publish_result || {})
const analytics = computed(() => (workflowStore.workflowState as any)?.analytics || {})

// Ripple data
const ripplePrediction = computed(() => workflowStore.ripplePrediction)
const ripplePmf = computed(() => workflowStore.ripplePmf)
const rippleComparison = computed(() => workflowStore.rippleComparison)
const rippleReason = computed(() => workflowStore.rippleReason)
const rippleProgress = computed(() => workflowStore.rippleProgress)

// Check if specific data exists
const hasTrendData = computed(() => Object.keys(trendData.value).length > 0)
const hasContentPlan = computed(() => Object.keys(contentPlan.value).length > 0)
const hasCopyContent = computed(() => Object.keys(copyContent.value).length > 0)
const hasPublishResult = computed(() => Object.keys(publishResult.value).length > 0)
const hasAnalytics = computed(() => Object.keys(analytics.value).length > 0)
const hasRipplePrediction = computed(() => Object.keys(ripplePrediction.value).length > 0)
const hasRipplePmf = computed(() => Object.keys(ripplePmf.value).length > 0)
const hasRippleComparison = computed(() => Object.keys(rippleComparison.value).length > 0)

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
  if (score === undefined) return 'bg-slate-100'
  if (score >= 80) return 'bg-rose-50'
  if (score >= 60) return 'bg-amber-50'
  return 'bg-slate-50'
}
</script>

<template>
  <!-- Empty state -->
  <div v-if="isIdle" class="text-center py-12" role="status">
    <div class="w-16 h-16 mx-auto rounded-full bg-slate-100 flex items-center justify-center mb-4">
      <AppIcon name="Rocket" size="lg" variant="cyan" />
    </div>
    <p class="text-slate-500 text-lg mb-2">{{ t('dashboard.header.idle') }}</p>
    <p class="text-slate-400 text-sm">{{ t('home.startWorkflow') }}</p>
  </div>

  <!-- Loading state with skeleton -->
  <div v-else-if="!hasTrendData && !hasContentPlan && !hasCopyContent && !hasPublishResult" class="grid grid-cols-1 lg:grid-cols-3 gap-4" role="status">
    <div v-for="i in 3" :key="i" class="rounded-xl p-5 bg-white/98 border border-slate-200/50">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-xl bg-slate-200 animate-pulse" />
        <div class="flex-1 space-y-2">
          <div class="h-4 w-24 rounded bg-slate-200 animate-pulse" />
          <div class="h-3 w-16 rounded bg-slate-100 animate-pulse" />
        </div>
      </div>
      <div class="space-y-2.5">
        <div class="h-3 w-full rounded bg-slate-100 animate-pulse" />
        <div class="h-3 w-3/4 rounded bg-slate-100 animate-pulse" />
        <div class="h-3 w-5/6 rounded bg-slate-100 animate-pulse" />
      </div>
    </div>
  </div>

  <!-- Phase-specific content -->
  <TransitionGroup v-else name="phase-card" tag="div" class="space-y-4">

    <!-- ═══ SCOUTING: Trend Data ═══ -->
    <div v-if="hasTrendData && showForPhase('scouting')" class="rounded-xl p-5 bg-white/98 border border-pink-100/50">
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
          <div v-for="(topic, idx) in trendData.hot_topics.slice(0, 5)" :key="idx" class="flex items-center gap-3 p-2.5 rounded-lg bg-slate-50 border border-slate-100">
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

    <!-- ═══ PLANNING: Content Plan + Ripple ═══ -->
    <div v-if="hasContentPlan && showForPhase('planning')" class="rounded-xl p-5 bg-white/98 border border-cyan-100/50">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-400 to-teal-400 flex items-center justify-center">
          <AppIcon name="ClipboardList" size="md" variant="white" />
        </div>
        <div>
          <div class="text-sm font-semibold text-slate-800">{{ t('dashboard.contentCards.strategyPlanning') }}</div>
          <div class="text-xs text-slate-400">{{ getNodeStatus('planning') === 'completed' ? t('common.completed') : t('dashboard.timeline.running') }}</div>
        </div>
      </div>

      <!-- Topic & Angle -->
      <div class="space-y-2 mb-4">
        <div v-if="contentPlan.selected_topic" class="flex items-start gap-2 text-sm">
          <span class="text-cyan-500 font-medium shrink-0">Topic:</span>
          <span class="text-slate-700 font-medium">{{ contentPlan.selected_topic }}</span>
        </div>
        <div v-if="contentPlan.content_angle" class="flex items-start gap-2 text-sm">
          <span class="text-cyan-500 font-medium shrink-0">Angle:</span>
          <span class="text-slate-600">{{ contentPlan.content_angle }}</span>
        </div>
        <div v-if="contentPlan.target_audience" class="flex items-start gap-2 text-sm">
          <span class="text-cyan-500 font-medium shrink-0">Audience:</span>
          <span class="text-slate-600">{{ contentPlan.target_audience }}</span>
        </div>
      </div>

      <!-- Key Points -->
      <div v-if="contentPlan.key_points && contentPlan.key_points.length > 0" class="mb-4">
        <div class="text-xs text-slate-500 uppercase tracking-wide font-medium mb-2">Key Points</div>
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
          variant="planning"
        />
      </div>
    </div>

    <!-- ═══ COPYWRITING ═══ -->
    <div v-if="hasCopyContent && showForPhase('creating')" class="rounded-xl p-5 bg-white/98 border border-violet-100/50">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-400 to-purple-400 flex items-center justify-center">
          <AppIcon name="Pencil" size="md" variant="white" />
        </div>
        <div>
          <div class="text-sm font-semibold text-slate-800">{{ t('dashboard.contentCards.copywriting') }}</div>
          <div class="text-xs text-slate-400">{{ getNodeStatus('creating') === 'completed' ? t('common.completed') : t('dashboard.timeline.running') }}</div>
        </div>
      </div>

      <!-- Title -->
      <div v-if="copyContent.selected_title" class="mb-3">
        <div class="text-sm font-semibold text-slate-800">{{ copyContent.selected_title }}</div>
      </div>

      <!-- Title candidates -->
      <div v-if="copyContent.title_candidates && copyContent.title_candidates.length > 1" class="mb-3">
        <div class="text-xs text-slate-500 mb-1.5">Title Candidates:</div>
        <div class="space-y-1">
          <div v-for="(title, idx) in copyContent.title_candidates" :key="idx" class="text-xs text-slate-600" :class="title === copyContent.selected_title ? 'font-semibold text-violet-600' : ''">
            {{ idx + 1 }}. {{ title }}
          </div>
        </div>
      </div>

      <!-- Body preview -->
      <div v-if="copyContent.body_text" class="p-3 rounded-lg bg-slate-50 border border-slate-100 mb-3">
        <p class="text-xs text-slate-600 line-clamp-4 whitespace-pre-line">{{ copyContent.body_text }}</p>
      </div>

      <!-- Hashtags -->
      <div v-if="copyContent.hashtags && copyContent.hashtags.length > 0" class="flex flex-wrap gap-1.5">
        <span v-for="(tag, idx) in copyContent.hashtags" :key="idx" class="px-2 py-1 rounded-md bg-violet-50 text-violet-600 text-xs border border-violet-100">
          #{{ tag }}
        </span>
      </div>
    </div>

    <!-- ═══ PUBLISHING: Publish Result ═══ -->
    <div v-if="hasPublishResult && showForPhase('publishing')" class="rounded-xl p-5 bg-white/98 border border-emerald-100/50">
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
            {{ publishResult.status }}
          </span>
        </div>
        <div v-if="publishResult.published_at" class="flex items-center justify-between text-sm">
          <span class="text-slate-500">{{ t('dashboard.publishResult.publishedAt') }}</span>
          <span class="text-xs text-slate-600">{{ new Date(publishResult.published_at).toLocaleString() }}</span>
        </div>
        <div v-if="publishResult.post_url" class="mt-3">
          <a :href="publishResult.post_url" target="_blank" rel="noopener" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-50 text-emerald-600 text-xs font-medium hover:bg-emerald-100 transition-colors border border-emerald-100">
            <AppIcon name="ExternalLink" size="sm" />
            {{ t('dashboard.publishResult.viewPost') }}
          </a>
        </div>
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
    <div v-else-if="hasAnalytics && showForPhase('analyzing')" class="rounded-xl p-5 bg-white/98 border border-teal-100/50">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-teal-400 to-emerald-400 flex items-center justify-center">
          <AppIcon name="BarChart3" size="md" variant="white" />
        </div>
        <div>
          <div class="text-sm font-semibold text-slate-800">Analytics</div>
        </div>
      </div>
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div v-if="analytics.views !== undefined" class="rounded-lg p-3 bg-slate-50 border border-slate-100 text-center">
          <div class="text-xs text-slate-500">Views</div>
          <div class="text-lg font-bold text-slate-700">{{ formatNum(analytics.views) }}</div>
        </div>
        <div v-if="analytics.likes !== undefined" class="rounded-lg p-3 bg-pink-50 border border-pink-100 text-center">
          <div class="text-xs text-slate-500">Likes</div>
          <div class="text-lg font-bold text-pink-600">{{ formatNum(analytics.likes) }}</div>
        </div>
        <div v-if="analytics.collects !== undefined" class="rounded-lg p-3 bg-amber-50 border border-amber-100 text-center">
          <div class="text-xs text-slate-500">Collects</div>
          <div class="text-lg font-bold text-amber-600">{{ formatNum(analytics.collects) }}</div>
        </div>
        <div v-if="analytics.engagement_rate !== undefined" class="rounded-lg p-3 bg-teal-50 border border-teal-100 text-center">
          <div class="text-xs text-slate-500">Engagement</div>
          <div class="text-lg font-bold text-teal-600">{{ (analytics.engagement_rate * 100).toFixed(1) }}%</div>
        </div>
      </div>
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
