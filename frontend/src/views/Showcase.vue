<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import PublicReplayResult from '@/components/replay/PublicReplayResult.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { getPublicCase, listPublicCases } from '@/api/publicShowcase'
import type { PublicCase, PublicCaseStatus, PublicWorkflowMode } from '@/types/publicShowcase'
import { useAuthStore } from '@/stores/auth'
import { trackInteraction } from '@/utils/interactionTelemetry'

const { t, locale } = useI18n()
const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

type StatusFilter = 'all' | PublicCaseStatus
type ModeFilter = 'all' | PublicWorkflowMode
type SortKey = 'recent' | 'title'

const cases = ref<PublicCase[]>([])
const loading = ref(true)
const loaded = ref(false)
const loadError = ref<string | null>(null)
const retrying = ref(false)
const search = ref('')
const statusFilter = ref<StatusFilter>('all')
const modeFilter = ref<ModeFilter>('all')
const sortKey = ref<SortKey>('recent')
const detailState = ref<Record<string, 'idle' | 'loading' | 'ready' | 'error'>>({})
const detailCache = ref<Map<string, PublicCase>>(new Map())
const firstCaseTracked = ref(false)
const totalCases = ref(0)

const CACHE_VERSION = 2
const CACHE_KEY = `showcase:public-cases:v${CACHE_VERSION}`
const CACHE_TTL = 30_000
let queryReady = false
let listRequestToken = 0
let listAbortController: AbortController | null = null
const detailAbortControllers = new Map<string, AbortController>()

const isAuthenticated = computed(() => authStore.isAuthenticated)
const featuredCase = computed(() => {
  const explicit = cases.value.find(item => item.featured)
  return explicit || cases.value.find(item => item.status === 'completed') || cases.value[0] || null
})

const filteredCases = computed(() => {
  const normalizedSearch = search.value.trim().toLocaleLowerCase(locale.value)
  const result = cases.value.filter((item) => {
    if (item.public_id === featuredCase.value?.public_id) return false
    if (statusFilter.value !== 'all' && item.status !== statusFilter.value) return false
    if (modeFilter.value !== 'all' && item.workflow_mode !== modeFilter.value) return false
    if (normalizedSearch && !`${item.title} ${item.summary}`.toLocaleLowerCase(locale.value).includes(normalizedSearch)) return false
    return true
  })
  return result.sort((a, b) => {
    if (sortKey.value === 'title') return a.title.localeCompare(b.title, locale.value)
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
  })
})

const resultCount = computed(() => totalCases.value || cases.value.length)

function trackFirstCaseVisible(cached: boolean, startedAt: number) {
  if (firstCaseTracked.value || !cases.value.length) return
  firstCaseTracked.value = true
  trackInteraction('showcase_first_case_visible', {
    cached,
    duration_ms: typeof performance !== 'undefined' ? Math.round(performance.now() - startedAt) : undefined,
  })
}

function queryValue(value: unknown): string | undefined {
  if (Array.isArray(value)) return typeof value[0] === 'string' ? value[0] : undefined
  return typeof value === 'string' ? value : undefined
}

function restoreQuery() {
  const status = queryValue(route.query.status) as StatusFilter | undefined
  const mode = queryValue(route.query.mode) as ModeFilter | undefined
  const sort = queryValue(route.query.sort) as SortKey | undefined
  const q = queryValue(route.query.q)
  statusFilter.value = ['all', 'completed', 'in_progress', 'attention'].includes(status || '') ? status || 'all' : 'all'
  modeFilter.value = ['all', 'trend', 'brief'].includes(mode || '') ? mode || 'all' : 'all'
  sortKey.value = ['recent', 'title'].includes(sort || '') ? sort || 'recent' : 'recent'
  search.value = q || ''
}

function queryState() {
  const query: Record<string, string> = {}
  if (statusFilter.value !== 'all') query.status = statusFilter.value
  if (modeFilter.value !== 'all') query.mode = modeFilter.value
  if (sortKey.value !== 'recent') query.sort = sortKey.value
  if (search.value.trim()) query.q = search.value.trim()
  return query
}

watch([statusFilter, modeFilter, sortKey, search], () => {
  if (!queryReady) return
  void router.replace({ query: queryState() })
})

