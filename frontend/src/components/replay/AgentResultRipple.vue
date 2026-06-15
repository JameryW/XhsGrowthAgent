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
  <!-- Ripple Prediction -->
  <div v-if="cp.ripple_prediction && Object.keys(cp.ripple_prediction).length > 0" class="p-3 rounded-lg bg-violet-50 border border-violet-100">
    <div class="text-xs text-violet-600 font-medium mb-2">Ripple {{ t('replay.prediction') }}</div>    <div class="grid grid-cols-2 sm:grid-cols-3 gap-2">
      <div v-if="cp.ripple_prediction.viral_probability != null" class="p-2 rounded liquid-glass-inset text-center">
        <div class="text-[10px] text-slate-400">{{ t('replay.viralProb') }}</div>
        <div class="text-base font-bold" :class="cp.ripple_prediction.viral_probability >= 0.7 ? 'text-emerald-600' : cp.ripple_prediction.viral_probability >= 0.4 ? 'text-amber-600' : 'text-rose-600'">
          {{ (cp.ripple_prediction.viral_probability * 100).toFixed(1) }}%
        </div>
      </div>
      <div v-if="cp.ripple_prediction.estimated_reach != null" class="p-2 rounded liquid-glass-inset text-center">
        <div class="text-[10px] text-slate-400">{{ t('replay.estReach') }}</div>
        <div class="text-base font-bold text-indigo-700">{{ formatNum(cp.ripple_prediction.estimated_reach) }}</div>
      </div>
      <div v-if="cp.ripple_prediction.estimated_engagement != null" class="p-2 rounded liquid-glass-inset text-center">
        <div class="text-[10px] text-slate-400">{{ t('replay.estEngagement') }}</div>
        <div class="text-base font-bold text-indigo-700">{{ formatNum(cp.ripple_prediction.estimated_engagement) }}</div>
      </div>
      <div v-if="cp.ripple_prediction.confidence != null" class="p-2 rounded liquid-glass-inset text-center">
        <div class="text-[10px] text-slate-400">{{ t('replay.confidence') }}</div>
        <div class="text-base font-bold text-slate-700">{{ (cp.ripple_prediction.confidence * 100).toFixed(0) }}%</div>
      </div>
      <div v-if="cp.ripple_prediction.total_waves != null" class="p-2 rounded liquid-glass-inset text-center">
        <div class="text-[10px] text-slate-400">{{ t('replay.totalWaves') }}</div>
        <div class="text-base font-bold text-slate-700">{{ cp.ripple_prediction.total_waves }}</div>
      </div>
      <div v-if="cp.ripple_prediction.phase" class="p-2 rounded liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.phase') }}</div>
        <div class="text-xs font-medium text-slate-700">{{ cp.ripple_prediction.phase }}</div>
      </div>
    </div>
    <div v-if="cp.ripple_prediction.verdict" class="mt-2 flex items-center justify-between text-xs">
      <span class="text-slate-500">{{ t('replay.verdict') }}</span>
      <span class="font-medium text-slate-700">{{ cp.ripple_prediction.verdict }}</span>
    </div>
    <div v-if="cp.ripple_prediction.prediction_summary" class="mt-1.5 p-2 rounded liquid-glass-inset text-xs text-slate-600">{{ cp.ripple_prediction.prediction_summary }}</div>
    <!-- Confidence gate -->
    <div v-if="cp.ripple_prediction.confidence_gate" class="mt-2 p-2 rounded liquid-glass-inset">
      <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('replay.confidenceGate') }}</div>
      <div class="flex items-center gap-2 text-xs">
        <span class="text-slate-500">{{ cp.ripple_prediction.confidence_gate.original_confidence }}</span>
        <span class="text-slate-300">&rarr;</span>
        <span class="font-medium" :class="cp.ripple_prediction.confidence_gate.final_confidence === 'high' ? 'text-emerald-600' : cp.ripple_prediction.confidence_gate.final_confidence === 'medium' ? 'text-amber-600' : 'text-rose-600'">{{ cp.ripple_prediction.confidence_gate.final_confidence }}</span>
        <span v-if="cp.ripple_prediction.confidence_gate.reason" class="text-slate-400 ml-1">({{ cp.ripple_prediction.confidence_gate.reason }})</span>
      </div>
    </div>
    <!-- Relative estimates -->
    <div v-if="cp.ripple_prediction.views_relative || cp.ripple_prediction.engagements_relative || cp.ripple_prediction.favorites_relative" class="mt-2 grid grid-cols-2 gap-1.5">
      <div v-if="cp.ripple_prediction.views_relative" class="p-1.5 rounded liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.views') }}</div>
        <div class="text-xs text-slate-700">{{ cp.ripple_prediction.views_relative }}</div>
      </div>
      <div v-if="cp.ripple_prediction.engagements_relative" class="p-1.5 rounded liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.engagements') }}</div>
        <div class="text-xs text-slate-700">{{ cp.ripple_prediction.engagements_relative }}</div>
      </div>
      <div v-if="cp.ripple_prediction.favorites_relative" class="p-1.5 rounded liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.favorites') }}</div>
        <div class="text-xs text-slate-700">{{ cp.ripple_prediction.favorites_relative }}</div>
      </div>
      <div v-if="cp.ripple_prediction.comments_relative" class="p-1.5 rounded liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.comments') }}</div>
        <div class="text-xs text-slate-700">{{ cp.ripple_prediction.comments_relative }}</div>
      </div>
    </div>
    <!-- Spread path -->
    <div v-if="cp.ripple_prediction.spread_path?.length" class="mt-2">
      <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('replay.spreadPhases') }}</div>
      <div class="space-y-0.5">
        <div v-for="(sp, i) in cp.ripple_prediction.spread_path" :key="i" class="text-xs text-slate-600 flex gap-1.5">
          <span class="w-4 h-4 rounded-full bg-violet-100 text-violet-600 flex items-center justify-center text-[10px] font-medium shrink-0">{{ i + 1 }}</span>
          <span>{{ typeof sp === 'object' ? (sp.phase || sp.name || JSON.stringify(sp)) : String(sp) }}</span>
        </div>
      </div>
    </div>
    <!-- Key influencers -->
    <div v-if="cp.ripple_prediction.key_influencers?.length" class="mt-2">
      <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('replay.keyInfluencers') }}</div>
      <div class="flex flex-wrap gap-1.5">
        <span v-for="(inf, i) in cp.ripple_prediction.key_influencers" :key="i" class="text-[11px] px-2 py-0.5 rounded-md bg-violet-100 text-violet-600 border border-violet-200">
          {{ typeof inf === 'object' ? (inf.name || inf.handle || JSON.stringify(inf)) : String(inf) }}
        </span>
      </div>
    </div>
  </div>

  <!-- Ripple PMF -->
  <div v-if="cp.ripple_pmf && Object.keys(cp.ripple_pmf).length > 0" class="p-3 rounded-lg bg-indigo-50 border border-indigo-100">
    <div class="text-xs text-indigo-600 font-medium mb-2">{{ t('replay.ripplePmf') }}</div>
    <div class="grid grid-cols-2 sm:grid-cols-3 gap-2">
      <div v-if="cp.ripple_pmf.pmf_score != null" class="p-2 rounded liquid-glass-inset text-center">
        <div class="text-[10px] text-slate-400">{{ t('replay.pmfScore') }}</div>
        <div class="text-base font-bold" :class="cp.ripple_pmf.pmf_score >= 0.7 ? 'text-emerald-600' : cp.ripple_pmf.pmf_score >= 0.4 ? 'text-amber-600' : 'text-rose-600'">
          {{ (cp.ripple_pmf.pmf_score * 100).toFixed(0) }}%
        </div>
      </div>
      <div v-if="cp.ripple_pmf.confidence != null" class="p-2 rounded liquid-glass-inset text-center">
        <div class="text-[10px] text-slate-400">{{ t('replay.confidence') }}</div>
        <div class="text-base font-bold text-indigo-700">{{ (cp.ripple_pmf.confidence * 100).toFixed(0) }}%</div>
      </div>
      <div v-if="cp.ripple_pmf.total_waves != null" class="p-2 rounded liquid-glass-inset text-center">
        <div class="text-[10px] text-slate-400">{{ t('replay.totalWaves') }}</div>
        <div class="text-base font-bold text-slate-700">{{ cp.ripple_pmf.total_waves }}</div>
      </div>
      <div v-if="cp.ripple_pmf.phase" class="p-2 rounded liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.phase') }}</div>
        <div class="text-xs font-medium text-slate-700">{{ cp.ripple_pmf.phase }}</div>
      </div>
      <div v-if="cp.ripple_pmf.score_source" class="p-2 rounded liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.scoreSource') }}</div>
        <div class="text-xs font-medium text-slate-700">{{ cp.ripple_pmf.score_source }}</div>
      </div>
    </div>
    <div v-if="cp.ripple_pmf.verdict" class="mt-2 flex items-center justify-between text-xs">
      <span class="text-slate-500">{{ t('replay.verdict') }}</span>
      <span class="font-medium text-slate-700">{{ cp.ripple_pmf.verdict }}</span>
    </div>
    <div v-if="cp.ripple_pmf.prediction_summary" class="mt-1.5 p-2 rounded liquid-glass-inset text-xs text-slate-600">{{ cp.ripple_pmf.prediction_summary }}</div>
    <!-- Confidence gate -->
    <div v-if="cp.ripple_pmf.confidence_gate" class="mt-2 p-2 rounded liquid-glass-inset">
      <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('replay.confidenceGate') }}</div>
      <div class="flex items-center gap-2 text-xs">
        <span class="text-slate-500">{{ cp.ripple_pmf.confidence_gate.original_confidence }}</span>
        <span class="text-slate-300">&rarr;</span>
        <span class="font-medium" :class="cp.ripple_pmf.confidence_gate.final_confidence === 'high' ? 'text-emerald-600' : cp.ripple_pmf.confidence_gate.final_confidence === 'medium' ? 'text-amber-600' : 'text-rose-600'">{{ cp.ripple_pmf.confidence_gate.final_confidence }}</span>
        <span v-if="cp.ripple_pmf.confidence_gate.reason" class="text-slate-400 ml-1">({{ cp.ripple_pmf.confidence_gate.reason }})</span>
      </div>
    </div>
    <div v-if="cp.ripple_pmf.risk_factors?.length" class="mt-2">
      <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('replay.riskFactors') }}</div>
      <div class="space-y-0.5">
        <div v-for="risk in cp.ripple_pmf.risk_factors" :key="risk" class="text-xs text-slate-500 flex gap-1.5">
          <span class="text-rose-400">&#9888;</span>
          <span>{{ risk }}</span>
        </div>
      </div>
    </div>
    <div v-if="cp.ripple_pmf.improvement_strategies?.length" class="mt-2">
      <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('replay.improvementStrategies') }}</div>
      <div class="space-y-0.5">
        <div v-for="strategy in cp.ripple_pmf.improvement_strategies" :key="strategy" class="text-xs text-slate-500 flex gap-1.5">
          <span class="text-cyan-400">&#128161;</span>
          <span>{{ strategy }}</span>
        </div>
      </div>
    </div>
  </div>

  <!-- Ripple Comparison -->
  <div v-if="cp.ripple_comparison && Object.keys(cp.ripple_comparison).length > 0" class="p-3 rounded-lg bg-amber-50 border border-amber-100">
    <div class="text-xs text-amber-600 font-medium mb-2">Ripple {{ t('replay.comparison') }}</div>
    <div class="grid grid-cols-2 gap-2">
      <div v-if="cp.ripple_comparison.predicted_reach != null" class="p-2 rounded liquid-glass-inset text-center">
        <div class="text-[10px] text-slate-400">{{ t('replay.predictedReach') }}</div>
        <div class="text-base font-bold text-sky-700">{{ formatNum(cp.ripple_comparison.predicted_reach) }}</div>
      </div>
      <div v-if="cp.ripple_comparison.actual_engagement_rate != null" class="p-2 rounded liquid-glass-inset text-center">
        <div class="text-[10px] text-slate-400">{{ t('replay.actualEngRate') }}</div>
        <div class="text-base font-bold text-slate-700">{{ (cp.ripple_comparison.actual_engagement_rate * 100).toFixed(1) }}%</div>
      </div>
      <div v-if="cp.ripple_comparison.reach_deviation != null" class="p-2 rounded liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.reachDeviation') }}</div>
        <div class="text-xs font-semibold" :class="cp.ripple_comparison.reach_deviation > 0 ? 'text-emerald-600' : 'text-rose-600'">
          {{ cp.ripple_comparison.reach_deviation > 0 ? '+' : '' }}{{ (cp.ripple_comparison.reach_deviation * 100).toFixed(1) }}%
        </div>
      </div>
      <div v-if="cp.ripple_comparison.engagement_deviation != null" class="p-2 rounded liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.engDeviation') }}</div>
        <div class="text-xs font-semibold" :class="cp.ripple_comparison.engagement_deviation > 0 ? 'text-emerald-600' : 'text-rose-600'">
          {{ cp.ripple_comparison.engagement_deviation > 0 ? '+' : '' }}{{ (cp.ripple_comparison.engagement_deviation * 100).toFixed(1) }}%
        </div>
      </div>
    </div>
    <div v-if="cp.ripple_comparison.accuracy_rating" class="mt-2 flex items-center justify-between text-xs">
      <span class="text-slate-500">{{ t('replay.accuracyRating') }}</span>
      <span class="font-medium" :class="cp.ripple_comparison.accuracy_rating === '准确' || cp.ripple_comparison.accuracy_rating === 'accurate' ? 'text-emerald-600' : 'text-amber-600'">{{ cp.ripple_comparison.accuracy_rating }}</span>
    </div>
    <div v-if="cp.ripple_comparison.calibration_insight" class="mt-1.5 p-2 rounded liquid-glass-inset text-xs text-amber-700">{{ cp.ripple_comparison.calibration_insight }}</div>
  </div>
</template>
