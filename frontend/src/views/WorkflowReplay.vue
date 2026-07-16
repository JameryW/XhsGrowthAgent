<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import PublicReplayResult from '@/components/replay/PublicReplayResult.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import {
  getPublicFinalSummary,
  getPublicReplayCheckpoint,
  getPublicReplayManifest,
} from '@/api/publicShowcase'
import type {
  PublicCaseStatus,
  PublicFinalSummaryResponse,
  PublicReplayManifestResponse,
  PublicReplayStep,
} from '@/types/publicShowcase'
import { useAuthStore } from '@/stores/auth'
import { trackInteraction } from '@/utils/interactionTelemetry'

const { t, locale } = useI18n()
const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const publicId = computed(() => String(route.params.publicId || route.params.threadId || ''))
const isAuthenticated = computed(() => authStore.isAuthenticated)
const manifest = ref<PublicReplayManifestResponse | null>(null)
const finalSummary = ref<PublicFinalSummaryResponse | null>(null)
const selectedStep = ref<PublicReplayStep | null>(null)
const selectedStepId = ref<string | null>(null)
const viewMode = ref<'key' | 'all'>('key')
const loading = ref(true)
const detailLoading = ref(false)
const manifestError = ref(false)
const detailError = ref(false)
const notFound = ref(false)
const retrying = ref(false)
const shareState = ref<'idle' | 'success' | 'error'>('idle')
const firstResultTracked = ref(false)
const loadingMore = ref(false)
const loadMoreError = ref(false)

const REPLAY_CACHE_VERSION = 1
const REPLAY_CACHE_TTL = 30_000
const REPLAY_CACHE_KEY = 'replay:public-step-cache:v1'
const REPLAY_PAGE_SIZE = 20
let manifestRequestToken = 0
let detailRequestToken = 0
let manifestAbortController: AbortController | null = null
let loadMoreAbortController: AbortController | null = null
let detailAbortController: AbortController | null = null

const steps = computed(() => [...(manifest.value?.steps || [])].sort((a, b) => a.step - b.step))
const currentIndex = computed(() => steps.value.findIndex(step => step.public_id === selectedStepId.value))
const currentStepNumber = computed(() => Math.max(currentIndex.value + 1, 1))
const caseStatus = computed<PublicCaseStatus>(() => manifest.value?.workflow.status || 'in_progress')
const caseStatusLabel = computed(() => t(`showcase.caseStatus.${caseStatus.value}`))
const selectedPhase = computed(() => selectedStep.value?.phase || steps.value.find(step => step.public_id === selectedStepId.value)?.phase || '')
const phaseGroups = computed(() => {
  const seen = new Set<string>()
  return steps.value.reduce<PublicReplayStep[]>((groups, step) => {
    if (!seen.has(step.phase)) {
      seen.add(step.phase)
      groups.push(step)
    }
    return groups
  }, [])
})
const canLoadMore = computed(() => Boolean(manifest.value?.has_more))
const returnPath = computed(() => {
  const value = route.query.from
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') ? value : '/'
})

function queryStep(): string | undefined {
  const value = route.query.step || route.query.checkpoint
  return typeof value === 'string' && value ? value : undefined
}

function phaseLabel(phase: string): string {
  const key = `showcase.phase.${phase}`
  const translated = t(key)
  return translated === key ? phase : translated
}

function formatDate(value: string | null | undefined): string {
  if (!value) return ''
  return new Intl.DateTimeFormat(locale.value || undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(value))
}

function isNotFoundError(error: any): boolean {
  return error?.code === 'ERROR_WORKFLOW_NOT_FOUND' || error?.status === 404 || /not found|不存在/i.test(error?.message || '')
}

function cacheKey(stepId: string, technical: boolean): string {
  return `${publicId.value}:${technical ? 'all' : 'key'}:${stepId}`
}

function readCachedStep(stepId: string, technical: boolean): PublicReplayStep | null {
  try {
    const raw = JSON.parse(sessionStorage.getItem(REPLAY_CACHE_KEY) || '{}') as Record<string, { version?: number; savedAt?: number; step?: PublicReplayStep }>
    const cached = raw[cacheKey(stepId, technical)]
    if (!cached || cached.version !== REPLAY_CACHE_VERSION || !cached.savedAt || Date.now() - cached.savedAt > REPLAY_CACHE_TTL || !cached.step) return null
    return cached.step
  } catch {
    return null
  }
}