function readCache(): PublicCase[] | null {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(CACHE_KEY) || '') as { version?: number; savedAt?: number; cases?: PublicCase[] }
    if (parsed.version !== CACHE_VERSION || !parsed.savedAt || Date.now() - parsed.savedAt > CACHE_TTL || !Array.isArray(parsed.cases)) return null
    return parsed.cases
  } catch {
    return null
  }
}

function writeCache(nextCases: PublicCase[]) {
  try {
    sessionStorage.setItem(CACHE_KEY, JSON.stringify({ version: CACHE_VERSION, savedAt: Date.now(), cases: nextCases }))
  } catch {
    // A full/private session store must not block the public page.
  }
}

function hydrate(nextCases: PublicCase[]) {
  cases.value = nextCases
  totalCases.value = nextCases.length
  loaded.value = true
  if (nextCases[0]) void loadCaseDetail(nextCases[0].public_id)
  if (featuredCase.value) void loadCaseDetail(featuredCase.value.public_id)
}

async function loadCaseDetail(publicId: string) {
  if (detailCache.value.has(publicId) || detailState.value[publicId] === 'loading') return
  const abortController = new AbortController()
  detailAbortControllers.get(publicId)?.abort()
  detailAbortControllers.set(publicId, abortController)
  detailState.value = { ...detailState.value, [publicId]: 'loading' }
  try {
    const detail = await getPublicCase(publicId, { suppressToast: true, signal: abortController.signal })
    if (abortController.signal.aborted) return
    detailCache.value.set(publicId, detail)
    detailState.value = { ...detailState.value, [publicId]: 'ready' }
  } catch {
    if (!abortController.signal.aborted) detailState.value = { ...detailState.value, [publicId]: 'error' }
  } finally {
    if (detailAbortControllers.get(publicId) === abortController) detailAbortControllers.delete(publicId)
  }
}

async function loadCases(useCache = true) {
  listAbortController?.abort()
  const abortController = new AbortController()
  listAbortController = abortController
  const requestToken = ++listRequestToken
  const startedAt = typeof performance !== 'undefined' ? performance.now() : 0
  loading.value = true
  loadError.value = null
  if (useCache) {
    const cached = readCache()
    if (cached) {
      hydrate(cached)
      loading.value = false
      trackFirstCaseVisible(true, startedAt)
    }
  }
  try {
    const response = await listPublicCases(
      { limit: 100, sort: 'recent' },
      { suppressToast: true, signal: abortController.signal },
    )
    if (abortController.signal.aborted || requestToken !== listRequestToken) return
    cases.value = response.cases || []
    totalCases.value = response.total ?? cases.value.length
    loaded.value = true
    writeCache(cases.value)
    trackFirstCaseVisible(false, startedAt)
    if (featuredCase.value) void loadCaseDetail(featuredCase.value.public_id)
    trackInteraction('showcase_cases_loaded', { count: cases.value.length, cached: false })
  } catch (error: any) {
    if (abortController.signal.aborted || requestToken !== listRequestToken) return
    if (!loaded.value) loadError.value = error?.message || t('showcase.casesLoadFailed')
    trackInteraction('showcase_cases_error', { error_type: 'public_cases' })
  } finally {
    if (listAbortController === abortController) {
      listAbortController = null
      loading.value = false
    }
  }
}

async function retryCases() {
  retrying.value = true
  try {
    await loadCases(false)
  } finally {
    retrying.value = false
  }
}

function clearFilters() {
  search.value = ''
  statusFilter.value = 'all'
  modeFilter.value = 'all'
  sortKey.value = 'recent'
  trackInteraction('showcase_filters_clear')
}

function goCreate() {
  trackInteraction('showcase_primary_cta_click', { authenticated: isAuthenticated.value })
  if (isAuthenticated.value) {
    void router.push({ name: 'home' })
  } else {
    void router.push({ name: 'login', query: { redirect: '/start' } })
  }
}

function openReplay(publicId: string) {
  trackInteraction('showcase_case_open', { has_public_id: true })
  void router.push({ name: 'replay', params: { publicId }, query: { from: '/' } })
}

function replayHref(publicId: string): string {
  return `/replay/${encodeURIComponent(publicId)}?from=%2F`
}

