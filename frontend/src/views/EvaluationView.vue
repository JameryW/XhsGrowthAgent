<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import EvaluationRadar from '@/components/charts/EvaluationRadar.vue'
import TrendChart from '@/components/charts/TrendChart.vue'
import { getEvaluationResult, getEvaluationTrend } from '@/api/evaluation'
import type { EvaluationResultResponse, EvaluationTrendResponse } from '@/types/evaluation'

const { t } = useI18n()

const threadId = ref('')
const inputId = ref('')
const loading = ref(false)
const error = ref<string | null>(null)
const result = ref<EvaluationResultResponse | null>(null)

// ── Trend state ──
const trend = ref<EvaluationTrendResponse | null>(null)
const trendLoading = ref(false)

const trendData = computed(() =>
  (trend.value?.points || []).map((p) => ({
    date: (p.created_at || '').slice(5, 16).replace('T', ' '),
    value: p.overall_score,
  })),
)

const hasTrend = computed(() => !!trend.value && trend.value.points.length > 0)

async function loadTrend() {
  trendLoading.value = true
  try {
    trend.value = await getEvaluationTrend(undefined, 100)
  } catch {
    trend.value = { db_ready: false, points: [], dim_averages: {} }
  } finally {
    trendLoading.value = false
  }
}

onMounted(loadTrend)

async function search() {
  const id = inputId.value.trim()
  if (!id) {
    error.value = t('evaluation.error.emptyId')
    return
  }
  loading.value = true
  error.value = null
  result.value = null
  try {
    result.value = await getEvaluationResult(id)
    threadId.value = id
  } catch (e) {
    error.value = (e as Error).message || t('evaluation.error.fetch')
  } finally {
    loading.value = false
  }
}

const ev = computed(() => result.value?.evaluation_result)
const hasResult = computed(() => !!result.value && result.value.has_evaluation && ev.value)

// ponytail: color tiers by overall score threshold, mirrors backend pass/reject bands
const scoreClass = computed(() => {
  const s = ev.value?.overall_score ?? 0
  if (s >= 70) return 'score-pass'
  if (s >= 50) return 'score-warn'
  return 'score-fail'
})

const decisionClass = computed(() => {
  const d = ev.value?.decision
  if (d === 'approved') return 'decision-approved'
  if (d === 'needs_revision') return 'decision-revision'
  return 'decision-rejected'
})

const DECISION_KEYS: Record<string, string> = {
  approved: 'evaluation.decision.approved',
  needs_revision: 'evaluation.decision.needs_revision',
  rejected: 'evaluation.decision.rejected',
}

const DIMENSION_LABEL_KEYS: Record<string, string> = {
  copywriting: 'evaluation.dim.copywriting',
  visual: 'evaluation.dim.visual',
  compliance: 'evaluation.dim.compliance',
  reach: 'evaluation.dim.reach',
  audience: 'evaluation.dim.audience',
  bias_check: 'evaluation.dim.bias_check',
}

function dimLabel(dim: string): string {
  return t(DIMENSION_LABEL_KEYS[dim] ?? 'evaluation.dim.unknown', { dim })
}
</script>

