<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import EvaluationRadar from '@/components/charts/EvaluationRadar.vue'
import TrendChart from '@/components/charts/TrendChart.vue'
import { getEvaluationList, getEvaluationResult, getEvaluationTrend } from '@/api/evaluation'
import type {
  EvaluationListItem,
  EvaluationListResponse,
  EvaluationResultResponse,
  EvaluationTrendResponse,
} from '@/types/evaluation'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

// ── 视图模式：列表 vs 详情（由路由 param 决定）──
const detailThreadId = computed(() => (route.params.threadId as string | undefined) ?? null)
const isDetailView = computed(() => !!detailThreadId.value)

// ════════════════════════════════════════════════════════════
// 列表页状态
// ════════════════════════════════════════════════════════════
const listItems = ref<EvaluationListItem[]>([])
const listTotal = ref(0)
const listLimit = 20
const listOffset = ref(0)
const listLoading = ref(false)
const listError = ref<string | null>(null)
const searchQuery = ref('')

async function loadList(reset = false) {
  listLoading.value = true
  listError.value = null
  if (reset) {
    listOffset.value = 0
    listItems.value = []
  }
  try {
    const res: EvaluationListResponse = await getEvaluationList(
      undefined,
      listLimit,
      listOffset.value,
    )
    if (reset) {
      listItems.value = res.workflows
    } else {
      listItems.value = [...listItems.value, ...res.workflows]
    }
    listTotal.value = res.total
  } catch (e) {
    listError.value = (e as Error).message || t('evaluation.list.loadError')
  } finally {
    listLoading.value = false
  }
}

const hasMore = computed(() => listOffset.value + listItems.value.length < listTotal.value)

function loadMore() {
  listOffset.value += listLimit
  loadList(false)
}

// 前端过滤：标题 + thread_id + account_id
const filteredItems = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return listItems.value
  return listItems.value.filter((w) => {
    const title = (w.selected_title || '').toLowerCase()
    const tid = (w.thread_id || '').toLowerCase()
    const acc = (w.account_id || '').toLowerCase()
    return title.includes(q) || tid.includes(q) || acc.includes(q)
  })
})

function openDetail(threadId: string) {
  router.push({ name: 'evaluation-detail', params: { threadId } })
}

function backToList() {
  router.push({ name: 'evaluation' })
}

// 列表页首次挂载加载
onMounted(() => {
  if (!isDetailView.value) {
    loadList(true)
  }
})

// 路由切换到列表页时按需加载（从详情返回且列表为空）
watch(isDetailView, (detail) => {
  if (!detail && listItems.value.length === 0 && !listLoading.value) {
    loadList(true)
  }
})

// 列表项的 decision 徽章 class
function decisionBadgeClass(decision: string): string {
  if (decision === 'approved') return 'decision-approved'
  if (decision === 'needs_revision') return 'decision-revision'
  return 'decision-rejected'
}

const DECISION_KEYS: Record<string, string> = {
  approved: 'evaluation.decision.approved',
  needs_revision: 'evaluation.decision.needs_revision',
  rejected: 'evaluation.decision.rejected',
}

function decisionLabel(decision: string): string {
  return t(DECISION_KEYS[decision] ?? 'evaluation.decision.unknown')
}

function scoreTier(score: number): string {
  if (score >= 70) return 'score-pass'
  if (score >= 50) return 'score-warn'
  return 'score-fail'
}

