<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import AnimatedCounter from '@/components/AnimatedCounter.vue'
import AuroraBackground from '@/components/showcase/AuroraBackground.vue'
import PublicReplayResult from '@/components/replay/PublicReplayResult.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { vReveal } from '@/directives/reveal'
import { vSpotlight } from '@/directives/spotlight'
import { getPublicCase, listPublicCases } from '@/api/publicShowcase'
import type { PublicCase, PublicCaseStatus, PublicWorkflowMode } from '@/types/publicShowcase'
import { useAuthStore } from '@/stores/auth'
import { trackInteraction } from '@/utils/interactionTelemetry'
import { setPublicPageMeta } from '@/utils/publicMeta'

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
const loadingMore = ref(false)
const loadMoreError = ref(false)
const impressionTracker = new Set<string>()
let impressionObserver: IntersectionObserver | null = null

const CACHE_VERSION = 2
const CACHE_KEY = `showcase:public-cases:v${CACHE_VERSION}`
const CACHE_TTL = 30_000
let queryReady = false
let listRequestToken = 0
let listAbortController: AbortController | null = null
let loadMoreAbortController: AbortController | null = null
const detailAbortControllers = new Map<string, AbortController>()
const SHOWCASE_PAGE_SIZE = 20
const marqueeBadges = ['badgeTrend', 'badgeStrategy', 'badgeCopy', 'badgeShooting', 'badgeVisual', 'badgePublish', 'badgeAnalytics'] as const

const isAuthenticated = computed(() => authStore.isAuthenticated)
const featuredCase = computed(() => {
  const explicit = cases.value.find(item => item.featured && item.status !== 'attention')
  return explicit || cases.value.find(item => item.status === 'completed') || cases.value.find(item => item.status !== 'attention') || null
})

const filteredCases = computed(() => {
  const normalizedSearch = search.value.trim().toLocaleLowerCase(locale.value)
  const result = cases.value.filter((item) => {
    // When the featured case is the only public one, keep it in the grid —
    // excluding it would leave the section showing "0 cases" plus an empty state.
    if (cases.value.length > 1 && item.public_id === featuredCase.value?.public_id) return false
    if (statusFilter.value !== 'all' && item.status !== statusFilter.value) return false
    if (modeFilter.value !== 'all' && item.workflow_mode !== modeFilter.value) return false
    if (normalizedSearch) {
      const haystack = `${item.title} ${item.summary} ${item.workflow_mode} ${item.result_preview?.topic || ''} ${(item.result_preview?.hashtags || []).join(' ')}`.toLocaleLowerCase(locale.value)
      if (!haystack.includes(normalizedSearch)) return false
    }
    return true
  })
  return result.sort((a, b) => {
    if (sortKey.value === 'title') return a.title.localeCompare(b.title, locale.value)
    // ponytail: featured_rank first when present (recommended sort), else recency.
    const ra = a.featured_rank ?? Number.MAX_SAFE_INTEGER
    const rb = b.featured_rank ?? Number.MAX_SAFE_INTEGER
    if (ra !== rb) return ra - rb
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
  })
})

const resultCount = computed(() => filteredCases.value.length)
const showSearch = computed(() => cases.value.length >= 8)
const hasMoreCases = computed(() => cases.value.length < totalCases.value)

const statusChips = computed(() => [
  { value: 'all' as StatusFilter, label: t('showcase.filterAll') },
  { value: 'completed' as StatusFilter, label: t('showcase.filterCompleted') },
  { value: 'in_progress' as StatusFilter, label: t('showcase.filterInProgress') },
])

function setStatusFilter(value: StatusFilter) {
  statusFilter.value = value
}

let searchDebounce: ReturnType<typeof setTimeout> | null = null
const searchInput = ref('')
watch(searchInput, (value) => {
  if (searchDebounce) clearTimeout(searchDebounce)
  searchDebounce = setTimeout(() => {
    search.value = value
  }, 300)
})

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
  // `attention` is an internal/public-status value, not a user-facing filter.
  statusFilter.value = ['all', 'completed', 'in_progress'].includes(status || '') ? status || 'all' : 'all'
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
  trackInteraction('showcase_filter_change', { status: statusFilter.value, mode: modeFilter.value })
})

