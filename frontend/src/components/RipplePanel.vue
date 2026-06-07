<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import { retryRippleAnalysis, submitRippleDecision } from '@/api/workflow'
import { useWorkflowStore, useToastStore } from '@/stores'
import type { RipplePrediction, RipplePMFResult, RippleComparison, RippleProgress } from '@/types/workflow'

const { t } = useI18n()
const workflowStore = useWorkflowStore()
const toastStore = useToastStore()

const isRetrying = ref(false)
const isSubmittingDecision = ref(false)

interface Props {
  prediction?: RipplePrediction
  pmf?: RipplePMFResult
  comparison?: RippleComparison
  variant?: 'planning' | 'analyzing'
  rippleReason?: string
  progress?: RippleProgress | null
  awaitingDecision?: boolean
  reselectCount?: number
  maxReselect?: number
}

const props = withDefaults(defineProps<Props>(), {
  prediction: () => ({}),
  pmf: () => ({}),
  comparison: () => ({}),
  variant: 'planning',
  rippleReason: '',
  progress: null,
  awaitingDecision: false,
  reselectCount: 0,
  maxReselect: 2,
})

const showDetails = ref(false)

const hasPrediction = computed(() => Object.keys(props.prediction).length > 0)
const hasPmf = computed(() => Object.keys(props.pmf).length > 0)
const hasComparison = computed(() => Object.keys(props.comparison).length > 0)
const hasAnyData = computed(() => hasPrediction.value || hasPmf.value || hasComparison.value)
const hasProgress = computed(() => props.progress !== null && props.progress !== undefined)

// Show progress when sim is running but results haven't arrived yet
const showProgress = computed(() => hasProgress.value && !hasAnyData.value)

function relativeText(source: RipplePrediction | RipplePMFResult, key: string): string | undefined {
  const sourceRecord = source as Record<string, unknown>
  const direct = sourceRecord[key]
  if (typeof direct === 'string' && direct.trim()) return direct

  const relative = source.relative_estimate
  if (relative && typeof relative[key] === 'string' && String(relative[key]).trim()) {
    return String(relative[key])
  }
  return undefined
}

function absoluteOrRelative(value: number | undefined, relative?: string): string | undefined {
  if (value !== undefined) return formatNumber(value)
  return relative
}

const relativeReach = computed(() => relativeText(props.prediction, 'views_relative'))
const relativeEngagement = computed(() => relativeText(props.prediction, 'engagements_relative'))
const reachDisplay = computed(() => absoluteOrRelative(props.prediction.estimated_reach, relativeReach.value))
const engagementDisplay = computed(() => absoluteOrRelative(props.prediction.estimated_engagement, relativeEngagement.value))
const hasRelativePrediction = computed(() => Boolean(
  relativeReach.value ||
  relativeEngagement.value ||
  props.prediction.prediction_summary ||
  props.prediction.verdict,
))

const isFallback = computed(() => {
  if (!hasPrediction.value) return false
  const p = props.prediction
  return (
    p.viral_probability === 0 &&
    (p.estimated_reach === 0 || p.estimated_reach === undefined) &&
    p.confidence === 0 &&
    !hasRelativePrediction.value
  )
})

const isDisabled = computed(() => props.rippleReason === 'disabled')
const isUnavailable = computed(() => props.rippleReason === 'timeout' || props.rippleReason === 'unreachable')

async function retryRipple() {
  const threadId = workflowStore.activeThreadId
  if (!threadId) return
  isRetrying.value = true
  try {
    await retryRippleAnalysis(threadId)
    toastStore.success(t('dashboard.ripple.retryStarted'))
    // Refresh status after a short delay to pick up new results
    setTimeout(() => workflowStore.refreshStatus(), 3000)
  } catch (e: any) {
    toastStore.error(t('dashboard.ripple.retryFailed'), e.message)
  } finally {
    isRetrying.value = false
  }
}