function formatDateTime(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function phaseLabel(phase: string): string {
  const key = `dashboard.timeline.${phase}`
  // 兜底：未知 phase 原样返回
  return t(key) === key ? phase : t(key)
}

// ════════════════════════════════════════════════════════════
// 趋势图状态（列表页顶部展示）
// ════════════════════════════════════════════════════════════
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

// ════════════════════════════════════════════════════════════
// 详情页状态（复用原有评估结果展示逻辑）
// ════════════════════════════════════════════════════════════
const result = ref<EvaluationResultResponse | null>(null)
const detailLoading = ref(false)
const detailError = ref<string | null>(null)

const ev = computed(() => result.value?.evaluation_result)
const hasResult = computed(() => !!result.value && result.value.has_evaluation && !!ev.value)

async function loadDetail(threadId: string) {
  detailLoading.value = true
  detailError.value = null
  result.value = null
  try {
    result.value = await getEvaluationResult(threadId)
  } catch (e) {
    detailError.value = (e as Error).message || t('evaluation.error.fetch')
  } finally {
    detailLoading.value = false
  }
}

// 进入详情页 / thread_id 变化时加载
watch(
  detailThreadId,
  (tid) => {
    if (tid) loadDetail(tid)
  },
  { immediate: true },
)

const scoreClass = computed(() => {
  const s = ev.value?.overall_score ?? 0
  return scoreTier(s)
})

const detailDecisionClass = computed(() => {
  const d = ev.value?.decision
  if (d === 'approved') return 'decision-approved'
  if (d === 'needs_revision') return 'decision-revision'
  return 'decision-rejected'
})

const DETAIL_DECISION_KEYS: Record<string, string> = {
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

// 趋势图：列表页挂载时加载一次（详情页不重复加载）
onMounted(() => {
  loadTrend()
})
</script>

<template>
  <div class="evaluation-view page-container">
    <!-- ════════ 列表视图 ════════ -->
    <template v-if="!isDetailView">
      <header class="page-header">
        <h1 class="page-title">{{ t('evaluation.title') }}</h1>
        <p class="page-subtitle">{{ t('evaluation.list.subtitle') }}</p>
      </header>

      <!-- 评估历史趋势 -->
      <section class="trend-card">
        <h3 class="card-title">{{ t('evaluation.trend.title') }}</h3>
        <div v-if="trendLoading" class="trend-loading">{{ t('evaluation.trend.loading') }}</div>
        <template v-else-if="hasTrend">
          <TrendChart :data="trendData" :height="260" />
          <div
            v-if="trend?.dim_averages && Object.keys(trend.dim_averages).length"
            class="dim-averages"
          >
            <span class="dim-avg-label">{{ t('evaluation.trend.dimAverages') }}</span>
            <span
              v-for="(v, k) in trend.dim_averages"
              :key="k"
              class="dim-avg-chip"
              :class="scoreTier(v)"
            >
              {{ k }}: {{ v.toFixed(1) }}
            </span>
          </div>
        </template>
        <div v-else class="trend-empty">{{ t('evaluation.trend.empty') }}</div>
      </section>

      <!-- 搜索框 -->
      <section class="search-bar">
        <input
          v-model="searchQuery"
          class="thread-input"
          :placeholder="t('evaluation.list.searchPlaceholder')"
        />
        <span class="result-count">{{ filteredItems.length }} / {{ listTotal }}</span>
      </section>

      <!-- 加载错误 -->
      <div v-if="listError" class="error-card">
        <AppIcon name="AlertCircle" />
        <span>{{ listError }}</span>
      </div>

      <!-- 加载中（首次） -->
      <div v-if="listLoading && listItems.length === 0" class="trend-loading">
        {{ t('evaluation.list.loading') }}
      </div>

      <!-- 空列表 -->
      <div
        v-else-if="!listError && filteredItems.length === 0"
        class="empty-state"
      >
        <AppIcon name="HelpCircle" size="xl" />
        <div class="empty-title">{{ t('evaluation.list.empty') }}</div>
      </div>

      <!-- 列表 -->
      <div v-else class="eval-list">
        <div
          v-for="w in filteredItems"
          :key="w.thread_id"
          class="eval-item"
          @click="openDetail(w.thread_id)"
        >
          <div class="item-main">
            <div class="item-title">{{ w.selected_title || t('evaluation.empty.title') }}</div>
            <div class="item-meta">
              <span class="meta-tag">{{ phaseLabel(w.phase) }}</span>
              <span class="meta-sep">·</span>
              <span class="meta-account">{{ w.account_id }}</span>
              <span class="meta-sep">·</span>
              <span class="meta-time">{{ formatDateTime(w.updated_at) }}</span>
            </div>
          </div>
          <div class="item-right">
            <span class="item-score" :class="scoreTier(w.overall_score ?? 0)">
              {{ (w.overall_score ?? 0).toFixed(1) }}
            </span>
            <span class="decision-badge" :class="decisionBadgeClass(w.decision)">
              {{ decisionLabel(w.decision) }}
            </span>
          </div>
        </div>
      </div>

      <!-- 加载更多 -->
      <div v-if="hasMore" class="load-more">
        <button class="load-more-btn" :disabled="listLoading" @click="loadMore">
          <AppIcon v-if="listLoading" name="Loader2" class="spin" />
          <span>{{ t('evaluation.list.loadMore') }}</span>
        </button>
      </div>
      <div v-else-if="listItems.length > 0" class="no-more">{{ t('evaluation.list.noMore') }}</div>
    </template>

    <!-- ════════ 详情视图 ════════ -->
    <template v-else>
      <header class="page-header detail-header">
        <button class="back-btn" @click="backToList">
          <AppIcon name="ArrowLeft" />
          <span>{{ t('evaluation.list.back') }}</span>
        </button>
        <h1 class="page-title">{{ t('evaluation.list.detailTitle') }}</h1>
      </header>

      <!-- 加载中 -->
      <div v-if="detailLoading" class="trend-loading">{{ t('evaluation.searching') }}</div>

      <!-- 错误 -->
      <div v-else-if="detailError" class="error-card">
        <AppIcon name="AlertCircle" />
        <span>{{ detailError }}</span>
      </div>

      <!-- 空状态：无评估结果 -->
      <div v-else-if="hasResult === false && result" class="empty-state">
        <AppIcon name="HelpCircle" size="xl" />
        <div class="empty-title">{{ t('evaluation.empty.title') }}</div>
        <div class="empty-desc">{{ t('evaluation.empty.desc') }}</div>
      </div>

      <!-- 结果展示（复用原有结构） -->
      <div v-if="hasResult && ev" class="result-grid">
        <!-- 总分 + 决策 -->
        <section class="overview-card">
          <div class="score-block">
            <span class="score-label">{{ t('evaluation.overall') }}</span>
            <span class="score-value" :class="scoreClass">{{ ev.overall_score?.toFixed(1) }}</span>
          </div>
          <div class="decision-badge" :class="detailDecisionClass">
            {{ t(DETAIL_DECISION_KEYS[ev.decision] ?? 'evaluation.decision.unknown') }}
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
              <span
                class="dim-score"
                :class="d.score >= 70 ? 'score-pass' : d.score >= 50 ? 'score-warn' : 'score-fail'"
              >
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
    </template>
  </div>
</template>

<style scoped>
/* ponytail: 宽度/内边距交由 <main> 的 p-6，与 Analytics/Dashboard 同构——
   不自定义 max-width，避免评估页两侧留白与其它页不一致 */
.evaluation-view { }
.page-header { margin-bottom: 1.5rem; }
.page-title { font-size: 1.5rem; font-weight: 700; color: #1e293b; margin: 0; }
.page-subtitle { font-size: 0.875rem; color: #64748b; margin: 0.25rem 0 0; }

/* ── 详情页返回头 ── */
.detail-header { display: flex; align-items: center; gap: 0.75rem; }
.back-btn {
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.4rem 0.8rem; border: 1px solid #e2e8f0; border-radius: 0.5rem;
  background: #fff; color: #334155; font-size: 0.8125rem; font-weight: 600;
  cursor: pointer; transition: background 0.15s;
}
.back-btn:hover { background: #f8fafc; }

/* ── 列表页搜索栏 ── */
.search-bar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; }
.thread-input {
  flex: 1; min-width: 240px; padding: 0.625rem 0.875rem;
  border: 1px solid #e2e8f0; border-radius: 0.5rem; font-size: 0.875rem;
  background: #fff;
}
.thread-input:focus { outline: none; border-color: #F43F5E; box-shadow: 0 0 0 3px rgba(244,63,94,0.12); }
.result-count { font-size: 0.75rem; color: #94a3b8; white-space: nowrap; }

/* ── 列表项 ── */
.eval-list { display: flex; flex-direction: column; gap: 0.5rem; }
.eval-item {
  display: flex; justify-content: space-between; align-items: center; gap: 0.75rem;
  background: #fff; border: 1px solid #e2e8f0; border-radius: 0.625rem;
  padding: 0.75rem 1rem; cursor: pointer; transition: border-color 0.15s, box-shadow 0.15s;
}
.eval-item:hover { border-color: #fda4af; box-shadow: 0 1px 4px rgba(244,63,94,0.08); }
.item-main { flex: 1; min-width: 0; }
.item-title {
  font-size: 0.9rem; font-weight: 600; color: #1e293b; margin-bottom: 0.25rem;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.item-meta { font-size: 0.75rem; color: #64748b; display: flex; align-items: center; gap: 0.35rem; flex-wrap: wrap; }
.meta-tag { color: #475569; }
.meta-sep { color: #cbd5e1; }
.meta-account { font-family: monospace; }
.meta-time { color: #94a3b8; }
.item-right { display: flex; flex-direction: column; align-items: flex-end; gap: 0.35rem; flex-shrink: 0; }
.item-score { font-size: 1.25rem; font-weight: 800; line-height: 1; }

.load-more { display: flex; justify-content: center; margin-top: 1rem; }
.load-more-btn {
  display: inline-flex; align-items: center; gap: 0.5rem;
  padding: 0.5rem 1.25rem; border: 1px solid #e2e8f0; border-radius: 0.5rem;
  background: #fff; color: #334155; font-size: 0.8125rem; font-weight: 600;
  cursor: pointer; transition: background 0.15s;
}
.load-more-btn:hover:not(:disabled) { background: #f8fafc; }
.load-more-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.no-more { text-align: center; font-size: 0.75rem; color: #94a3b8; margin-top: 0.75rem; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.error-card {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.875rem 1rem; background: #fef2f2; border: 1px solid #fecaca;
  border-radius: 0.5rem; color: #b91c1c; font-size: 0.875rem; margin-bottom: 1rem;
}
.empty-state {
  display: flex; flex-direction: column; align-items: center; gap: 0.75rem;
  padding: 3rem 1rem; text-align: center; color: #94a3b8;
}
.empty-title { font-size: 1rem; font-weight: 600; color: #475569; }
.empty-desc { font-size: 0.8125rem; max-width: 420px; }

/* ── 详情结果（复用原样式）── */
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