function readCache(): { cases: PublicCase[]; total: number } | null {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(CACHE_KEY) || '') as { version?: number; savedAt?: number; cases?: PublicCase[]; total?: number }
    if (parsed.version !== CACHE_VERSION || !parsed.savedAt || Date.now() - parsed.savedAt > CACHE_TTL || !Array.isArray(parsed.cases)) return null
    return { cases: parsed.cases, total: typeof parsed.total === 'number' ? parsed.total : parsed.cases.length }
  } catch {
    return null
  }
}

function writeCache(nextCases: PublicCase[], total = nextCases.length) {
  try {
    sessionStorage.setItem(CACHE_KEY, JSON.stringify({ version: CACHE_VERSION, savedAt: Date.now(), cases: nextCases, total }))
  } catch {
    // A full/private session store must not block the public page.
  }
}

function hydrate(cached: { cases: PublicCase[]; total: number }) {
  cases.value = cached.cases
  totalCases.value = cached.total
  loaded.value = true
  if (cached.cases[0]) void loadCaseDetail(cached.cases[0].public_id)
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
      { limit: SHOWCASE_PAGE_SIZE, offset: 0, sort: 'recent' },
      { suppressToast: true, signal: abortController.signal },
    )
    if (abortController.signal.aborted || requestToken !== listRequestToken) return
    cases.value = response.cases || []
    totalCases.value = response.total ?? cases.value.length
    loaded.value = true
    writeCache(cases.value, totalCases.value)
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