function writeCachedStep(stepId: string, technical: boolean, step: PublicReplayStep) {
  try {
    const raw = JSON.parse(sessionStorage.getItem(REPLAY_CACHE_KEY) || '{}') as Record<string, { version?: number; savedAt?: number; step?: PublicReplayStep }>
    const entries = Object.entries(raw).filter(([, item]) => item?.savedAt && Date.now() - item.savedAt <= REPLAY_CACHE_TTL)
    entries.push([cacheKey(stepId, technical), { version: REPLAY_CACHE_VERSION, savedAt: Date.now(), step }])
    const trimmed = entries.slice(-24)
    sessionStorage.setItem(REPLAY_CACHE_KEY, JSON.stringify(Object.fromEntries(trimmed)))
  } catch {
    // A full/private session store must not block replay navigation.
  }
}

function preferredStep(available: PublicReplayStep[]): PublicReplayStep | null {
  const requested = queryStep()
  return available.find(step => step.public_id === requested)
    || available.find(step => step.has_result)
    || available[0]
    || null
}

function mergeManifest(next: PublicReplayManifestResponse) {
  const current = manifest.value
  if (!current || next.offset === 0) {
    manifest.value = next
    return
  }
  const merged = [...current.steps, ...next.steps]
  const unique = Array.from(new Map(merged.map(step => [step.public_id, step])).values())
  manifest.value = { ...next, steps: unique, offset: 0 }
}

async function loadMoreSteps(): Promise<boolean> {
  if (!manifest.value || !manifest.value.has_more || loadingMore.value) return false
  loadMoreAbortController?.abort()
  const abortController = new AbortController()
  loadMoreAbortController = abortController
  loadingMore.value = true
  loadMoreError.value = false
  const requestToken = manifestRequestToken
  const previousCount = steps.value.length
  try {
    const next = await getPublicReplayManifest(
      publicId.value,
      viewMode.value === 'all' && isAuthenticated.value,
      { suppressToast: true, limit: REPLAY_PAGE_SIZE, offset: steps.value.length, signal: abortController.signal },
    )
    if (requestToken !== manifestRequestToken || !publicId.value) return false
    mergeManifest(next)
    return steps.value.length > previousCount || !manifest.value?.has_more
  } catch {
    if (!abortController.signal.aborted && requestToken === manifestRequestToken) {
      loadMoreError.value = true
      trackInteraction('replay_load_more_error', { view: viewMode.value })
    }
    return false
  } finally {
    if (loadMoreAbortController === abortController) {
      loadMoreAbortController = null
      loadingMore.value = false
    }
  }
}

async function ensureRequestedStep() {
  const requested = queryStep()
  while (requested && manifest.value?.has_more && !steps.value.some(step => step.public_id === requested)) {
    if (!await loadMoreSteps()) break
  }
}

function focusPhase(index: number) {
  const target = document.querySelector<HTMLButtonElement>(`[data-phase-index="${index}"]`)
  target?.focus()
}

function handlePhaseKeydown(event: KeyboardEvent, index: number) {
  if (!phaseGroups.value.length) return
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
    event.preventDefault()
    focusPhase((index + 1) % phaseGroups.value.length)
  } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
    event.preventDefault()
    focusPhase((index - 1 + phaseGroups.value.length) % phaseGroups.value.length)
  } else if (event.key === 'Home') {
    event.preventDefault()
    focusPhase(0)
  } else if (event.key === 'End') {
    event.preventDefault()
    focusPhase(phaseGroups.value.length - 1)
  }
}

async function selectPhase(step: PublicReplayStep) {
  await selectStep(step)
}