<template>
  <div class="evaluation-view page-container">
    <header class="page-header">
      <h1 class="page-title">{{ t('evaluation.title') }}</h1>
      <p class="page-subtitle">{{ t('evaluation.subtitle') }}</p>
    </header>

    <!-- 查询栏 -->
    <section class="search-bar">
      <input
        v-model="inputId"
        class="thread-input"
        :placeholder="t('evaluation.inputPlaceholder')"
        @keyup.enter="search"
      />
      <button class="search-btn" :disabled="loading" @click="search">
        <AppIcon v-if="loading" name="Loader2" class="spin" />
        <AppIcon v-else name="Search" />
        <span>{{ loading ? t('evaluation.searching') : t('evaluation.search') }}</span>
      </button>
    </section>

    <!-- 错误 -->
    <div v-if="error" class="error-card">
      <AppIcon name="AlertCircle" />
      <span>{{ error }}</span>
    </div>

    <!-- 评估历史趋势 -->
    <section class="trend-card">
      <h3 class="card-title">{{ t('evaluation.trend.title') }}</h3>
      <div v-if="trendLoading" class="trend-loading">{{ t('evaluation.trend.loading') }}</div>
      <template v-else-if="hasTrend">
        <TrendChart :data="trendData" :height="260" />
        <div v-if="trend?.dim_averages && Object.keys(trend.dim_averages).length" class="dim-averages">
          <span class="dim-avg-label">{{ t('evaluation.trend.dimAverages') }}</span>
          <span
            v-for="(v, k) in trend.dim_averages"
            :key="k"
            class="dim-avg-chip"
            :class="v >= 70 ? 'score-pass' : v >= 50 ? 'score-warn' : 'score-fail'"
          >
            {{ k }}: {{ v.toFixed(1) }}
          </span>
        </div>
      </template>
      <div v-else class="trend-empty">{{ t('evaluation.trend.empty') }}</div>
    </section>

    <!-- 空状态：无评估结果 -->
    <div v-if="hasResult === false && result" class="empty-state">
      <AppIcon name="HelpCircle" size="xl" />
      <div class="empty-title">{{ t('evaluation.empty.title') }}</div>
      <div class="empty-desc">{{ t('evaluation.empty.desc') }}</div>
    </div>

    <!-- 结果展示 -->
    <div v-if="hasResult && ev" class="result-grid">
      <!-- 总分 + 决策 -->
      <section class="overview-card">
        <div class="score-block">
          <span class="score-label">{{ t('evaluation.overall') }}</span>
          <span class="score-value" :class="scoreClass">{{ ev.overall_score?.toFixed(1) }}</span>
        </div>
        <div class="decision-badge" :class="decisionClass">
          {{ t(DECISION_KEYS[ev.decision] ?? 'evaluation.decision.unknown') }}
        </div>
        <p v-if="ev.summary" class="summary">{{ ev.summary }}</p>
      </section>

      <!-- 雷达图 -->
      <section class="radar-card">
        <h3 class="card-title">{{ t('evaluation.radarTitle') }}</h3>
        <EvaluationRadar :dimensions="ev.dimensions || []" />
      </section>

      <!-- 偏倚告警 -->
      <section v-if="ev.bias_warning" class="bias-card">
        <div class="bias-header">
          <AppIcon name="AlertTriangle" />
          <span>{{ t('evaluation.bias.title') }}</span>
        </div>
        <p class="bias-text">{{ ev.bias_warning }}</p>
      </section>

      <!-- 维度详情 -->
      <section class="dims-card">
        <h3 class="card-title">{{ t('evaluation.dimensionsTitle') }}</h3>
        <div v-for="d in ev.dimensions || []" :key="d.dimension" class="dim-row">
          <div class="dim-head">
            <span class="dim-name">
              {{ dimLabel(d.dimension) }}
              <span v-if="d.is_blocking" class="blocking-tag">{{ t('evaluation.blocking') }}</span>
            </span>
            <span class="dim-score" :class="d.score >= 70 ? 'score-pass' : d.score >= 50 ? 'score-warn' : 'score-fail'">
              {{ d.score?.toFixed(1) }}
            </span>
          </div>
          <p v-if="d.rationale" class="dim-rationale">{{ d.rationale }}</p>
          <ul v-if="d.issues?.length" class="dim-issues">
            <li v-for="(issue, i) in d.issues" :key="i">{{ issue }}</li>
          </ul>
        </div>
      </section>

      <!-- 修订建议 -->
      <section v-if="ev.revision_hints?.length" class="hints-card">
        <h3 class="card-title">{{ t('evaluation.hintsTitle') }}</h3>
        <ul class="hints-list">
          <li v-for="(h, i) in ev.revision_hints" :key="i">{{ h }}</li>
        </ul>
      </section>
    </div>

    <!-- 初始空（未查询） -->
    <div v-if="!result && !error && !loading" class="initial-hint">
      <AppIcon name="Search" size="xl" />
      <p>{{ t('evaluation.initialHint') }}</p>
    </div>
  </div>
</template>