async function loadMoreCases() {
  if (!hasMoreCases.value || loadingMore.value) return
  loadMoreAbortController?.abort()
  const abortController = new AbortController()
  loadMoreAbortController = abortController
  const requestToken = listRequestToken
  loadingMore.value = true
  loadMoreError.value = false
  try {
    const response = await listPublicCases(
      { limit: SHOWCASE_PAGE_SIZE, offset: cases.value.length, sort: 'recent' },
      { suppressToast: true, signal: abortController.signal },
    )
    if (abortController.signal.aborted || requestToken !== listRequestToken) return
    const existing = new Set(cases.value.map(item => item.public_id))
    cases.value = [...cases.value, ...(response.cases || []).filter(item => !existing.has(item.public_id))]
    totalCases.value = response.total ?? totalCases.value
    writeCache(cases.value, totalCases.value)
    await nextTick()
    observeCaseCards()
  } catch {
    if (!abortController.signal.aborted && requestToken === listRequestToken) {
      loadMoreError.value = true
    }
  } finally {
    if (loadMoreAbortController === abortController) {
      loadMoreAbortController = null
      loadingMore.value = false
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

function goCreate(position: 'nav' | 'hero' | 'empty' = 'hero') {
  trackInteraction('showcase_cta_click', { auth_state: isAuthenticated.value ? 'authenticated' : 'guest', position })
  if (isAuthenticated.value) {
    void router.push({ name: 'home', query: { source: 'showcase' } })
  } else {
    void router.push({ name: 'login', query: { redirect: '/start?source=showcase' } })
  }
}

function openReplay(publicId: string) {
  const caseItem = cases.value.find(item => item.public_id === publicId)
  trackInteraction('showcase_case_open', { has_public_id: true, mode: caseItem?.workflow_mode || 'trend', status: caseItem?.status || 'completed' })
  try { sessionStorage.setItem('showcase:last-card', publicId) } catch { /* public page must not block */ }
  const from = route.fullPath || '/'
  void router.push({ name: 'replay', params: { publicId }, query: { from } })
}

function replayHref(publicId: string): string {
  const from = encodeURIComponent(route.fullPath || '/')
  return `/replay/${encodeURIComponent(publicId)}?from=${from}`
}

function openFeaturedReplay(publicId: string) {
  trackInteraction('showcase_featured_open', { has_public_id: true })
  void openReplay(publicId)
}

function retryFeaturedDetail() {
  const publicId = featuredCase.value?.public_id
  if (!publicId) return
  detailState.value = { ...detailState.value, [publicId]: 'idle' }
  detailCache.value.delete(publicId)
  trackInteraction('showcase_detail_retry', { has_public_id: true })
  void loadCaseDetail(publicId)
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

function observeCaseCards() {
  if (typeof IntersectionObserver === 'undefined') return
  if (!impressionObserver) {
    impressionObserver = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        const publicId = (entry.target as HTMLElement).dataset.casePublicId
        if (!publicId || impressionTracker.has(publicId)) continue
        impressionTracker.add(publicId)
        trackInteraction('showcase_case_impression', {})
      }
    }, { threshold: 0.5 })
  }
  const cards = document.querySelectorAll<HTMLElement>('.case-card[data-case-public-id]')
  cards.forEach(card => impressionObserver!.observe(card))
}

onMounted(async () => {
  if (!authStore.isInitialized) void authStore.initialize()
  restoreQuery()
  queryReady = true
  setPublicPageMeta({ title: t('showcase.seo.title'), description: t('showcase.seo.description') })
  trackInteraction('showcase_view')
  await loadCases()
  await nextTick()
  observeCaseCards()
  // SH-06: restore focus to the last-clicked case card when returning from replay.
  const lastCardId = sessionStorage.getItem('showcase:last-card')
  if (lastCardId) {
    sessionStorage.removeItem('showcase:last-card')
    const card = document.querySelector<HTMLElement>(`.case-card[data-case-public-id="${CSS.escape(lastCardId)}"] a`)
    card?.focus()
  }
})

onUnmounted(() => {
  listAbortController?.abort()
  loadMoreAbortController?.abort()
  detailAbortControllers.forEach(controller => controller.abort())
  detailAbortControllers.clear()
  impressionObserver?.disconnect()
  impressionObserver = null
  impressionTracker.clear()
})

watch(locale, () => {
  setPublicPageMeta({ title: t('showcase.seo.title'), description: t('showcase.seo.description') })
})

watch(filteredCases, async () => {
  await nextTick()
  observeCaseCards()
})
</script>

<template>
  <div class="showcase-v2 min-h-screen overflow-x-clip bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-50">
    <AuroraBackground variant="rose" />
    <a href="#cases" class="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-slate-900 focus:px-4 focus:py-3 focus:text-sm focus:font-semibold focus:text-white">{{ t('common.skipToContent') }}</a>
    <nav class="glass-panel relative z-10 border-b border-slate-200/60 dark:border-slate-800/60">
      <div class="mx-auto flex min-h-16 max-w-6xl items-center justify-between gap-4 px-4 md:px-8">
        <button type="button" class="flex min-h-11 items-center gap-3 rounded-xl text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500" @click="router.push({ name: 'showcase' })">
          <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-rose-500 to-amber-400 shadow-lg shadow-rose-500/30"><AppIcon name="Rocket" size="sm" variant="white" aria-hidden="true" /></span>
          <span>
            <span class="block text-sm font-bold tracking-tight">{{ t('showcase.title') }}</span>
            <span class="hidden text-xs text-slate-500 sm:block dark:text-slate-400">{{ t('showcase.navShowcase') }}</span>
          </span>
        </button>
        <div class="flex items-center gap-2">
          <button type="button" class="min-h-11 rounded-xl bg-rose-600 px-4 text-sm font-semibold text-white shadow-lg shadow-rose-600/25 transition hover:-translate-y-0.5 hover:bg-rose-700 hover:shadow-xl hover:shadow-rose-600/30" @click="goCreate('nav')">{{ t('showcase.startCreating') }}</button>
          <ThemeToggle class="shrink-0" />
        </div>
      </div>
    </nav>

    <main id="main-content" class="relative z-10 mx-auto max-w-6xl px-4 py-10 md:px-8 md:py-14">
      <section class="grid items-center gap-8 lg:grid-cols-[1.05fr_.95fr] lg:gap-14" aria-labelledby="showcase-title">
        <div>
          <p class="hero-enter inline-flex items-center gap-2 rounded-full border border-teal-200/80 bg-teal-50/90 px-3 py-1.5 text-xs font-semibold text-teal-700 shadow-sm dark:border-teal-400/20 dark:bg-teal-400/10 dark:text-teal-200" style="--enter-delay: 0ms">
            <span class="relative flex h-2 w-2" aria-hidden="true"><span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-teal-400 opacity-60" /><span class="relative inline-flex h-2 w-2 rounded-full bg-teal-500" /></span>
            {{ t('showcase.heroTagline') }}
          </p>
          <h1 id="showcase-title" class="hero-enter mt-5 max-w-2xl text-3xl font-bold leading-tight tracking-tight sm:text-4xl lg:text-5xl" style="--enter-delay: 90ms"><span class="text-gradient-brand">{{ t('showcase.heroTitle') }}</span></h1>
          <p class="hero-enter mt-5 max-w-xl text-base leading-7 text-slate-600 dark:text-slate-300" style="--enter-delay: 180ms">{{ t('showcase.heroDesc') }}</p>
          <div class="hero-enter mt-6 flex flex-wrap items-center gap-3" style="--enter-delay: 270ms">
            <button type="button" class="inline-flex min-h-12 animate-gradient-flow items-center gap-2 rounded-xl bg-gradient-to-r from-rose-600 via-rose-500 to-orange-500 bg-[length:180%_180%] px-5 text-sm font-semibold text-white shadow-lg shadow-rose-600/40 transition hover:-translate-y-0.5 hover:shadow-xl hover:shadow-rose-600/50" @click="goCreate('hero')">{{ t('showcase.startCreating') }}<AppIcon name="ArrowRight" size="sm" aria-hidden="true" /></button>
            <a href="#cases" class="inline-flex min-h-12 items-center rounded-xl px-4 text-sm font-medium text-slate-600 transition hover:bg-white dark:text-slate-300 dark:hover:bg-slate-900">{{ t('showcase.browseCases') }}</a>
          </div>
          <p class="hero-enter mt-4 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400" style="--enter-delay: 360ms"><AppIcon name="CheckCircle" size="xs" variant="cyan" aria-hidden="true" />{{ t('showcase.heroProof') }}</p>
        </div>

        <div v-if="featuredCase" class="hero-enter relative" style="--enter-delay: 220ms">
          <div class="hero-ghost hero-ghost-a rounded-3xl border border-rose-200/70 bg-white/70 dark:border-rose-400/15 dark:bg-slate-900/70" aria-hidden="true" />
          <div class="hero-ghost hero-ghost-b rounded-3xl border border-teal-200/70 bg-white/80 dark:border-teal-400/15 dark:bg-slate-900/80" aria-hidden="true" />
          <div class="animate-float-slow relative">
            <div v-spotlight class="glow-border rounded-3xl border border-slate-200/80 bg-white/85 p-5 shadow-xl shadow-slate-900/5 backdrop-blur-sm dark:border-slate-800 dark:bg-slate-900/85 md:p-6" data-case-public-id="hero-featured">
              <div class="flex items-center justify-between gap-4">
                <div>
                  <p class="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">{{ t('showcase.featuredCaseBadge') }}</p>
                  <p class="mt-2 text-xl font-semibold line-clamp-2">{{ caseDetail(featuredCase).title }}</p>
                </div>
                <AppIcon name="Sparkles" size="lg" variant="cyan" aria-hidden="true" />
              </div>
              <div class="mt-4 flex flex-wrap items-center gap-2 text-xs">
                <span class="rounded-full bg-slate-100 px-2.5 py-1 font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">{{ modeLabel(featuredCase.workflow_mode) }}</span>
                <span class="rounded-full px-2.5 py-1 font-medium" :class="featuredCase.status === 'completed' ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-200' : featuredCase.status === 'attention' ? 'bg-amber-50 text-amber-700 dark:bg-amber-400/10 dark:text-amber-200' : 'bg-sky-50 text-sky-700 dark:bg-sky-400/10 dark:text-sky-200'">{{ statusLabel(featuredCase.status) }}</span>
                <span class="text-slate-500 dark:text-slate-400">{{ t('showcase.caseUpdated', { date: formatDate(featuredCase.updated_at) }) }}</span>
              </div>
              <p v-if="caseDetail(featuredCase).result_preview.topic" class="mt-4 rounded-xl bg-slate-50 p-3 text-sm text-slate-600 dark:bg-slate-800/70 dark:text-slate-300"><span class="font-medium text-slate-800 dark:text-slate-100">{{ t('showcase.detail.topic') }}：</span>{{ caseDetail(featuredCase).result_preview.topic }}</p>
              <a :href="replayHref(featuredCase.public_id)" class="mt-5 inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-rose-600 px-4 text-sm font-semibold text-white shadow-lg shadow-rose-600/25 transition hover:-translate-y-0.5 hover:bg-rose-700 hover:shadow-xl hover:shadow-rose-600/30" @click.prevent="openFeaturedReplay(featuredCase.public_id)">{{ t('showcase.featuredOpenReplay') }}<AppIcon name="ArrowRight" size="sm" aria-hidden="true" /></a>
            </div>
          </div>
        </div>
      </section>

      <div v-reveal class="marquee mt-12" aria-hidden="true">
        <div class="marquee-track">
          <div v-for="half in 2" :key="half" class="flex shrink-0 items-center gap-3 pr-3">
            <span v-for="badge in marqueeBadges" :key="`${half}-${badge}`" class="flex items-center gap-2 rounded-full border border-slate-200/80 bg-white/75 px-4 py-2 text-xs font-semibold text-slate-500 shadow-sm backdrop-blur-sm dark:border-slate-700/70 dark:bg-slate-900/60 dark:text-slate-300"><span class="h-1.5 w-1.5 rounded-full bg-gradient-to-r from-rose-500 to-orange-400" />{{ t(`replay.${badge}`) }}</span>
          </div>
        </div>
      </div>

      <section v-if="featuredCase" v-reveal class="mt-10" aria-labelledby="featured-heading">
        <div class="border-beam rounded-3xl shadow-xl shadow-rose-900/10">
          <div class="overflow-hidden rounded-3xl bg-white dark:bg-slate-900">
            <div class="grid lg:grid-cols-[.82fr_1.18fr]">
              <div class="featured-shine relative overflow-hidden bg-gradient-to-br from-rose-500 via-orange-400 to-amber-300 p-6 text-white md:p-8">
                <p class="text-xs font-semibold uppercase tracking-[0.14em] text-white/90">{{ t('showcase.featuredLabel') }}</p>
                <h2 id="featured-heading" class="mt-4 text-2xl font-bold leading-tight md:text-3xl">{{ caseDetail(featuredCase).title }}</h2>
                <p class="mt-3 text-sm leading-6 text-white/95">{{ caseDetail(featuredCase).summary }}</p>
                <div class="mt-6 flex flex-wrap items-center gap-2 text-xs text-white/90">
                  <span class="rounded-full bg-white/15 px-2.5 py-1">{{ statusLabel(featuredCase.status) }}</span>
                  <span class="rounded-full bg-white/15 px-2.5 py-1">{{ modeLabel(featuredCase.workflow_mode) }}</span>
                  <span>{{ t('showcase.caseUpdated', { date: formatDate(featuredCase.updated_at) }) }}</span>
                </div>
                <a :href="replayHref(featuredCase.public_id)" class="mt-7 inline-flex min-h-12 items-center gap-2 rounded-xl bg-white px-4 text-sm font-semibold text-rose-700 shadow-lg transition hover:-translate-y-0.5 hover:bg-rose-50 hover:shadow-xl" @click.prevent="openFeaturedReplay(featuredCase.public_id)">{{ t('showcase.caseReplay') }}<AppIcon name="ArrowRight" size="sm" aria-hidden="true" /></a>
              </div>
              <div class="p-6 md:p-8">
                <div v-if="detailState[featuredCase.public_id] === 'loading'" class="space-y-4" aria-busy="true"><div class="h-5 w-2/3 animate-pulse rounded bg-slate-200 dark:bg-slate-800" /><div class="h-20 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-800" /></div>
                <div v-else-if="detailState[featuredCase.public_id] === 'error'" class="flex flex-col items-center gap-3 rounded-xl bg-rose-50 p-6 text-center dark:bg-rose-400/10" role="alert"><p class="text-sm font-medium text-rose-700 dark:text-rose-200">{{ t('replay.publicDetailFailed') }}</p><button type="button" class="inline-flex min-h-11 items-center rounded-xl bg-slate-900 px-4 text-sm font-semibold text-white dark:bg-white dark:text-slate-900" @click="retryFeaturedDetail">{{ t('replay.detailRetry') }}</button></div>
                <PublicReplayResult v-else :result="caseDetail(featuredCase).result || caseDetail(featuredCase).result_preview" compact />
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="cases" class="mt-16 scroll-mt-20" aria-labelledby="cases-heading">
        <div v-reveal class="relative flex flex-col justify-between gap-4 md:flex-row md:items-end">
          <span class="ghost-index ghost-index-rose" aria-hidden="true">01</span>
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.14em] text-teal-700 dark:text-teal-300">{{ t('showcase.sectionTitle') }}</p>
            <h2 id="cases-heading" class="mt-2 text-2xl font-bold tracking-tight md:text-3xl">{{ t('showcase.evidenceTitle') }}</h2>
            <i18n-t keypath="showcase.caseCount" tag="p" class="mt-2 text-sm text-slate-500 dark:text-slate-400">
              <template #count><AnimatedCounter :value="resultCount" class="font-semibold text-teal-700 dark:text-teal-300" /></template>
            </i18n-t>
          </div>
        </div>

        <div v-reveal class="glass-panel mt-6 rounded-2xl p-3 shadow-sm md:p-4">
          <div class="flex flex-col gap-3">
            <label v-if="showSearch" class="relative block"><span class="sr-only">{{ t('showcase.searchPlaceholder') }}</span><AppIcon name="Search" size="sm" variant="cyan" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2" aria-hidden="true" /><input v-model="searchInput" type="search" class="min-h-11 w-full rounded-xl border border-slate-200 bg-white pl-10 pr-3 text-sm text-slate-800 outline-none ring-0 placeholder:text-slate-400 focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" :placeholder="t('showcase.searchPlaceholder')" /></label>
            <div class="flex flex-wrap items-center gap-2">
              <button type="button" v-for="chip in statusChips" :key="chip.value" class="min-h-11 rounded-full px-4 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500" :class="statusFilter === chip.value ? 'bg-slate-900 text-white shadow-md shadow-slate-900/20 ring-2 ring-teal-400/40 dark:bg-white dark:text-slate-900' : 'border border-slate-200 text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800'" :aria-pressed="statusFilter === chip.value" @click="setStatusFilter(chip.value)">{{ chip.label }}</button>
              <span class="ml-auto flex items-center gap-2">
                <label class="sr-only" for="showcase-mode-filter">{{ t('showcase.filterMode') }}</label>
                <select id="showcase-mode-filter" v-model="modeFilter" class="min-h-11 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"><option value="all">{{ t('showcase.filterAll') }}</option><option value="trend">{{ t('showcase.filterTrend') }}</option><option value="brief">{{ t('showcase.filterBrief') }}</option></select>
                <label class="sr-only" for="showcase-sort">{{ t('showcase.sortRecent') }}</label>
                <select id="showcase-sort" v-model="sortKey" class="min-h-11 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"><option value="recent">{{ t('showcase.sortRecent') }}</option><option value="title">{{ t('showcase.sortTitle') }}</option></select>
              </span>
            </div>
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
          <button type="button" class="mt-5 min-h-11 rounded-xl bg-rose-600 px-4 text-sm font-semibold text-white hover:bg-rose-700" @click="goCreate('empty')">{{ t('showcase.startCreating') }}</button>
        </div>
        <div v-else-if="loaded && !filteredCases.length" class="mt-5 rounded-2xl border border-dashed border-slate-300 bg-white/70 p-8 text-center dark:border-slate-700 dark:bg-slate-900/70">
          <AppIcon name="SearchX" size="lg" variant="cyan" aria-hidden="true" />
          <h3 class="mt-3 text-base font-semibold">{{ t('showcase.noResults') }}</h3>
          <button type="button" class="mt-4 min-h-11 rounded-xl border border-slate-300 px-4 text-sm font-medium dark:border-slate-700" @click="clearFilters">{{ t('showcase.resetFilters') }}</button>
        </div>
        <div v-else class="mt-5 grid gap-4 md:grid-cols-3">
          <article v-for="(item, index) in filteredCases" :key="item.public_id" v-reveal="(index % 4) * 70" v-spotlight class="case-card glow-border group rounded-2xl border border-slate-200/80 bg-white/90 p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900/80" :class="index % 5 === 0 ? 'md:col-span-2' : ''" :data-case-public-id="item.public_id">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0"><span class="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">{{ modeLabel(item.workflow_mode) }}</span><h3 class="mt-3 line-clamp-2 text-lg font-semibold leading-snug">{{ caseDetail(item).title }}</h3></div>
              <span class="shrink-0 rounded-full px-2.5 py-1 text-xs font-medium" :class="item.status === 'completed' ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-200' : item.status === 'attention' ? 'bg-amber-50 text-amber-700 dark:bg-amber-400/10 dark:text-amber-200' : 'bg-sky-50 text-sky-700 dark:bg-sky-400/10 dark:text-sky-200'">{{ statusLabel(item.status) }}</span>
            </div>
            <p class="mt-3 line-clamp-3 text-sm leading-6 text-slate-600 dark:text-slate-300">{{ caseDetail(item).summary }}</p>
            <div v-if="caseDetail(item).result_preview.topic" class="mt-4 rounded-xl bg-slate-50 p-3 text-sm text-slate-600 dark:bg-slate-800/70 dark:text-slate-300"><span class="font-medium text-slate-800 dark:text-slate-100">{{ t('showcase.detail.topic') }}：</span>{{ caseDetail(item).result_preview.topic }}</div>
            <div class="mt-5 flex items-center justify-between gap-3"><span class="text-xs text-slate-500 dark:text-slate-400">{{ t('showcase.caseUpdated', { date: formatDate(item.updated_at) }) }}</span><a :href="replayHref(item.public_id)" class="inline-flex min-h-11 items-center gap-1.5 rounded-xl px-3 text-sm font-semibold text-rose-600 transition hover:bg-rose-50 dark:text-rose-300 dark:hover:bg-rose-400/10" @click.prevent="openReplay(item.public_id)">{{ t('showcase.caseReplay') }}<AppIcon name="ArrowRight" size="xs" class="transition group-hover:translate-x-0.5" aria-hidden="true" /></a></div>
          </article>
        </div>
        <div v-if="hasMoreCases" class="mt-5 flex flex-col items-center gap-3">
          <button type="button" class="min-h-11 rounded-xl border border-slate-300 bg-white px-5 text-sm font-semibold text-slate-700 transition hover:-translate-y-0.5 hover:bg-slate-50 hover:shadow-md disabled:cursor-wait disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800" :disabled="loadingMore" @click="loadMoreCases">
            {{ loadingMore ? t('common.loadingState') : t('showcase.loadMore') }}
          </button>
          <p v-if="loadMoreError" class="flex items-center gap-2 text-xs text-rose-600 dark:text-rose-300" role="alert">
            <span>{{ t('showcase.loadMoreFailed') }}</span>
            <button type="button" class="min-h-11 rounded-lg px-3 font-semibold underline" @click="loadMoreCases">{{ t('common.retry') }}</button>
          </p>
        </div>
      </section>

      <section v-reveal class="glass-panel relative mt-16 overflow-hidden rounded-3xl p-6 md:p-8" aria-labelledby="how-heading">
        <span class="ghost-index ghost-index-teal" aria-hidden="true">02</span>
        <div class="max-w-xl"><p class="text-xs font-semibold uppercase tracking-[0.14em] text-teal-700 dark:text-teal-300">{{ t('showcase.howItWorks') }}</p><h2 id="how-heading" class="mt-2 text-2xl font-bold">{{ t('showcase.evidenceTitle') }}</h2></div>
        <div class="mt-8 grid gap-5 md:grid-cols-3 md:pb-10">
          <div v-for="(step, index) in ['scouting', 'creating', 'analyzing']" :key="step" v-reveal="index * 110">
            <div class="how-step relative rounded-2xl border border-slate-200/70 bg-white/60 p-5 transition hover:-translate-y-1 hover:shadow-lg dark:border-slate-800 dark:bg-slate-900/50" :class="index === 1 ? 'md:translate-y-5' : index === 2 ? 'md:translate-y-10' : ''">
              <span class="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-teal-500 to-cyan-400 text-sm font-bold text-white shadow-md shadow-teal-500/25">0{{ index + 1 }}</span>
              <h3 class="mt-4 text-base font-semibold">{{ t(`showcase.phase.${step}`) }}</h3>
              <p class="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">{{ t(`showcase.steps.${step}`) }}</p>
            </div>
          </div>
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