async function loadStep(stepId: string | null) {
  if (!stepId || !manifest.value) {
    selectedStep.value = null
    return
  }
  const manifestStep = steps.value.find(step => step.public_id === stepId)
  if (!manifestStep) return
  selectedStepId.value = stepId
  detailLoading.value = true
  detailError.value = false
  detailAbortController?.abort()
  const abortController = new AbortController()
  detailAbortController = abortController
  const requestToken = ++detailRequestToken
  const technical = viewMode.value === 'all' && isAuthenticated.value
  const cached = readCachedStep(stepId, technical)
  if (cached) {
    selectedStep.value = cached
    detailLoading.value = false
    trackInteraction(firstResultTracked.value ? 'replay_select_to_render' : 'replay_first_result_visible', {
      view: viewMode.value,
      cached: true,
      duration_ms: 0,
    })
    firstResultTracked.value = true
    return
  }
  const startedAt = typeof performance !== 'undefined' ? performance.now() : 0
  try {
    const nextStep = await getPublicReplayCheckpoint(publicId.value, stepId, technical, {
      suppressToast: true,
      signal: abortController.signal,
    })
    if (requestToken !== detailRequestToken) return
    selectedStep.value = nextStep
    writeCachedStep(stepId, technical, nextStep)
    const duration = typeof performance !== 'undefined' ? Math.round(performance.now() - startedAt) : undefined
    trackInteraction(firstResultTracked.value ? 'replay_select_to_render' : 'replay_first_result_visible', {
      view: viewMode.value,
      duration_ms: duration,
    })
    firstResultTracked.value = true
  } catch (error: any) {
    if (abortController.signal.aborted || requestToken !== detailRequestToken) return
    detailError.value = true
    if (isNotFoundError(error)) notFound.value = true
  } finally {
    if (detailAbortController === abortController) {
      detailAbortController = null
      if (requestToken === detailRequestToken) detailLoading.value = false
    }
  }
}

async function loadReplay() {
  manifestAbortController?.abort()
  loadMoreAbortController?.abort()
  detailAbortController?.abort()
  const abortController = new AbortController()
  manifestAbortController = abortController
  const requestToken = ++manifestRequestToken
  detailRequestToken += 1
  loading.value = true
  manifestError.value = false
  detailError.value = false
  loadMoreError.value = false
  notFound.value = false
  selectedStep.value = null
  try {
    const technical = viewMode.value === 'all' && isAuthenticated.value
    const [nextManifest, nextSummary] = await Promise.all([
      getPublicReplayManifest(publicId.value, technical, {
        suppressToast: true,
        limit: REPLAY_PAGE_SIZE,
        offset: 0,
        signal: abortController.signal,
      }),
      getPublicFinalSummary(publicId.value, { suppressToast: true, signal: abortController.signal }).catch(() => null),
    ])
    if (requestToken !== manifestRequestToken) return
    mergeManifest(nextManifest)
    finalSummary.value = nextSummary
    await ensureRequestedStep()
    if (requestToken !== manifestRequestToken) return
    const first = preferredStep(steps.value)
    selectedStepId.value = first?.public_id || null
    if (first) await loadStep(first.public_id)
    trackInteraction('replay_view', { view: viewMode.value, has_steps: Boolean(first) })
  } catch (error: any) {
    if (abortController.signal.aborted || requestToken !== manifestRequestToken) return
    manifestError.value = true
    notFound.value = isNotFoundError(error)
    trackInteraction('replay_load_error', { error_type: notFound.value ? 'not_found' : 'manifest' })
  } finally {
    if (manifestAbortController === abortController) {
      manifestAbortController = null
      loading.value = false
    }
  }
}

async function retryReplay() {
  retrying.value = true
  try {
    await loadReplay()
  } finally {
    retrying.value = false
  }
}

async function selectStep(step: PublicReplayStep) {
  if (step.public_id === selectedStepId.value && selectedStep.value) return
  selectedStepId.value = step.public_id
  await router.replace({ query: { ...route.query, step: step.public_id } })
  trackInteraction('replay_step_select', { view: viewMode.value, has_result: step.has_result })
  await loadStep(step.public_id)
}

async function selectAdjacent(direction: -1 | 1) {
  const nextIndex = currentIndex.value + direction
  const step = steps.value[nextIndex]
  if (step) await selectStep(step)
}

async function toggleView(mode: 'key' | 'all') {
  if (mode === 'all' && !isAuthenticated.value) {
    void router.push({ name: 'login', query: { redirect: route.fullPath } })
    return
  }
  if (viewMode.value === mode) return
  viewMode.value = mode
  trackInteraction('replay_view_mode_change', { view: mode })
  await loadReplay()
}

function goBack() {
  trackInteraction('replay_back', { source: route.query.from ? 'showcase' : 'direct' })
  void router.push(returnPath.value)
}

function goCreate() {
  trackInteraction('replay_primary_cta_click', { authenticated: isAuthenticated.value })
  if (isAuthenticated.value) void router.push({ name: 'home' })
  else void router.push({ name: 'login', query: { redirect: '/start' } })
}