// Progress display helpers
const progressPercent = computed(() => {
  if (!props.progress) return 0
  // Use progress field if available, otherwise estimate from wave count
  if (props.progress.progress > 0) return Math.round(props.progress.progress * 100)
  const total = props.progress.total_waves || 8
  if (total > 0) return Math.round((props.progress.current_wave / total) * 100)
  return 0
})

const elapsedDisplay = computed(() => {
  if (!props.progress) return ''
  const s = props.progress.elapsed_seconds
  if (s < 60) return `${Math.round(s)}s`
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  return `${m}m ${sec}s`
})

const waveDisplay = computed(() => {
  if (!props.progress) return ''
  const { current_wave, total_waves } = props.progress
  if (total_waves > 0) return `${current_wave}/${total_waves}`
  return `Wave ${current_wave}`
})

// Format large numbers
function formatNumber(n?: number): string {
  if (n === undefined || n === null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString()
}

// Viral probability color
function viralColor(prob?: number): string {
  if (prob === undefined) return 'text-slate-400'
  if (prob >= 0.7) return 'text-emerald-600'
  if (prob >= 0.4) return 'text-amber-600'
  return 'text-rose-600'
}

function viralBg(prob?: number): string {
  if (prob === undefined) return 'bg-slate-100'
  if (prob >= 0.7) return 'bg-emerald-50'
  if (prob >= 0.4) return 'bg-amber-50'
  return 'bg-rose-50'
}

// PMF score color
function pmfColor(score?: number): string {
  if (score === undefined) return 'text-slate-400'
  if (score >= 0.7) return 'text-emerald-600'
  if (score >= 0.4) return 'text-amber-600'
  return 'text-rose-600'
}

// Accuracy rating color
function accuracyColor(rating?: string): string {
  if (!rating) return 'text-slate-400'
  if (rating === '准确' || rating === 'accurate') return 'text-emerald-600'
  if (rating === '低估' || rating === 'underestimate') return 'text-amber-600'
  return 'text-rose-600'
}

// Progress bar width
function progressWidth(value?: number, max: number = 1): string {
  if (value === undefined) return '0%'
  return `${Math.min(100, (value / max) * 100)}%`
}

// Ripple decision helpers
const canReselect = computed(() => (props.reselectCount ?? 0) < (props.maxReselect ?? 2))

async function handleRippleDecision(action: 'accept' | 'reangle' | 'retopic') {
  const threadId = workflowStore.activeThreadId
  if (!threadId) return
  isSubmittingDecision.value = true
  try {
    await submitRippleDecision(threadId, action)
    const actionLabels: Record<string, string> = {
      accept: t('dashboard.ripple.accepted'),
      reangle: t('dashboard.ripple.reangling'),
      retopic: t('dashboard.ripple.retopicing'),
    }
    toastStore.success(actionLabels[action] || action)
    setTimeout(() => workflowStore.refreshStatus(), 1000)
  } catch (e: any) {
    toastStore.error(t('dashboard.ripple.decisionFailed'), e.message)
  } finally {
    isSubmittingDecision.value = false
  }
}
</script>

<template>
  <!-- Progress state — shown when sim is running but no results yet -->
  <div v-if="showProgress" class="rounded-xl bg-gradient-to-r from-violet-50/80 to-indigo-50/80 border border-violet-200/50 overflow-hidden">
    <!-- Header -->
    <div class="px-5 py-3 flex items-center gap-2.5 border-b border-violet-100/50">
      <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-indigo-500 flex items-center justify-center animate-pulse">
        <AppIcon name="Zap" size="sm" variant="white" />
      </div>
      <div>
        <span class="text-sm font-semibold text-violet-800">{{ t('dashboard.ripple.title') }}</span>
        <span class="text-xs text-violet-500 ml-2">{{ t('dashboard.ripple.simulating') }}</span>
      </div>
    </div>

    <!-- Progress content -->
    <div class="px-5 py-4 space-y-3">
      <!-- Wave progress -->
      <div class="flex items-center justify-between">
        <span class="text-sm text-slate-600">{{ t('dashboard.ripple.waveProgress') }}</span>
        <span class="text-sm font-semibold text-violet-700">{{ waveDisplay }}</span>
      </div>

      <!-- Progress bar -->
      <div class="h-2.5 rounded-full bg-violet-100 overflow-hidden">
        <div
          class="h-full rounded-full bg-gradient-to-r from-violet-400 to-indigo-400 transition-all duration-500 ease-out"
          :style="{ width: `${progressPercent}%` }"
        />
      </div>

      <!-- Bottom row: percentage + elapsed -->
      <div class="flex items-center justify-between text-xs text-slate-500">
        <span>{{ progressPercent }}%</span>
        <span>{{ t('dashboard.ripple.elapsed') }} {{ elapsedDisplay }}</span>
      </div>
    </div>
  </div>

  <!-- Results state -->
  <div v-else-if="hasAnyData" class="rounded-xl bg-gradient-to-r from-violet-50/80 to-indigo-50/80 border border-violet-200/50 overflow-hidden">
    <!-- Header -->
    <div class="px-5 py-3 flex items-center justify-between border-b border-violet-100/50">
      <div class="flex items-center gap-2.5">
        <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-indigo-500 flex items-center justify-center">
          <AppIcon name="Zap" size="sm" variant="white" />
        </div>
        <div>
          <span class="text-sm font-semibold text-violet-800">{{ t('dashboard.ripple.title') }}</span>
          <span v-if="variant === 'planning'" class="text-xs text-violet-500 ml-2">{{ t('dashboard.ripple.spreadPrediction') }}</span>
          <span v-else class="text-xs text-violet-500 ml-2">{{ t('dashboard.ripple.predictionComparison') }}</span>
        </div>
      </div>
      <button
        class="text-xs text-violet-600 hover:text-violet-800 flex items-center gap-1 px-2 py-1 rounded-md hover:bg-violet-100 transition-colors"
        @click="showDetails = !showDetails"
      >
        {{ showDetails ? t('dashboard.ripple.hideDetails') : t('dashboard.ripple.showDetails') }}
        <AppIcon :name="showDetails ? 'ChevronUp' : 'ChevronDown'" size="sm" />
      </button>
    </div>

    <!-- Fallback notice -->
    <div v-if="isFallback" :class="[
      'mx-5 mt-3 p-2.5 rounded-lg flex items-center justify-between',
      isDisabled ? 'bg-slate-50 border border-slate-200' : 'bg-amber-50 border border-amber-200'
    ]">
      <div class="flex items-center gap-2">
        <AppIcon :name="isDisabled ? 'ZapOff' : 'AlertTriangle'" size="sm" :variant="isDisabled ? 'cyan' : 'peach'" />
        <span :class="['text-xs', isDisabled ? 'text-slate-500' : 'text-amber-700']">
          {{ isDisabled ? t('dashboard.ripple.disabledNotice') : t('dashboard.ripple.fallbackNotice') }}
        </span>
      </div>
      <NeonButton v-if="!isDisabled" variant="ghost" size="sm" :loading="isRetrying" @click="retryRipple">
        <AppIcon name="RefreshCw" size="sm" variant="cyan" />
      </NeonButton>
    </div>

    <!-- Decision panel — shown when awaiting user choice after suboptimal Ripple results -->
    <div v-if="awaitingDecision && hasAnyData" class="mx-5 mt-3 p-3 rounded-lg bg-violet-50 border border-violet-200">
      <div class="text-xs text-violet-700 font-medium mb-2">{{ t('dashboard.ripple.decisionPrompt') }}</div>
      <div class="text-xs text-violet-500 mb-3">
        {{ t('dashboard.ripple.reselectInfo', { count: reselectCount, max: maxReselect }) }}
      </div>
      <div class="flex flex-col gap-2">
        <NeonButton
          variant="cyan"
          size="sm"
          :loading="isSubmittingDecision && false"
          :disabled="isSubmittingDecision"
          @click="handleRippleDecision('accept')"
          class="w-full"
        >
          <span class="inline-flex items-center gap-1.5 justify-center">
            <AppIcon name="Check" size="sm" variant="white" />
            {{ t('dashboard.ripple.accept') }}
          </span>
        </NeonButton>
        <NeonButton
          v-if="canReselect"
          variant="purple"
          size="sm"
          :loading="isSubmittingDecision"
          :disabled="isSubmittingDecision"
          @click="handleRippleDecision('reangle')"
          class="w-full"
        >
          <span class="inline-flex items-center gap-1.5 justify-center">
            <AppIcon name="RefreshCw" size="sm" variant="white" />
            {{ t('dashboard.ripple.reangle') }}
          </span>
        </NeonButton>
        <NeonButton
          v-if="canReselect"
          variant="peach"
          size="sm"
          :loading="isSubmittingDecision"
          :disabled="isSubmittingDecision"
          @click="handleRippleDecision('retopic')"
          class="w-full"
        >
          <span class="inline-flex items-center gap-1.5 justify-center">
            <AppIcon name="Search" size="sm" variant="white" />
            {{ t('dashboard.ripple.retopic') }}
          </span>
        </NeonButton>
      </div>
    </div>

    <!-- Summary cards -->
    <div class="px-5 py-4">
      <div class="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <!-- Viral Probability -->
        <div v-if="hasPrediction && prediction.viral_probability !== undefined" :class="['rounded-lg p-3 border', viralBg(prediction.viral_probability), 'border-current/10']">
          <div class="text-xs text-slate-500 mb-1">{{ t('dashboard.ripple.viralProbability') }}</div>
          <div :class="['text-2xl font-bold', viralColor(prediction.viral_probability)]">
            {{ (prediction.viral_probability * 100).toFixed(0) }}%
          </div>
          <div class="mt-1.5 h-1.5 rounded-full bg-white/60 overflow-hidden">
            <div :class="['h-full rounded-full transition-all duration-500', prediction.viral_probability >= 0.7 ? 'bg-emerald-400' : prediction.viral_probability >= 0.4 ? 'bg-amber-400' : 'bg-rose-400']" :style="{ width: progressWidth(prediction.viral_probability) }" />
          </div>
        </div>

        <!-- Estimated Reach -->
        <div v-if="hasPrediction && reachDisplay" class="rounded-lg p-3 bg-indigo-50 border border-indigo-100">
          <div class="text-xs text-slate-500 mb-1">{{ t('dashboard.ripple.estimatedReach') }}</div>
          <div class="text-2xl font-bold text-indigo-700">
            {{ reachDisplay }}
          </div>
        </div>

        <!-- PMF Score -->
        <div v-if="hasPmf && pmf.pmf_score !== undefined" class="rounded-lg p-3 bg-teal-50 border border-teal-100">
          <div class="text-xs text-slate-500 mb-1">{{ t('dashboard.ripple.pmfScore') }}</div>
          <div :class="['text-2xl font-bold', pmfColor(pmf.pmf_score)]">
            {{ (pmf.pmf_score * 100).toFixed(0) }}%
          </div>
          <div class="mt-1.5 h-1.5 rounded-full bg-white/60 overflow-hidden">
            <div :class="['h-full rounded-full transition-all duration-500', pmf.pmf_score >= 0.7 ? 'bg-teal-400' : pmf.pmf_score >= 0.4 ? 'bg-amber-400' : 'bg-rose-400']" :style="{ width: progressWidth(pmf.pmf_score) }" />
          </div>
        </div>

        <!-- Comparison: Accuracy Rating -->
        <div v-if="hasComparison && comparison.accuracy_rating" class="rounded-lg p-3 bg-amber-50 border border-amber-100">
          <div class="text-xs text-slate-500 mb-1">{{ t('dashboard.ripple.accuracyRating') }}</div>
          <div :class="['text-lg font-bold', accuracyColor(comparison.accuracy_rating)]">
            {{ comparison.accuracy_rating }}
          </div>
        </div>

        <!-- Comparison: Predicted Reach -->
        <div v-if="hasComparison && comparison.predicted_reach !== undefined" class="rounded-lg p-3 bg-sky-50 border border-sky-100">
          <div class="text-xs text-slate-500 mb-1">{{ t('dashboard.ripple.predictedReach') }}</div>
          <div class="text-lg font-bold text-sky-700">
            {{ formatNumber(comparison.predicted_reach) }}
          </div>
        </div>

        <!-- Confidence -->
        <div v-if="hasPrediction && prediction.confidence !== undefined" class="rounded-lg p-3 bg-slate-50 border border-slate-200">
          <div class="text-xs text-slate-500 mb-1">{{ t('dashboard.ripple.confidence') }}</div>
          <div class="text-lg font-bold text-slate-700">
            {{ (prediction.confidence * 100).toFixed(0) }}%
          </div>
        </div>
      </div>
    </div>

    <!-- Expandable details -->
    <div v-if="showDetails" class="px-5 pb-4 space-y-4 border-t border-violet-100/50 pt-4">
      <!-- Prediction details -->
      <div v-if="hasPrediction" class="space-y-3">
        <h4 class="text-xs font-semibold text-violet-700 uppercase tracking-wide">{{ t('dashboard.ripple.spreadPrediction') }}</h4>

        <div v-if="prediction.prediction_summary" class="p-3 rounded-lg bg-white/60 border border-violet-100">
          <div class="text-xs text-violet-700 font-medium mb-1">{{ t('dashboard.ripple.summary') }}</div>
          <p class="text-xs text-slate-600 leading-relaxed">{{ prediction.prediction_summary }}</p>
        </div>

        <div v-if="prediction.verdict" class="flex items-center justify-between text-sm">
          <span class="text-slate-500">{{ t('dashboard.ripple.marketSignal') }}</span>
          <span class="font-medium text-slate-700">{{ prediction.verdict }}</span>
        </div>

        <!-- Estimated Engagement -->
        <div v-if="engagementDisplay" class="flex items-center justify-between text-sm">
          <span class="text-slate-500">{{ t('dashboard.ripple.estimatedEngagement') }}</span>
          <span class="font-medium text-slate-700">{{ engagementDisplay }}</span>
        </div>

        <!-- Spread phases -->
        <div v-if="prediction.spread_path && prediction.spread_path.length > 0">
          <div class="text-xs text-slate-500 mb-2">{{ t('dashboard.ripple.spreadPhases') }}</div>
          <div class="space-y-1.5">
            <div v-for="(phase, idx) in prediction.spread_path" :key="idx" class="flex items-center gap-2 text-xs">
              <span class="w-5 h-5 rounded-full bg-violet-100 text-violet-600 flex items-center justify-center font-medium text-[10px]">{{ idx + 1 }}</span>
              <span class="text-slate-600">{{ typeof phase === 'object' ? (phase.phase || phase.name || JSON.stringify(phase)) : String(phase) }}</span>
            </div>
          </div>
        </div>

        <!-- Key influencers -->
        <div v-if="prediction.key_influencers && prediction.key_influencers.length > 0">
          <div class="text-xs text-slate-500 mb-2">{{ t('dashboard.ripple.keyInfluencers') }}</div>
          <div class="flex flex-wrap gap-1.5">
            <span v-for="(inf, idx) in prediction.key_influencers" :key="idx" class="px-2 py-1 rounded-md bg-violet-50 text-violet-600 text-[11px] border border-violet-100">
              {{ typeof inf === 'object' ? (inf.name || inf.handle || JSON.stringify(inf)) : String(inf) }}
            </span>
          </div>
        </div>
      </div>

      <!-- PMF details -->
      <div v-if="hasPmf" class="space-y-3">
        <h4 class="text-xs font-semibold text-teal-700 uppercase tracking-wide">{{ t('dashboard.ripple.pmfValidation') }}</h4>

        <div v-if="pmf.prediction_summary" class="p-3 rounded-lg bg-white/60 border border-teal-100">
          <div class="text-xs text-teal-700 font-medium mb-1">{{ t('dashboard.ripple.summary') }}</div>
          <p class="text-xs text-slate-600 leading-relaxed">{{ pmf.prediction_summary }}</p>
        </div>

        <div v-if="pmf.verdict" class="flex items-center justify-between text-sm">
          <span class="text-slate-500">{{ t('dashboard.ripple.marketSignal') }}</span>
          <span class="font-medium text-slate-700">{{ pmf.verdict }}</span>
        </div>

        <!-- Risk factors -->
        <div v-if="pmf.risk_factors && pmf.risk_factors.length > 0">
          <div class="text-xs text-slate-500 mb-2">{{ t('dashboard.ripple.riskFactors') }}</div>
          <div class="space-y-1">
            <div v-for="(risk, idx) in pmf.risk_factors" :key="idx" class="flex items-start gap-2 text-xs">
              <AppIcon name="AlertTriangle" size="sm" variant="pink" class="mt-0.5 flex-shrink-0" />
              <span class="text-slate-600">{{ risk }}</span>
            </div>
          </div>
        </div>

        <!-- Improvement strategies -->
        <div v-if="pmf.improvement_strategies && pmf.improvement_strategies.length > 0">
          <div class="text-xs text-slate-500 mb-2">{{ t('dashboard.ripple.improvementStrategies') }}</div>
          <div class="space-y-1">
            <div v-for="(strategy, idx) in pmf.improvement_strategies" :key="idx" class="flex items-start gap-2 text-xs">
              <AppIcon name="Lightbulb" size="sm" variant="cyan" class="mt-0.5 flex-shrink-0" />
              <span class="text-slate-600">{{ strategy }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Comparison details -->
      <div v-if="hasComparison" class="space-y-3">
        <h4 class="text-xs font-semibold text-amber-700 uppercase tracking-wide">{{ t('dashboard.ripple.predictionComparison') }}</h4>

        <div v-if="comparison.actual_engagement_rate !== undefined" class="flex items-center justify-between text-sm">
          <span class="text-slate-500">{{ t('dashboard.ripple.actualEngagementRate') }}</span>
          <span class="font-medium text-slate-700">{{ (comparison.actual_engagement_rate * 100).toFixed(1) }}%</span>
        </div>

        <div v-if="comparison.reach_deviation !== undefined" class="flex items-center justify-between text-sm">
          <span class="text-slate-500">{{ t('dashboard.ripple.reachDeviation') }}</span>
          <span :class="['font-medium', comparison.reach_deviation > 0 ? 'text-emerald-600' : 'text-rose-600']">
            {{ comparison.reach_deviation > 0 ? '+' : '' }}{{ (comparison.reach_deviation * 100).toFixed(1) }}%
          </span>
        </div>

        <div v-if="comparison.calibration_insight" class="p-3 rounded-lg bg-amber-50 border border-amber-100">
          <div class="text-xs text-amber-700 font-medium mb-1">{{ t('dashboard.ripple.calibrationInsight') }}</div>
          <p class="text-xs text-amber-600">{{ comparison.calibration_insight }}</p>
        </div>
      </div>
    </div>
  </div>

  <!-- Timeout/unavailable state -->
  <div v-if="isUnavailable" class="rounded-xl p-4 bg-amber-50 border border-amber-200 text-center">
    <AppIcon name="AlertTriangle" size="md" variant="peach" class="mb-2 mx-auto" />
    <p class="text-xs text-amber-700 font-medium">Ripple 模拟不可用</p>
    <p class="text-xs text-amber-500 mt-1">服务响应超时，传播预测已跳过</p>
    <NeonButton variant="cyan" size="sm" class="mt-3" :loading="isRetrying" @click="retryRipple">
      <span class="inline-flex items-center gap-1">
        <AppIcon name="RefreshCw" size="sm" variant="cyan" />
        {{ t('common.retry') }}
      </span>
    </NeonButton>
  </div>

  <!-- Empty state -->
  <div v-else-if="!hasAnyData && !showProgress" class="rounded-xl p-4 bg-slate-50 border border-slate-200 text-center">
    <AppIcon name="Zap" size="md" variant="purple" class="mb-2 mx-auto opacity-40" />
    <p class="text-xs text-slate-400">{{ t('dashboard.ripple.noData') }}</p>
  </div>
</template>