/* Staggered hero entrance — delay comes from the inline --enter-delay var. */
.hero-enter {
  opacity: 0;
  animation: showcase-rise 0.75s cubic-bezier(0.22, 1, 0.36, 1) forwards;
  animation-delay: var(--enter-delay, 0ms);
}

@keyframes showcase-rise {
  from {
    opacity: 0;
    transform: translateY(26px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Light sweep across the featured-case gradient panel. */
.featured-shine::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(115deg, transparent 32%, rgb(255 255 255 / 0.25) 48%, transparent 64%);
  background-size: 260% 100%;
  animation: shine-sweep 5.5s ease-in-out infinite;
  pointer-events: none;
}

@keyframes shine-sweep {
  0% {
    background-position: 130% 0;
  }
  55%, 100% {
    background-position: -70% 0;
  }
}

/* Card deck behind the hero featured card — two offset ghost sheets. */
.hero-ghost {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.hero-ghost-a {
  transform: rotate(-3.5deg) translate(-0.85rem, 0.6rem);
}

.hero-ghost-b {
  transform: rotate(2.2deg) translate(0.85rem, -0.3rem);
}

/* Giant outlined section indices (editorial rhythm). */
.ghost-index {
  position: absolute;
  top: -2.5rem;
  right: 0;
  font-size: 5.5rem;
  font-weight: 800;
  line-height: 1;
  letter-spacing: -0.04em;
  color: transparent;
  -webkit-text-stroke: 1.5px rgb(244 63 94 / 0.2);
  pointer-events: none;
  user-select: none;
}

.ghost-index-teal {
  top: 0.5rem;
  right: 1rem;
  -webkit-text-stroke-color: rgb(20 184 166 / 0.22);
}

.dark .ghost-index-rose {
  -webkit-text-stroke-color: rgb(251 113 133 / 0.3);
}

.dark .ghost-index-teal {
  -webkit-text-stroke-color: rgb(45 212 191 / 0.3);
}

@media (prefers-reduced-motion: reduce) {
  .hero-enter {
    animation: none;
    opacity: 1;
  }

  .featured-shine::after {
    animation: none;
  }

  .showcase-v2 .animate-pulse,
  .showcase-v2 .animate-ping,
  .showcase-v2 .animate-float-slow {
    animation: none !important;
  }

  .showcase-v2 button,
  .showcase-v2 a {
    transition-duration: 100ms !important;
  }
}
</style>