function goWorkspace() {
  if (isAuthenticated.value) void router.push({ name: 'dashboard' })
  else void router.push({ name: 'login', query: { redirect: '/dashboard' } })
}

async function copyLink(step = false) {
  shareState.value = 'idle'
  const query = step && selectedStepId.value ? { ...route.query, step: selectedStepId.value } : { from: '/' }
  const resolved = router.resolve({ name: 'replay', params: { publicId: publicId.value }, query })
  const href = typeof window !== 'undefined' ? new URL(resolved.href, window.location.origin).toString() : resolved.href
  try {
    await navigator.clipboard.writeText(href)
    shareState.value = 'success'
    trackInteraction(step ? 'replay_step_link_copy' : 'replay_case_link_copy', { has_step: step })
  } catch {
    shareState.value = 'error'
    trackInteraction('replay_share_error', { has_step: step })
  }
}

watch(() => route.query.step, (value) => {
  if (typeof value === 'string' && value !== selectedStepId.value) {
    void ensureRequestedStep().then(() => {
      if (steps.value.some(step => step.public_id === value)) void loadStep(value)
    })
  }
})

watch(publicId, (next, previous) => {
  if (next && next !== previous) void loadReplay()
})

onUnmounted(() => {
  manifestAbortController?.abort()
  loadMoreAbortController?.abort()
  detailAbortController?.abort()
})

onMounted(() => {
  if (!authStore.isInitialized) void authStore.initialize()
  void loadReplay()
})
</script>