<style scoped>
.evaluation-view {
  max-width: 1100px;
  margin: 0 auto;
  padding: 1.5rem;
}
.page-header { margin-bottom: 1.5rem; }
.page-title { font-size: 1.5rem; font-weight: 700; color: #1e293b; margin: 0; }
.page-subtitle { font-size: 0.875rem; color: #64748b; margin: 0.25rem 0 0; }

.search-bar { display: flex; gap: 0.75rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
.thread-input {
  flex: 1; min-width: 240px; padding: 0.625rem 0.875rem;
  border: 1px solid #e2e8f0; border-radius: 0.5rem; font-size: 0.875rem;
  background: #fff;
}
.thread-input:focus { outline: none; border-color: #F43F5E; box-shadow: 0 0 0 3px rgba(244,63,94,0.12); }
.search-btn {
  display: inline-flex; align-items: center; gap: 0.5rem;
  padding: 0.625rem 1.25rem; border: none; border-radius: 0.5rem;
  background: #F43F5E; color: #fff; font-size: 0.875rem; font-weight: 600;
  cursor: pointer; transition: background 0.15s;
}
.search-btn:hover:not(:disabled) { background: #e11d48; }
.search-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.error-card {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.875rem 1rem; background: #fef2f2; border: 1px solid #fecaca;
  border-radius: 0.5rem; color: #b91c1c; font-size: 0.875rem; margin-bottom: 1rem;
}
.empty-state, .initial-hint {
  display: flex; flex-direction: column; align-items: center; gap: 0.75rem;
  padding: 3rem 1rem; text-align: center; color: #94a3b8;
}
.empty-title { font-size: 1rem; font-weight: 600; color: #475569; }
.empty-desc { font-size: 0.8125rem; max-width: 420px; }

.result-grid { display: grid; gap: 1rem; grid-template-columns: 1fr; }
@media (min-width: 768px) { .result-grid { grid-template-columns: 1fr 1fr; } }
.overview-card, .radar-card, .bias-card, .dims-card, .hints-card {
  background: #fff; border: 1px solid #e2e8f0; border-radius: 0.75rem; padding: 1.25rem;
}
.overview-card { display: flex; flex-direction: column; gap: 0.75rem; align-items: flex-start; }
.score-block { display: flex; align-items: baseline; gap: 0.5rem; }
.score-label { font-size: 0.8125rem; color: #64748b; }
.score-value { font-size: 2.5rem; font-weight: 800; line-height: 1; }
.score-pass { color: #16a34a; }
.score-warn { color: #d97706; }
.score-fail { color: #dc2626; }
.decision-badge { padding: 0.25rem 0.75rem; border-radius: 999px; font-size: 0.75rem; font-weight: 600; }
.decision-approved { background: #dcfce7; color: #15803d; }
.decision-revision { background: #fef3c7; color: #b45309; }
.decision-rejected { background: #fee2e2; color: #b91c1c; }
.summary { font-size: 0.8125rem; color: #475569; margin: 0; }

.card-title { font-size: 0.9rem; font-weight: 600; color: #1e293b; margin: 0 0 0.75rem; }
.bias-card { border-color: #fde68a; background: #fffbeb; }
.bias-header { display: flex; align-items: center; gap: 0.5rem; color: #b45309; font-weight: 600; font-size: 0.875rem; margin-bottom: 0.5rem; }
.bias-text { font-size: 0.8125rem; color: #92400e; margin: 0; }

.dim-row { padding: 0.625rem 0; border-bottom: 1px solid #f1f5f9; }
.dim-row:last-child { border-bottom: none; }
.dim-head { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
.dim-name { font-size: 0.8125rem; font-weight: 600; color: #334155; display: inline-flex; align-items: center; gap: 0.5rem; }
.blocking-tag { font-size: 0.625rem; padding: 0.1rem 0.4rem; background: #fee2e2; color: #b91c1c; border-radius: 4px; font-weight: 700; }
.dim-score { font-size: 0.9rem; font-weight: 700; }
.dim-rationale { font-size: 0.75rem; color: #64748b; margin: 0.25rem 0 0; }
.dim-issues { margin: 0.375rem 0 0; padding-left: 1.1rem; }
.dim-issues li { font-size: 0.75rem; color: #475569; margin-bottom: 0.2rem; }

.hints-list { margin: 0; padding-left: 1.1rem; }
.hints-list li { font-size: 0.8125rem; color: #334155; margin-bottom: 0.4rem; line-height: 1.5; }

.radar-card { grid-column: 1 / -1; }
@media (min-width: 768px) { .radar-card { grid-column: auto; } }

.trend-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 0.75rem; padding: 1.25rem; margin-bottom: 1rem; }
.trend-loading, .trend-empty { font-size: 0.8125rem; color: #94a3b8; padding: 1.5rem 0; text-align: center; }
.dim-averages { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-top: 0.75rem; }
.dim-avg-label { font-size: 0.75rem; color: #64748b; }
.dim-avg-chip { font-size: 0.7rem; padding: 0.2rem 0.55rem; border-radius: 999px; font-weight: 600; background: #f1f5f9; color: #334155; }
.dim-avg-chip.score-pass { background: #dcfce7; color: #15803d; }
.dim-avg-chip.score-warn { background: #fef3c7; color: #b45309; }
.dim-avg-chip.score-fail { background: #fee2e2; color: #b91c1c; }
</style>