function formatDate(value: string): string {
  if (!value) return ''
  return new Intl.DateTimeFormat(locale.value || undefined, { month: 'short', day: 'numeric' }).format(new Date(value))
}

function caseDetail(item: PublicCase): PublicCase {
  return detailCache.value.get(item.public_id) || item
}

function statusLabel(status: PublicCaseStatus): string {
  return t(`showcase.caseStatus.${status}`)
}

function modeLabel(mode: PublicWorkflowMode): string {
  return t(`showcase.mode.${mode}`)
}

onMounted(async () => {
  if (!authStore.isInitialized) void authStore.initialize()
  restoreQuery()
  queryReady = true
  trackInteraction('showcase_view')
  await loadCases()
})

onUnmounted(() => {
  listAbortController?.abort()
  detailAbortControllers.forEach(controller => controller.abort())
  detailAbortControllers.clear()
})
</script>

<template>
  <div class="showcase-v2 min-h-screen overflow-x-clip bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-50">
    <div class="showcase-v2-ambient" aria-hidden="true" />
    <a href="#cases" class="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-slate-900 focus:px-4 focus:py-3 focus:text-sm focus:font-semibold focus:text-white">{{ t('common.skipToContent') }}</a>
    <nav class="relative z-10 border-b border-slate-200/70 bg-white/80 backdrop-blur-xl dark:border-slate-800/70 dark:bg-slate-950/80">
      <div class="mx-auto flex min-h-16 max-w-6xl items-center justify-between gap-4 px-4 md:px-8">
        <button type="button" class="flex min-h-11 items-center gap-3 rounded-xl text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500" @click="router.push({ name: 'showcase' })">
          <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-rose-500 to-amber-400 shadow-lg shadow-rose-500/20"><AppIcon name="Rocket" size="sm" variant="white" aria-hidden="true" /></span>
          <span>
            <span class="block text-sm font-bold tracking-tight">{{ t('showcase.title') }}</span>
            <span class="hidden text-xs text-slate-500 sm:block dark:text-slate-400">{{ t('showcase.navShowcase') }}</span>
          </span>
        </button>
        <div class="flex items-center gap-2">
          <button v-if="!isAuthenticated" type="button" class="hidden min-h-11 rounded-xl px-3 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800 sm:inline-flex" @click="router.push({ name: 'login', query: { redirect: '/' } })">{{ t('showcase.signIn') }}</button>
          <button type="button" class="min-h-11 rounded-xl bg-rose-600 px-4 text-sm font-semibold text-white shadow-lg shadow-rose-600/20 hover:bg-rose-700" @click="goCreate">{{ t('showcase.startCreating') }}</button>
          <ThemeToggle class="shrink-0" />
        </div>
      </div>
    </nav>

    <main id="main-content" class="relative z-10 mx-auto max-w-6xl px-4 py-8 md:px-8 md:py-12">
      <section class="grid items-center gap-8 lg:grid-cols-[1.05fr_.95fr] lg:gap-14" aria-labelledby="showcase-title">
        <div>
          <p class="inline-flex items-center gap-2 rounded-full border border-teal-200 bg-teal-50 px-3 py-1.5 text-xs font-semibold text-teal-700 dark:border-teal-400/20 dark:bg-teal-400/10 dark:text-teal-200"><span class="h-2 w-2 rounded-full bg-teal-500" aria-hidden="true" />{{ t('showcase.heroTagline') }}</p>
          <h1 id="showcase-title" class="mt-5 max-w-2xl text-3xl font-bold leading-tight tracking-tight sm:text-4xl lg:text-5xl">{{ t('showcase.heroTitle') }}</h1>
          <p class="mt-5 max-w-xl text-base leading-7 text-slate-600 dark:text-slate-300">{{ t('showcase.heroDesc') }}</p>
          <div class="mt-6 flex flex-wrap items-center gap-3">
            <button type="button" class="inline-flex min-h-12 items-center gap-2 rounded-xl bg-slate-900 px-5 text-sm font-semibold text-white shadow-lg shadow-slate-900/15 hover:bg-slate-700 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-200" @click="goCreate">{{ t('showcase.startCreating') }}<AppIcon name="ArrowRight" size="sm" aria-hidden="true" /></button>
            <a href="#cases" class="inline-flex min-h-12 items-center rounded-xl px-4 text-sm font-medium text-slate-600 hover:bg-white dark:text-slate-300 dark:hover:bg-slate-900">{{ t('showcase.browseCases') }}</a>
          </div>
          <p class="mt-4 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400"><AppIcon name="CheckCircle" size="xs" variant="cyan" aria-hidden="true" />{{ t('showcase.heroProof') }}</p>
        </div>

        <div class="rounded-3xl border border-slate-200/80 bg-white/80 p-5 shadow-xl shadow-slate-900/5 dark:border-slate-800 dark:bg-slate-900/80 md:p-6">
          <div class="flex items-center justify-between gap-4">
            <div>
              <p class="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">{{ t('showcase.resultEvidence') }}</p>
              <p class="mt-2 text-xl font-semibold">{{ t('showcase.evidenceTitle') }}</p>
            </div>
            <AppIcon name="Sparkles" size="lg" variant="cyan" aria-hidden="true" />
          </div>
          <div class="mt-6 space-y-3">
            <div v-for="(step, index) in ['scouting', 'planning', 'creating', 'publishing']" :key="step" class="flex items-center gap-3 rounded-xl border border-slate-200/70 p-3 dark:border-slate-800">
              <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-sm font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">{{ index + 1 }}</span>
              <span class="text-sm font-medium">{{ t(`showcase.phase.${step}`) }}</span>
              <AppIcon name="Check" size="xs" variant="cyan" class="ml-auto" aria-hidden="true" />
            </div>
          </div>
          <p class="mt-5 text-sm leading-6 text-slate-500 dark:text-slate-400">{{ t('showcase.evidenceDesc') }}</p>
        </div>
      </section>

      <section v-if="featuredCase" class="mt-10" aria-labelledby="featured-heading">
        <div class="overflow-hidden rounded-3xl border border-rose-200/70 bg-white shadow-xl shadow-rose-900/5 dark:border-rose-400/20 dark:bg-slate-900">
          <div class="grid lg:grid-cols-[.82fr_1.18fr]">
            <div class="bg-gradient-to-br from-rose-500 via-orange-400 to-amber-300 p-6 text-white md:p-8">
              <p class="text-xs font-semibold uppercase tracking-[0.14em] text-white/75">{{ t('showcase.featuredLabel') }}</p>
              <h2 id="featured-heading" class="mt-4 text-2xl font-bold leading-tight md:text-3xl">{{ caseDetail(featuredCase).title }}</h2>
              <p class="mt-3 text-sm leading-6 text-white/85">{{ caseDetail(featuredCase).summary }}</p>
              <div class="mt-6 flex flex-wrap items-center gap-2 text-xs text-white/80">
                <span class="rounded-full bg-white/15 px-2.5 py-1">{{ statusLabel(featuredCase.status) }}</span>
                <span class="rounded-full bg-white/15 px-2.5 py-1">{{ modeLabel(featuredCase.workflow_mode) }}</span>
                <span>{{ t('showcase.caseUpdated', { date: formatDate(featuredCase.updated_at) }) }}</span>
              </div>
              <a :href="replayHref(featuredCase.public_id)" class="mt-7 inline-flex min-h-12 items-center gap-2 rounded-xl bg-white px-4 text-sm font-semibold text-rose-700 shadow-lg hover:bg-rose-50" @click.prevent="openReplay(featuredCase.public_id)">{{ t('showcase.caseReplay') }}<AppIcon name="ArrowRight" size="sm" aria-hidden="true" /></a>
            </div>
            <div class="p-6 md:p-8">
              <div v-if="detailState[featuredCase.public_id] === 'loading'" class="space-y-4" aria-busy="true"><div class="h-5 w-2/3 animate-pulse rounded bg-slate-200 dark:bg-slate-800" /><div class="h-20 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-800" /></div>
              <PublicReplayResult v-else :result="caseDetail(featuredCase).result || caseDetail(featuredCase).result_preview" compact />
            </div>
          </div>
        </div>
      </section>

      <section id="cases" class="mt-12 scroll-mt-20" aria-labelledby="cases-heading">
        <div class="flex flex-col justify-between gap-4 md:flex-row md:items-end">
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.14em] text-teal-600 dark:text-teal-300">{{ t('showcase.sectionTitle') }}</p>
            <h2 id="cases-heading" class="mt-2 text-2xl font-bold tracking-tight md:text-3xl">{{ t('showcase.evidenceTitle') }}</h2>
            <p class="mt-2 text-sm text-slate-500 dark:text-slate-400">{{ t('showcase.caseCount', { count: resultCount }) }}</p>
          </div>
        </div>

        <div class="mt-6 rounded-2xl border border-slate-200/80 bg-white/80 p-3 shadow-sm dark:border-slate-800 dark:bg-slate-900/70 md:p-4">
          <div class="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_auto_auto]">
            <label class="relative block"><span class="sr-only">{{ t('showcase.searchPlaceholder') }}</span><AppIcon name="Search" size="sm" variant="cyan" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2" aria-hidden="true" /><input v-model="search" type="search" class="min-h-11 w-full rounded-xl border border-slate-200 bg-white pl-10 pr-3 text-sm text-slate-800 outline-none ring-0 placeholder:text-slate-400 focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" :placeholder="t('showcase.searchPlaceholder')" /></label>
            <label><span class="sr-only">{{ t('showcase.filterStatus') }}</span><select v-model="statusFilter" class="min-h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"><option value="all">{{ t('showcase.filterAll') }}</option><option value="completed">{{ t('showcase.filterCompleted') }}</option><option value="in_progress">{{ t('showcase.filterInProgress') }}</option><option value="attention">{{ t('showcase.filterAttention') }}</option></select></label>
            <label><span class="sr-only">{{ t('showcase.filterMode') }}</span><select v-model="modeFilter" class="min-h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"><option value="all">{{ t('showcase.filterAll') }}</option><option value="trend">{{ t('showcase.filterTrend') }}</option><option value="brief">{{ t('showcase.filterBrief') }}</option></select></label>
            <label><span class="sr-only">{{ t('showcase.sortRecent') }}</span><select v-model="sortKey" class="min-h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"><option value="recent">{{ t('showcase.sortRecent') }}</option><option value="title">{{ t('showcase.sortTitle') }}</option></select></label>
          </div>
        </div>

        <div v-if="loading && !loaded" class="mt-5 grid gap-4 md:grid-cols-2">
          <div v-for="index in 4" :key="index" class="h-56 animate-pulse rounded-2xl bg-white/80 dark:bg-slate-900/80" aria-busy="true" />
        </div>
        <div v-else-if="loadError && !loaded" class="mt-5 rounded-2xl border border-rose-200 bg-rose-50 p-6 text-center dark:border-rose-400/20 dark:bg-rose-400/10">
          <AppIcon name="WifiOff" size="lg" variant="pink" aria-hidden="true" />
          <h3 class="mt-3 text-base font-semibold">{{ t('showcase.casesLoadFailed') }}</h3>
          <p class="mt-2 text-sm text-slate-600 dark:text-slate-300">{{ t('showcase.casesLoadFailedDesc') }}</p>
          <button type="button" class="mt-4 min-h-11 rounded-xl bg-slate-900 px-4 text-sm font-semibold text-white dark:bg-white dark:text-slate-900" :disabled="retrying" @click="retryCases">{{ retrying ? t('common.loadingState') : t('common.retry') }}</button>
        </div>
        <div v-else-if="loaded && !cases.length" class="mt-5 rounded-2xl border border-dashed border-slate-300 bg-white/70 p-8 text-center dark:border-slate-700 dark:bg-slate-900/70">
          <AppIcon name="Layers" size="lg" variant="cyan" aria-hidden="true" />
          <h3 class="mt-3 text-base font-semibold">{{ t('showcase.noPublicCases') }}</h3>
          <p class="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">{{ t('showcase.noPublicCasesDesc') }}</p>
          <button type="button" class="mt-5 min-h-11 rounded-xl bg-rose-600 px-4 text-sm font-semibold text-white hover:bg-rose-700" @click="goCreate">{{ t('showcase.startCreating') }}</button>
        </div>
        <div v-else-if="loaded && !filteredCases.length" class="mt-5 rounded-2xl border border-dashed border-slate-300 bg-white/70 p-8 text-center dark:border-slate-700 dark:bg-slate-900/70">
          <AppIcon name="SearchX" size="lg" variant="cyan" aria-hidden="true" />
          <h3 class="mt-3 text-base font-semibold">{{ t('showcase.noResults') }}</h3>
          <button type="button" class="mt-4 min-h-11 rounded-xl border border-slate-300 px-4 text-sm font-medium dark:border-slate-700" @click="clearFilters">{{ t('showcase.resetFilters') }}</button>
        </div>
        <div v-else class="mt-5 grid gap-4 md:grid-cols-2">
          <article v-for="item in filteredCases" :key="item.public_id" class="case-card group rounded-2xl border border-slate-200/80 bg-white/90 p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg dark:border-slate-800 dark:bg-slate-900/80">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0"><span class="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">{{ modeLabel(item.workflow_mode) }}</span><h3 class="mt-3 line-clamp-2 text-lg font-semibold leading-snug">{{ caseDetail(item).title }}</h3></div>
              <span class="shrink-0 rounded-full px-2.5 py-1 text-xs font-medium" :class="item.status === 'completed' ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-200' : item.status === 'attention' ? 'bg-amber-50 text-amber-700 dark:bg-amber-400/10 dark:text-amber-200' : 'bg-sky-50 text-sky-700 dark:bg-sky-400/10 dark:text-sky-200'">{{ statusLabel(item.status) }}</span>
            </div>
            <p class="mt-3 line-clamp-3 text-sm leading-6 text-slate-600 dark:text-slate-300">{{ caseDetail(item).summary }}</p>
            <div v-if="caseDetail(item).result_preview.topic" class="mt-4 rounded-xl bg-slate-50 p-3 text-sm text-slate-600 dark:bg-slate-800/70 dark:text-slate-300"><span class="font-medium text-slate-800 dark:text-slate-100">{{ t('showcase.detail.topic') }}：</span>{{ caseDetail(item).result_preview.topic }}</div>
            <div class="mt-5 flex items-center justify-between gap-3"><span class="text-xs text-slate-500 dark:text-slate-400">{{ t('showcase.caseUpdated', { date: formatDate(item.updated_at) }) }}</span><a :href="replayHref(item.public_id)" class="inline-flex min-h-11 items-center gap-1.5 rounded-xl px-3 text-sm font-semibold text-rose-600 hover:bg-rose-50 dark:text-rose-300 dark:hover:bg-rose-400/10" @click.prevent="openReplay(item.public_id)">{{ t('showcase.caseReplay') }}<AppIcon name="ArrowRight" size="xs" aria-hidden="true" /></a></div>
          </article>
        </div>
      </section>

      <section class="mt-14 rounded-3xl border border-slate-200/80 bg-white/70 p-6 dark:border-slate-800 dark:bg-slate-900/60 md:p-8" aria-labelledby="how-heading">
        <div class="max-w-xl"><p class="text-xs font-semibold uppercase tracking-[0.14em] text-teal-600 dark:text-teal-300">{{ t('showcase.howItWorks') }}</p><h2 id="how-heading" class="mt-2 text-2xl font-bold">{{ t('showcase.evidenceTitle') }}</h2></div>
        <div class="mt-6 grid gap-4 md:grid-cols-3">
          <div v-for="(step, index) in ['scouting', 'creating', 'analyzing']" :key="step" class="rounded-2xl border border-slate-200/70 p-4 dark:border-slate-800"><span class="text-sm font-semibold text-teal-600 dark:text-teal-300">0{{ index + 1 }}</span><h3 class="mt-3 text-base font-semibold">{{ t(`showcase.phase.${step}`) }}</h3><p class="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">{{ t(`showcase.steps.${step}`) }}</p></div>
        </div>
      </section>
    </main>

    <footer class="relative z-10 border-t border-slate-200/70 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">{{ t('showcase.footer') }}</footer>
  </div>
</template>

<style scoped>
.showcase-v2 {
  position: relative;
}

.showcase-v2-ambient {
  position: absolute;
  inset: 0 0 auto;
  height: 38rem;
  pointer-events: none;
  background:
    radial-gradient(circle at 15% 5%, rgba(244, 63, 94, 0.12), transparent 28%),
    radial-gradient(circle at 82% 12%, rgba(20, 184, 166, 0.12), transparent 28%);
}

@media (prefers-reduced-motion: reduce) {
  .showcase-v2 :deep(*) {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
</style>