<template>
  <div class="replay-v2 min-h-screen overflow-x-clip bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-50">
    <div class="replay-v2-ambient" aria-hidden="true" />
    <a href="#replay-results" class="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-slate-900 focus:px-4 focus:py-3 focus:text-sm focus:font-semibold focus:text-white">{{ t('common.skipToContent') }}</a>
    <nav class="relative z-10 border-b border-slate-200/70 bg-white/85 backdrop-blur-xl dark:border-slate-800/70 dark:bg-slate-950/85">
      <div class="mx-auto flex min-h-16 max-w-6xl items-center justify-between gap-3 px-4 md:px-8">
        <div class="flex min-w-0 items-center gap-3">
          <button type="button" class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-slate-600 hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 dark:text-slate-300 dark:hover:bg-slate-800" :aria-label="t('replay.publicBack')" @click="goBack"><AppIcon name="ArrowLeft" size="sm" aria-hidden="true" /></button>
          <div class="min-w-0"><p class="truncate text-sm font-bold">{{ manifest?.workflow.title || t('replay.title') }}</p><div class="mt-0.5 flex items-center gap-2"><span class="text-xs text-slate-500 dark:text-slate-400">{{ t('replay.title') }}</span><span class="rounded-full px-2 py-0.5 text-xs font-medium" :class="caseStatus === 'completed' ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-200' : 'bg-sky-50 text-sky-700 dark:bg-sky-400/10 dark:text-sky-200'">{{ caseStatusLabel }}</span></div></div>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <button type="button" class="hidden min-h-11 rounded-xl border border-slate-200 px-3 text-sm font-medium text-slate-600 hover:bg-slate-50 sm:inline-flex dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800" @click="copyLink(false)"><AppIcon name="Copy" size="xs" class="mr-1.5" aria-hidden="true" />{{ shareState === 'success' ? t('replay.publicShared') : shareState === 'error' ? t('replay.publicShareFailed') : t('replay.publicShareCase') }}</button>
          <button type="button" class="min-h-11 rounded-xl bg-rose-500 px-3 text-sm font-semibold text-white shadow-lg shadow-rose-500/20 hover:bg-rose-600" @click="isAuthenticated ? goWorkspace() : goCreate">{{ isAuthenticated ? t('replay.publicWorkspace') : t('replay.publicStart') }}</button>
          <ThemeToggle class="shrink-0" />
        </div>
      </div>
    </nav>

    <main class="relative z-10 mx-auto max-w-6xl px-4 py-6 md:px-8 md:py-10">
      <section v-if="loading" class="rounded-3xl border border-slate-200/80 bg-white/80 p-6 dark:border-slate-800 dark:bg-slate-900/80" aria-busy="true"><div class="h-5 w-2/3 animate-pulse rounded bg-slate-200 dark:bg-slate-800" /><div class="mt-4 h-3 w-full animate-pulse rounded bg-slate-100 dark:bg-slate-800" /><div class="mt-8 h-64 animate-pulse rounded-2xl bg-slate-100 dark:bg-slate-800" /><p class="mt-4 text-sm text-slate-500">{{ t('replay.loadingWorkflow') }}</p></section>
      <section v-else-if="notFound" class="rounded-3xl border border-dashed border-slate-300 bg-white/80 p-10 text-center dark:border-slate-700 dark:bg-slate-900/80" role="alert"><AppIcon name="HelpCircle" size="lg" variant="cyan" aria-hidden="true" /><h1 class="mt-4 text-xl font-semibold">{{ t('replay.threadNotFound') }}</h1><p class="mt-2 text-sm text-slate-500 dark:text-slate-400">{{ t('replay.threadNotFoundDesc') }}</p><button type="button" class="mt-5 min-h-11 rounded-xl bg-slate-900 px-4 text-sm font-semibold text-white dark:bg-white dark:text-slate-900" @click="goBack">{{ t('replay.publicBack') }}</button></section>
      <section v-else-if="manifestError" class="rounded-3xl border border-rose-200 bg-rose-50 p-8 text-center dark:border-rose-400/20 dark:bg-rose-400/10" role="alert"><AppIcon name="WifiOff" size="lg" variant="pink" aria-hidden="true" /><h1 class="mt-4 text-xl font-semibold">{{ t('replay.publicLoadFailed') }}</h1><p class="mt-2 text-sm text-slate-600 dark:text-slate-300">{{ t('replay.publicLoadFailedDesc') }}</p><button type="button" class="mt-5 min-h-11 rounded-xl bg-slate-900 px-4 text-sm font-semibold text-white dark:bg-white dark:text-slate-900" :disabled="retrying" @click="retryReplay">{{ retrying ? t('common.loadingState') : t('common.retry') }}</button></section>
      <template v-else-if="manifest">
        <header class="flex flex-col justify-between gap-5 md:flex-row md:items-end">
          <div class="min-w-0"><p class="text-xs font-semibold uppercase tracking-[0.14em] text-teal-600 dark:text-teal-300">{{ t('replay.publicKeySteps') }}</p><h1 class="mt-2 max-w-3xl text-2xl font-bold leading-tight md:text-4xl">{{ manifest.workflow.title }}</h1><p class="mt-3 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">{{ manifest.workflow.summary }}</p></div>
          <div class="flex shrink-0 items-center gap-2"><button type="button" class="min-h-11 rounded-xl border border-slate-200 px-3 text-sm font-medium text-slate-600 hover:bg-white dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-900" @click="copyLink(true)"><AppIcon name="Copy" size="xs" class="mr-1.5" aria-hidden="true" />{{ shareState === 'success' ? t('replay.publicShared') : shareState === 'error' ? t('replay.publicShareFailed') : t('replay.publicShareStep') }}</button><span class="rounded-full bg-slate-100 px-3 py-2 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">{{ caseStatusLabel }}</span></div>
        </header>
        <p class="sr-only" aria-live="polite">{{ selectedStep ? t('replay.publicSelectedStep', { step: selectedStep.step, title: selectedStep.title || t('replay.publicStep', { step: selectedStep.step }) }) : '' }}</p>

        <section class="mt-7 rounded-3xl border border-slate-200/80 bg-white/85 p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/80 md:p-5" aria-labelledby="replay-steps-heading">
          <div class="flex flex-col justify-between gap-3 sm:flex-row sm:items-center"><div><h2 id="replay-steps-heading" class="text-base font-semibold">{{ t('replay.publicKeySteps') }}</h2><p class="mt-1 text-sm text-slate-500 dark:text-slate-400">{{ t('replay.publicStepCount', { key: manifest.key_step_count, total: viewMode === 'all' ? manifest.total_steps : manifest.key_step_count }) }}</p></div><div class="flex items-center gap-2"><button type="button" class="min-h-11 rounded-xl px-3 text-sm font-medium" :class="viewMode === 'key' ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'" :aria-pressed="viewMode === 'key'" @click="toggleView('key')">{{ t('replay.publicKeySteps') }}</button><button type="button" class="min-h-11 rounded-xl px-3 text-sm font-medium" :class="viewMode === 'all' ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'" :aria-pressed="viewMode === 'all'" @click="toggleView('all')">{{ t('replay.publicAllSteps') }}</button></div></div>
          <p v-if="viewMode === 'key' && manifest.technical_steps_available && !isAuthenticated" class="mt-2 text-xs text-slate-500 dark:text-slate-400">{{ t('replay.publicLoginForAdvanced') }}</p>
          <nav v-if="phaseGroups.length > 1" class="mt-5 overflow-x-auto border-y border-slate-200/70 py-3 dark:border-slate-800" :aria-label="t('replay.publicPhaseNavigation')"><ol class="flex min-w-max items-center gap-2"><li v-for="(phase, index) in phaseGroups" :key="phase.phase"><button type="button" :data-phase-index="index" :tabindex="selectedPhase === phase.phase ? 0 : -1" class="min-h-11 rounded-xl px-3 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500" :class="selectedPhase === phase.phase ? 'bg-teal-50 text-teal-700 dark:bg-teal-400/10 dark:text-teal-200' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'" :aria-current="selectedPhase === phase.phase ? 'step' : undefined" @click="selectPhase(phase)" @keydown="handlePhaseKeydown($event, index)">{{ phaseLabel(phase.phase) }}</button></li></ol></nav>
          <ol v-if="steps.length" class="mt-5 grid gap-3 md:grid-cols-2 lg:grid-cols-3" :aria-label="t('replay.publicStepsLabel')">
            <li v-for="(step, index) in steps" :key="step.public_id"><button type="button" :data-step-id="step.public_id" class="w-full rounded-2xl border p-4 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500" :class="step.public_id === selectedStepId ? 'border-teal-500 bg-teal-50/80 shadow-sm dark:border-teal-300 dark:bg-teal-400/10' : 'border-slate-200/80 hover:border-teal-300 hover:bg-slate-50 dark:border-slate-800 dark:hover:border-teal-500/50 dark:hover:bg-slate-800/80'" :aria-current="step.public_id === selectedStepId ? 'step' : undefined" @click="selectStep(step)"><div class="flex items-center gap-3"><span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-sm font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">{{ index + 1 }}</span><span class="text-xs font-medium text-teal-700 dark:text-teal-200">{{ phaseLabel(step.phase) }}</span></div><p class="mt-3 line-clamp-2 text-sm font-semibold text-slate-900 dark:text-slate-50">{{ step.title || t('replay.publicStep', { step: step.step }) }}</p><p class="mt-2 line-clamp-2 text-sm leading-5 text-slate-500 dark:text-slate-400">{{ step.summary }}</p></button></li>
          </ol>
          <button v-if="canLoadMore" type="button" class="mt-4 min-h-11 w-full rounded-xl border border-slate-200 px-4 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800" :disabled="loadingMore" @click="loadMoreSteps">{{ loadingMore ? t('common.loadingState') : t('replay.publicLoadMore') }}</button>
          <div v-if="loadMoreError" class="mt-3 flex flex-col items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 sm:flex-row dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-100" role="alert"><span>{{ t('replay.publicLoadMoreFailed') }}</span><button type="button" class="min-h-11 rounded-lg bg-rose-600 px-3 text-sm font-semibold text-white hover:bg-rose-700" @click="loadMoreSteps">{{ t('common.retry') }}</button></div>
          <div v-if="!steps.length && !canLoadMore" class="mt-5 rounded-2xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">{{ t('replay.publicNoSteps') }}</div>
        </section>

        <div id="replay-results" class="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_19rem]" tabindex="-1">
          <section class="min-w-0 rounded-3xl border border-slate-200/80 bg-white/90 p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900/80 md:p-7" aria-labelledby="step-detail-heading">
            <div v-if="selectedStep" class="flex flex-col justify-between gap-3 border-b border-slate-200/70 pb-5 sm:flex-row sm:items-start dark:border-slate-800"><div><p class="text-xs font-semibold uppercase tracking-[0.14em] text-teal-600 dark:text-teal-300">{{ phaseLabel(selectedStep.phase) }}</p><h2 id="step-detail-heading" class="mt-2 text-xl font-bold md:text-2xl">{{ selectedStep.title || t('replay.publicStep', { step: selectedStep.step }) }}</h2><p class="mt-2 text-sm text-slate-500 dark:text-slate-400">{{ t('replay.publicStepOf', { current: currentStepNumber, total: steps.length }) }}<span v-if="selectedStep.created_at"> · {{ formatDate(selectedStep.created_at) }}</span></p></div><span class="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">{{ selectedStep.has_result ? t('showcase.resultEvidence') : t('replay.publicNoResult') }}</span></div>
            <div v-if="detailLoading" class="mt-6 space-y-3" aria-busy="true"><div class="h-6 w-1/2 animate-pulse rounded bg-slate-200 dark:bg-slate-800" /><div class="h-24 animate-pulse rounded-2xl bg-slate-100 dark:bg-slate-800" /></div>
            <div v-else-if="detailError" class="mt-6 rounded-2xl border border-rose-200 bg-rose-50 p-6 text-center dark:border-rose-400/20 dark:bg-rose-400/10" role="alert"><p class="text-sm font-medium">{{ t('replay.publicDetailFailed') }}</p><button type="button" class="mt-4 min-h-11 rounded-xl bg-slate-900 px-4 text-sm font-semibold text-white dark:bg-white dark:text-slate-900" @click="loadStep(selectedStepId)">{{ t('common.retry') }}</button></div>
            <PublicReplayResult v-else-if="selectedStep" class="mt-6" :result="selectedStep.result || {}" />
            <div v-else class="mt-6 rounded-2xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">{{ t('replay.publicNoSteps') }}</div>
            <div v-if="selectedStep?.technical" class="mt-6 rounded-xl bg-slate-50 p-4 text-sm text-slate-600 dark:bg-slate-800/70 dark:text-slate-300"><p class="font-medium">{{ t('replay.publicAdvanced') }}</p><p class="mt-2">{{ t('replay.publicStep', { step: selectedStep.technical.step }) }} · {{ phaseLabel(selectedStep.technical.phase) }}</p></div>
            <div class="mt-7 flex flex-col justify-between gap-3 border-t border-slate-200/70 pt-5 sm:flex-row sm:items-center dark:border-slate-800"><button type="button" class="min-h-11 rounded-xl border border-slate-200 px-4 text-sm font-medium text-slate-600 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700 dark:text-slate-300" :disabled="currentIndex <= 0" @click="selectAdjacent(-1)"><AppIcon name="ArrowLeft" size="xs" class="mr-1.5" aria-hidden="true" />{{ t('replay.publicPrevious') }}</button><button type="button" class="min-h-11 rounded-xl bg-teal-600 px-4 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40 hover:bg-teal-700" :disabled="currentIndex < 0 || currentIndex >= steps.length - 1" @click="selectAdjacent(1)">{{ t('replay.publicNext') }}<AppIcon name="ArrowRight" size="xs" class="ml-1.5" aria-hidden="true" /></button></div>
          </section>

          <aside class="h-fit rounded-3xl border border-slate-200/80 bg-white/90 p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900/80 lg:sticky lg:top-6">
            <p class="text-xs font-semibold uppercase tracking-[0.14em] text-rose-500 dark:text-rose-300">{{ t('replay.publicFinalSummary') }}</p>
            <h2 class="mt-2 text-lg font-bold">{{ finalSummary?.result.title || manifest.workflow.title }}</h2>
            <p class="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{{ t('replay.publicFinalStable') }}</p>
            <PublicReplayResult v-if="finalSummary" class="mt-5" :result="finalSummary.result" compact />
            <div v-else class="mt-5 rounded-xl bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-800/70 dark:text-slate-400">{{ t('replay.notGenerated') }}</div>
            <button type="button" class="mt-6 flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-rose-500 px-4 text-sm font-semibold text-white shadow-lg shadow-rose-500/20 hover:bg-rose-600" @click="goCreate">{{ t('replay.publicStart') }}<AppIcon name="ArrowRight" size="sm" aria-hidden="true" /></button>
          </aside>
        </div>
      </template>
    </main>
  </div>
</template>

<style scoped>
.replay-v2 {
  position: relative;
}

.replay-v2-ambient {
  position: absolute;
  inset: 0 0 auto;
  height: 32rem;
  pointer-events: none;
  background:
    radial-gradient(circle at 10% 4%, rgba(20, 184, 166, 0.1), transparent 28%),
    radial-gradient(circle at 90% 15%, rgba(244, 63, 94, 0.1), transparent 28%);
}

@media (prefers-reduced-motion: reduce) {
  .replay-v2 :deep(*) {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
</style>
