<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import ErrorState from '@/components/ErrorState.vue'
import { ReplaySkeleton } from '@/components/skeletons'
import AuroraBackground from '@/components/showcase/AuroraBackground.vue'
import PublicReplayResult from '@/components/replay/PublicReplayResult.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { vReveal } from '@/directives/reveal'
import { vSpotlight } from '@/directives/spotlight'
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
import { useToastStore } from '@/stores/toast'
import { trackInteraction } from '@/utils/interactionTelemetry'
import { setPublicPageMeta } from '@/utils/publicMeta'

const { t, locale } = useI18n()
const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const toastStore = useToastStore()

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
// Per-button share state: the case-link and step-link copy buttons must not
// share one flag, or copying one flips the other's label to "copied" too.
const caseShareState = ref<'idle' | 'success' | 'error'>('idle')
const stepShareState = ref<'idle' | 'success' | 'error'>('idle')
const firstResultTracked = ref(false)
const loadingMore = ref(false)
const loadMoreError = ref(false)
const stepsExpanded = ref(false)
const stepNotFoundShown = ref<string | null>(null)
const resultExpanded = ref(false)
const copyState = ref<'idle' | 'success' | 'error'>('idle')

const REPLAY_CACHE_VERSION = 1
const REPLAY_CACHE_TTL = 30_000
const REPLAY_CACHE_KEY = 'replay:public-step-cache:v1'
const REPLAY_PAGE_SIZE = 20
let manifestRequestToken = 0
let detailRequestToken = 0
let manifestAbortController: AbortController | null = null
let loadMoreAbortController: AbortController | null = null
let detailAbortController: AbortController | null = null
let prefetchTimer: number | ReturnType<typeof setTimeout> | null = null
const prefetchAbortControllers = new Map<string, AbortController>()

const steps = computed(() => [...(manifest.value?.steps || [])].sort((a, b) => a.step - b.step))
const currentIndex = computed(() => steps.value.findIndex(step => step.public_id === selectedStepId.value))
const currentStepNumber = computed(() => Math.max(currentIndex.value + 1, 1))
const progressPercent = computed(() => {
  if (!steps.value.length || currentIndex.value < 0) return 0
  return Math.round(((currentIndex.value + 1) / steps.value.length) * 100)
})
const caseStatus = computed<PublicCaseStatus>(() => manifest.value?.workflow.status || 'in_progress')
const caseMode = computed(() => manifest.value?.workflow.workflow_mode || 'trend')
const caseStatusLabel = computed(() => t(`showcase.caseStatus.${caseStatus.value}`))
const selectedPhase = computed(() => selectedStep.value?.phase || steps.value.find(step => step.public_id === selectedStepId.value)?.phase || '')
const phaseGroups = computed(() => {
  // RP-05: pick the most recent step with business data (has_result) per phase;
  // fall back to the last step of the phase if none has data.
  const byPhase = new Map<string, PublicReplayStep>()
  for (const step of steps.value) {
    const current = byPhase.get(step.phase)
    if (!current) {
      byPhase.set(step.phase, step)
      continue
    }
    const currentHasData = current.has_result || current.has_business_data
    const stepHasData = step.has_result || step.has_business_data
    if (stepHasData && !currentHasData) byPhase.set(step.phase, step)
    else if (stepHasData === currentHasData && step.step > current.step) byPhase.set(step.phase, step)
  }
  return [...byPhase.values()]
})
const phasesWithoutData = computed(() => {
  const seen = new Set<string>()
  const empty = new Set<string>()
  for (const step of steps.value) {
    if (!seen.has(step.phase)) {
      seen.add(step.phase)
      if (!step.has_result && !step.has_business_data) empty.add(step.phase)
    }
  }
  return empty
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

function cancelPrefetch() {
  if (prefetchTimer !== null && typeof window !== 'undefined') {
    const idleWindow = window as Window & { cancelIdleCallback?: (id: number) => void }
    if (typeof prefetchTimer === 'number' && idleWindow.cancelIdleCallback) idleWindow.cancelIdleCallback(prefetchTimer)
    else window.clearTimeout(prefetchTimer)
  }
  prefetchTimer = null
  prefetchAbortControllers.forEach(controller => controller.abort())
  prefetchAbortControllers.clear()
}

async function prefetchStep(stepId: string) {
  if (!manifest.value || !publicId.value) return
  const technical = viewMode.value === 'all' && isAuthenticated.value
  if (readCachedStep(stepId, technical) || prefetchAbortControllers.has(stepId)) return
  // Manifest already embeds result for key steps — cache without a network hop.
  const embedded = steps.value.find(step => step.public_id === stepId)
  if (embedded?.result && !technical) {
    writeCachedStep(stepId, technical, embedded)
    return
  }
  const controller = new AbortController()
  prefetchAbortControllers.set(stepId, controller)
  try {
    const step = await getPublicReplayCheckpoint(publicId.value, stepId, technical, {
      suppressToast: true,
      signal: controller.signal,
    })
    if (!controller.signal.aborted) writeCachedStep(stepId, technical, step)
  } catch {
    // Prefetch is opportunistic; navigation still owns visible error handling.
  } finally {
    if (prefetchAbortControllers.get(stepId) === controller) prefetchAbortControllers.delete(stepId)
  }
}

function scheduleNextStepPrefetch() {
  cancelPrefetch()
  const next = steps.value[currentIndex.value + 1]
  if (!next || typeof window === 'undefined') return
  const run = () => {
    prefetchTimer = null
    void prefetchStep(next.public_id)
  }
  const idleWindow = window as Window & { requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number }
  if (idleWindow.requestIdleCallback) prefetchTimer = idleWindow.requestIdleCallback(run, { timeout: 700 })
  else prefetchTimer = window.setTimeout(run, 120)
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

function handleStepKeydown(event: KeyboardEvent) {
  if (!steps.value.length) return
  if (event.key === 'Home') {
    event.preventDefault()
    void selectStep(steps.value[0], 'keys')
  } else if (event.key === 'End') {
    event.preventDefault()
    void selectStep(steps.value[steps.value.length - 1], 'keys')
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
    scheduleNextStepPrefetch()
    return
  }
  // Manifest now embeds result on key steps — paint immediately without a round-trip.
  if (manifestStep.result && !technical) {
    selectedStep.value = manifestStep
    writeCachedStep(stepId, technical, manifestStep)
    detailLoading.value = false
    trackInteraction(firstResultTracked.value ? 'replay_select_to_render' : 'replay_first_result_visible', {
      view: viewMode.value,
      cached: false,
      duration_ms: 0,
    })
    firstResultTracked.value = true
    scheduleNextStepPrefetch()
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
    scheduleNextStepPrefetch()
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
  cancelPrefetch()
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
    const requested = queryStep()
    const first = preferredStep(steps.value)
    if (requested && stepNotFoundShown.value !== requested && first?.public_id !== requested) {
      stepNotFoundShown.value = requested
      toastStore.warning(t('replay.stepNotFoundToast'))
    }
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

async function selectStep(step: PublicReplayStep, method: 'click' | 'keys' | 'prev' | 'next' = 'click') {
  if (step.public_id === selectedStepId.value && selectedStep.value) return
  selectedStepId.value = step.public_id
  trackInteraction('replay_step_select', { view: viewMode.value, has_result: step.has_result })
  trackInteraction('replay_step_navigate', { method, has_result: step.has_result })
  await loadStep(step.public_id)
  await nextTick()
  // RP-06: move focus to the result title so keyboard users hear/see the update.
  document.getElementById('step-detail-heading')?.focus()
  void router.replace({ query: { ...route.query, step: step.public_id } }).catch(() => undefined)
}

async function selectAdjacent(direction: -1 | 1) {
  const nextIndex = currentIndex.value + direction
  const step = steps.value[nextIndex]
  if (step) await selectStep(step, direction > 0 ? 'next' : 'prev')
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
  trackInteraction('replay_cta_click', { auth_state: isAuthenticated.value ? 'authenticated' : 'guest', position: 'hero' })
  if (isAuthenticated.value) void router.push({ path: '/start', query: { source: 'replay', mode: caseMode.value } })
  else void router.push({ name: 'login', query: { redirect: `/start?source=replay&mode=${caseMode.value}` } })
}

// Secondary entry: authenticated visitors may still want their existing
// workspace rather than starting a new creation. Kept distinct from the main
// /start CTA so the "回到工作台" label never points at /start (PRD D2).
function goWorkspace() {
  trackInteraction('replay_cta_click', { auth_state: isAuthenticated.value ? 'authenticated' : 'guest', position: 'nav' })
  if (isAuthenticated.value) void router.push({ name: 'dashboard' })
  else void router.push({ name: 'login', query: { redirect: '/dashboard' } })
}

function buildShareHref(step = false): string {
  const query: Record<string, string> = {}
  const fromRaw = route.query.from
  const from = typeof fromRaw === 'string' && fromRaw.trim() ? fromRaw.trim() : 'showcase'
  query.from = from
  if (step && selectedStepId.value) query.step = selectedStepId.value
  const resolved = router.resolve({
    name: 'replay',
    params: { publicId: publicId.value },
    query,
  })
  return typeof window !== 'undefined'
    ? new URL(resolved.href, window.location.origin).toString()
    : resolved.href
}

async function writeClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // fall through to execCommand path
  }
  try {
    const el = document.createElement('textarea')
    el.value = text
    el.setAttribute('readonly', '')
    el.style.position = 'fixed'
    el.style.left = '-9999px'
    document.body.appendChild(el)
    el.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(el)
    return ok
  } catch {
    return false
  }
}

let shareResetTimer: ReturnType<typeof setTimeout> | null = null

async function copyLink(step = false) {
  const state = step ? stepShareState : caseShareState
  state.value = 'idle'
  if (shareResetTimer) {
    clearTimeout(shareResetTimer)
    shareResetTimer = null
  }
  const href = buildShareHref(step)
  const title = manifest.value?.workflow.title || t('replay.title')
  // Prefer native share sheet on mobile when available (still falls back to copy).
  const canShare =
    typeof navigator !== 'undefined'
    && typeof navigator.share === 'function'
    && (!step || !!selectedStepId.value)
  if (canShare && /Mobi|Android|iPhone/i.test(navigator.userAgent || '')) {
    try {
      await navigator.share({
        title,
        text: step
          ? t('replay.publicShareStepText', { title })
          : t('replay.publicShareCaseText', { title }),
        url: href,
      })
      state.value = 'success'
      trackInteraction(step ? 'replay_step_link_copy' : 'replay_case_link_copy', {
        has_step: step,
        method: 'share',
      })
      trackInteraction('replay_share', { has_step: step, method: 'share' })
      shareResetTimer = setTimeout(() => {
        if (state.value === 'success') state.value = 'idle'
      }, 2200)
      return
    } catch {
      // User cancelled share sheet or share failed — fall through to clipboard.
    }
  }
  try {
    const ok = await writeClipboard(href)
    if (!ok) throw new Error('clipboard unavailable')
    state.value = 'success'
    toastStore.success(
      step ? t('replay.publicSharedStep') : t('replay.publicSharedCase'),
      href.length > 72 ? `${href.slice(0, 72)}…` : href,
    )
    trackInteraction(step ? 'replay_step_link_copy' : 'replay_case_link_copy', {
      has_step: step,
      method: 'clipboard',
    })
    trackInteraction('replay_share', { has_step: step, method: 'clipboard' })
    shareResetTimer = setTimeout(() => {
      if (state.value === 'success') state.value = 'idle'
    }, 2200)
  } catch {
    state.value = 'error'
    toastStore.warning(t('replay.publicShareFailed'), href)
    trackInteraction('replay_share_error', { has_step: step })
    shareResetTimer = setTimeout(() => {
      if (state.value === 'error') state.value = 'idle'
    }, 2800)
  }
}

// RP-03: narrative layer helpers.
function phaseImportance(phase: string | undefined): string {
  if (!phase) return ''
  const key = `replay.phaseImportance.${phase}`
  const translated = t(key)
  return translated === key ? '' : translated
}

function toggleResultExpanded() {
  resultExpanded.value = !resultExpanded.value
  trackInteraction('replay_result_expand', { has_result: Boolean(selectedStep.value?.has_result) })
}

async function copyResult() {
  const result = selectedStep.value?.result
  if (!result) return
  try {
    await navigator.clipboard.writeText(JSON.stringify(result, null, 2))
    copyState.value = 'success'
    trackInteraction('replay_result_copy', { has_result: true })
    setTimeout(() => { copyState.value = 'idle' }, 2000)
  } catch {
    copyState.value = 'error'
  }
}

watch(() => route.query.step, (value) => {
  if (typeof value === 'string' && value !== selectedStepId.value) {
    if (stepNotFoundShown.value !== value) stepNotFoundShown.value = null
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
  cancelPrefetch()
})

onMounted(() => {
  if (!authStore.isInitialized) void authStore.initialize()
  setPublicPageMeta({ title: t('replay.seo.title'), description: t('replay.seo.description'), type: 'article' })
  void loadReplay()
})

watch(locale, () => {
  setPublicPageMeta({ title: t('replay.seo.title'), description: t('replay.seo.description'), type: 'article' })
})
</script>

<template>
  <div class="dark-explicit replay-v2 min-h-screen overflow-x-clip bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-50">
    <AuroraBackground variant="teal" />
    <a href="#replay-results" class="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-modal focus:rounded-lg focus:bg-slate-900 focus:px-4 focus:py-3 focus:text-sm focus:font-semibold focus:text-white">{{ t('common.skipToContent') }}</a>
    <nav class="dark-explicit glass-panel relative z-sticky border-b border-slate-200/60 dark:border-slate-800/60">
      <div class="mx-auto flex min-h-16 max-w-6xl items-center justify-between gap-3 px-4 md:px-8">
        <div class="flex min-w-0 items-center gap-3">
          <button type="button" class="dark-explicit flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-slate-600 transition hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 dark:text-slate-300 dark:hover:bg-slate-800" :aria-label="t('replay.publicBack')" @click="goBack"><AppIcon name="ArrowLeft" size="sm" aria-hidden="true" /></button>
          <div class="min-w-0"><p class="truncate text-sm font-bold">{{ manifest?.workflow.title || t('replay.title') }}</p><div class="mt-0.5 flex items-center gap-2"><span class="dark-explicit text-xs text-slate-500 dark:text-slate-400">{{ t('replay.title') }}</span><span v-if="!manifest?.workflow.replay_available" class="dark-explicit rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-400/10 dark:text-amber-200">{{ t('replay.noFullReplay') }}</span><span class="dark-explicit rounded-full px-2 py-0.5 text-xs font-medium" :class="caseStatus === 'completed' ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-200' : 'bg-sky-50 text-sky-700 dark:bg-sky-400/10 dark:text-sky-200'">{{ caseStatusLabel }}</span></div></div>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <button type="button" class="dark-explicit hidden min-h-11 items-center rounded-xl border border-slate-200 px-3 text-sm font-medium text-slate-600 transition hover:bg-slate-50 sm:inline-flex dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800" @click="copyLink(false)"><AppIcon name="Copy" size="xs" class="mr-1.5" aria-hidden="true" />{{ caseShareState === 'success' ? t('replay.publicShared') : caseShareState === 'error' ? t('replay.publicShareFailed') : t('replay.publicShareCase') }}</button>
          <button type="button" class="min-h-11 rounded-xl bg-rose-600 px-3 text-sm font-semibold text-white shadow-lg shadow-rose-600/25 transition hover:-translate-y-0.5 hover:bg-rose-700 hover:shadow-xl hover:shadow-rose-600/30" @click="isAuthenticated ? goWorkspace() : goCreate">{{ isAuthenticated ? t('replay.publicWorkspace') : t('replay.publicStart') }}</button>
          <ThemeToggle class="shrink-0" />
        </div>
      </div>
    </nav>

    <main class="relative z-sticky mx-auto max-w-6xl px-4 py-6 md:px-8 md:py-10">
      <ReplaySkeleton v-if="loading" />
      <section v-else-if="notFound" class="dark-explicit rounded-3xl border border-dashed border-slate-300 bg-white/80 p-10 text-center dark:border-slate-700 dark:bg-slate-900/80" role="alert"><AppIcon name="HelpCircle" size="lg" variant="cyan" aria-hidden="true" /><h1 class="mt-4 text-xl font-semibold">{{ t('replay.threadNotFound') }}</h1><p class="dark-explicit mt-2 text-sm text-slate-500 dark:text-slate-400">{{ t('replay.threadNotFoundDesc') }}</p><button type="button" class="mt-5 min-h-11 rounded-xl bg-slate-900 px-4 text-sm font-semibold text-white dark:bg-white dark:text-slate-900" @click="goBack">{{ t('replay.publicBack') }}</button></section>
      <!-- INF-01: shared presentational ErrorState (no store binding on public pages) -->
      <ErrorState
        v-else-if="manifestError"
        variant="api"
        :title="t('replay.publicLoadFailed')"
        :message="t('replay.publicLoadFailedDesc')"
        :retrying="retrying"
        hide-dismiss
        @retry="retryReplay"
      />
      <template v-else-if="manifest">
        <header class="replay-enter flex flex-col justify-between gap-5 md:flex-row md:items-end" style="--enter-delay: 0ms">
          <div class="min-w-0"><p class="dark-explicit text-xs font-semibold uppercase tracking-[0.14em] text-teal-700 dark:text-teal-300">{{ t('replay.publicKeySteps') }}</p><h1 class="mt-2 max-w-3xl text-2xl font-bold leading-tight md:text-4xl">{{ manifest.workflow.title }}</h1><p class="dark-explicit mt-3 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">{{ manifest.workflow.summary }}</p></div>
          <div class="flex shrink-0 items-center gap-2"><button type="button" class="dark-explicit min-h-11 rounded-xl border border-slate-200 px-3 text-sm font-medium text-slate-600 transition hover:bg-white dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-900" @click="copyLink(true)"><AppIcon name="Copy" size="xs" class="mr-1.5" aria-hidden="true" />{{ stepShareState === 'success' ? t('replay.publicShared') : stepShareState === 'error' ? t('replay.publicShareFailed') : t('replay.publicShareStep') }}</button><span class="dark-explicit rounded-full bg-slate-100 px-3 py-2 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">{{ caseStatusLabel }}</span></div>
        </header>
        <p class="sr-only" aria-live="polite">{{ selectedStep ? t('replay.publicSelectedStep', { step: selectedStep.step, title: selectedStep.title || t('replay.publicStep', { step: selectedStep.step }) }) : '' }}</p>

        <section v-reveal class="glass-panel mt-7 rounded-3xl p-4 shadow-sm md:p-5" aria-labelledby="replay-steps-heading">
          <div class="flex flex-col justify-between gap-3 sm:flex-row sm:items-center"><div><h2 id="replay-steps-heading" class="text-base font-semibold">{{ t('replay.publicKeySteps') }}</h2><p class="dark-explicit mt-1 text-sm text-slate-500 dark:text-slate-400">{{ t('replay.publicStepCount', { key: manifest.key_step_count, total: viewMode === 'all' ? manifest.total_steps : manifest.key_step_count }) }}</p></div><div class="flex items-center gap-2"><button type="button" class="dark-explicit min-h-11 rounded-xl px-3 text-sm font-medium transition" :class="viewMode === 'key' ? 'bg-slate-900 text-white shadow-md shadow-slate-900/20 dark:bg-white dark:text-slate-900' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'" :aria-pressed="viewMode === 'key'" @click="toggleView('key')">{{ t('replay.publicKeySteps') }}</button><button type="button" class="dark-explicit min-h-11 rounded-xl px-3 text-sm font-medium transition" :class="viewMode === 'all' ? 'bg-slate-900 text-white shadow-md shadow-slate-900/20 dark:bg-white dark:text-slate-900' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'" :aria-pressed="viewMode === 'all'" @click="toggleView('all')">{{ t('replay.publicAllSteps') }}</button></div></div>
          <p class="sr-only">{{ t('replay.progressLabel') }}: {{ progressPercent }}%</p>
          <button type="button" class="dark-explicit mt-3 flex min-h-11 w-full items-center justify-between rounded-xl border border-slate-200 px-4 text-sm font-medium text-slate-700 transition hover:bg-slate-50 md:hidden dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800" :aria-expanded="stepsExpanded" aria-controls="replay-steps-content" @click="stepsExpanded = !stepsExpanded"><span>{{ t('replay.publicStepsToggle', { current: currentStepNumber, total: steps.length }) }}</span><AppIcon :name="stepsExpanded ? 'ChevronUp' : 'ChevronDown'" size="sm" aria-hidden="true" /></button>
          <div id="replay-steps-content" :class="stepsExpanded ? 'block' : 'hidden'" class="md:block">
          <p class="dark-explicit mt-2 text-xs text-slate-500 dark:text-slate-400" v-if="viewMode === 'key' && manifest.technical_steps_available && !isAuthenticated">{{ t('replay.publicLoginForAdvanced') }}</p>
          <nav v-if="phaseGroups.length > 1" class="dark-explicit phase-nav-fade mt-5 overflow-x-auto border-y border-slate-200/70 py-3 dark:border-slate-800" :aria-label="t('replay.publicPhaseNavigation')"><ol class="flex min-w-max items-center gap-2"><li v-for="(phase, index) in phaseGroups" :key="phase.phase" class="phase-item"><button type="button" :data-phase-index="index" :tabindex="selectedPhase === phase.phase ? 0 : -1" :disabled="phasesWithoutData.has(phase.phase)" :title="phasesWithoutData.has(phase.phase) ? t('replay.phaseNoData') : undefined" class="dark-explicit min-h-11 rounded-xl px-3 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 disabled:cursor-not-allowed disabled:opacity-40" :class="selectedPhase === phase.phase ? 'bg-gradient-to-r from-teal-600 to-cyan-500 text-white shadow-md shadow-teal-500/40 dark:from-teal-500 dark:to-cyan-400 dark:text-slate-950' : phasesWithoutData.has(phase.phase) ? 'text-slate-400 dark:text-slate-600' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'" :aria-current="selectedPhase === phase.phase ? 'step' : undefined" :aria-disabled="phasesWithoutData.has(phase.phase)" @click="selectPhase(phase)" @keydown="handlePhaseKeydown($event, index)">{{ phaseLabel(phase.phase) }}</button></li></ol></nav>
          <div v-if="steps.length" class="replay-timeline relative mt-6">
            <div class="timeline-spine" aria-hidden="true"><div class="timeline-fill" :style="{ height: `${progressPercent}%` }" /></div>
            <ol class="space-y-3" :aria-label="t('replay.publicStepsLabel')">
              <li v-for="(step, index) in steps" :key="step.public_id" v-reveal="(index % 6) * 50" class="relative"><span class="timeline-node" :class="step.public_id === selectedStepId ? 'timeline-node-active' : index < currentIndex ? 'timeline-node-done' : ''" aria-hidden="true">{{ index + 1 }}</span><button v-spotlight type="button" :data-step-id="step.public_id" class="dark-explicit w-full rounded-2xl border p-4 pl-5 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500" :class="step.public_id === selectedStepId ? 'border-teal-500 bg-teal-50/80 shadow-lg shadow-teal-500/25 ring-1 ring-teal-400/50 dark:border-teal-300 dark:bg-teal-400/10' : 'border-slate-200/80 bg-white/60 hover:-translate-y-0.5 hover:border-teal-300 hover:bg-slate-50 hover:shadow-md dark:border-slate-800 dark:bg-slate-900/40 dark:hover:border-teal-500/50 dark:hover:bg-slate-800/80'" :aria-current="step.public_id === selectedStepId ? 'step' : undefined" @click="selectStep(step)" @keydown="handleStepKeydown($event)"><p class="dark-explicit text-xs font-medium text-teal-700 dark:text-teal-200">{{ phaseLabel(step.phase) }}</p><p class="dark-explicit mt-1.5 line-clamp-2 text-sm font-semibold text-slate-900 dark:text-slate-50">{{ step.title || t('replay.publicStep', { step: step.step }) }}</p><p class="dark-explicit mt-1 line-clamp-2 text-sm leading-5 text-slate-500 dark:text-slate-400">{{ step.summary }}</p></button></li>
            </ol>
          </div>
          <button v-if="canLoadMore" type="button" class="dark-explicit mt-4 min-h-11 w-full rounded-xl border border-slate-200 px-4 text-sm font-medium text-slate-600 transition hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800" :disabled="loadingMore" @click="loadMoreSteps">{{ loadingMore ? t('common.loadingState') : t('replay.publicLoadMore') }}</button>
          <div v-if="loadMoreError" class="dark-explicit mt-3 flex flex-col items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 sm:flex-row dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-100" role="alert"><span>{{ t('replay.publicLoadMoreFailed') }}</span><button type="button" class="min-h-11 rounded-lg bg-rose-600 px-3 text-sm font-semibold text-white hover:bg-rose-700" @click="loadMoreSteps">{{ t('common.retry') }}</button></div>
          <div v-if="!steps.length && !canLoadMore" class="dark-explicit mt-5 rounded-2xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">{{ t('replay.publicNoSteps') }}</div>
          </div>
        </section>

        <div id="replay-results" v-reveal class="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_19rem]" tabindex="-1">
          <section class="glass-panel min-w-0 rounded-3xl p-5 shadow-sm md:p-7" aria-labelledby="step-detail-heading">
            <div :key="selectedStepId || 'none'" class="replay-swap">
              <div v-if="selectedStep" class="dark-explicit flex flex-col justify-between gap-3 border-b border-slate-200/70 pb-5 sm:flex-row sm:items-start dark:border-slate-800"><div class="min-w-0"><p class="dark-explicit text-xs font-semibold uppercase tracking-[0.14em] text-teal-700 dark:text-teal-300">{{ phaseLabel(selectedStep.phase) }}</p><h2 id="step-detail-heading" class="mt-2 text-xl font-bold md:text-2xl" tabindex="-1">{{ selectedStep.title || t('replay.publicStep', { step: selectedStep.step }) }}</h2><p class="dark-explicit mt-2 text-sm text-slate-500 dark:text-slate-400">{{ t('replay.publicStepOf', { current: currentStepNumber, total: steps.length }) }}<span v-if="selectedStep.created_at"> · {{ formatDate(selectedStep.created_at) }}</span></p></div><span class="dark-explicit rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">{{ selectedStep.has_result ? t('showcase.resultEvidence') : t('replay.publicNoResult') }}</span></div>
              <p v-if="selectedStep?.summary" class="dark-explicit mt-4 text-sm leading-6 text-slate-600 dark:text-slate-300">{{ selectedStep.summary }}</p>
              <p v-if="phaseImportance(selectedStep?.phase)" class="dark-explicit mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{{ phaseImportance(selectedStep?.phase) }}</p>
              <div v-if="selectedStep?.result" class="mt-3 flex items-center gap-2"><button type="button" class="dark-explicit inline-flex min-h-11 items-center gap-1.5 rounded-xl border border-slate-200 px-3 text-xs font-medium text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800" @click="toggleResultExpanded"><AppIcon :name="resultExpanded ? 'ChevronUp' : 'ChevronDown'" size="xs" aria-hidden="true" />{{ resultExpanded ? t('replay.resultCollapse') : t('replay.resultExpand') }}</button><button type="button" class="dark-explicit inline-flex min-h-11 items-center gap-1.5 rounded-xl border border-slate-200 px-3 text-xs font-medium text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800" @click="copyResult">{{ copyState === 'success' ? t('replay.copied') : t('replay.copyResult') }}</button></div>
              <div v-if="detailLoading" class="mt-6 space-y-3" aria-busy="true"><div class="dark-explicit h-6 w-1/2 animate-pulse rounded bg-slate-200 dark:bg-slate-800" /><div class="dark-explicit h-24 animate-pulse rounded-2xl bg-slate-100 dark:bg-slate-800" /></div>
              <div v-else-if="detailError" class="dark-explicit mt-6 rounded-2xl border border-rose-200 bg-rose-50 p-6 text-center dark:border-rose-400/20 dark:bg-rose-400/10" role="alert"><p class="text-sm font-medium">{{ t('replay.publicDetailFailed') }}</p><button type="button" class="mt-4 min-h-11 rounded-xl bg-slate-900 px-4 text-sm font-semibold text-white dark:bg-white dark:text-slate-900" @click="loadStep(selectedStepId)">{{ t('common.retry') }}</button></div>
              <PublicReplayResult v-else-if="selectedStep" class="mt-6" :result="selectedStep.result || {}" />
              <div v-else class="dark-explicit mt-6 rounded-2xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">{{ t('replay.publicNoSteps') }}</div>
              <div v-if="selectedStep?.technical" class="dark-explicit mt-6 rounded-xl bg-slate-50 p-4 text-sm text-slate-600 dark:bg-slate-800/70 dark:text-slate-300"><p class="font-medium">{{ t('replay.publicAdvanced') }}</p><p class="mt-2">{{ t('replay.publicStep', { step: selectedStep.technical.step }) }} · {{ phaseLabel(selectedStep.technical.phase) }}</p></div>
              <div class="dark-explicit mt-7 flex flex-col justify-between gap-3 border-t border-slate-200/70 pt-5 sm:flex-row sm:items-center dark:border-slate-800"><button type="button" class="min-h-11 rounded-xl border border-slate-200 px-4 text-sm font-medium text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700 dark:text-slate-300" :disabled="currentIndex <= 0" :title="currentIndex <= 0 ? t('replay.boundaryStart') : undefined" :aria-disabled="currentIndex <= 0" @click="selectAdjacent(-1)"><AppIcon name="ArrowLeft" size="xs" class="mr-1.5" aria-hidden="true" />{{ t('replay.publicPrevious') }}</button><button type="button" class="min-h-11 rounded-xl bg-gradient-to-r from-teal-600 to-cyan-600 px-4 text-sm font-semibold text-white shadow-lg shadow-teal-600/40 transition hover:-translate-y-0.5 hover:shadow-xl hover:shadow-teal-600/50 disabled:cursor-not-allowed disabled:opacity-40" :disabled="currentIndex < 0 || currentIndex >= steps.length - 1" :title="currentIndex >= steps.length - 1 ? t('replay.boundaryEnd') : undefined" :aria-disabled="currentIndex < 0 || currentIndex >= steps.length - 1" @click="selectAdjacent(1)">{{ t('replay.publicNext') }}<AppIcon name="ArrowRight" size="xs" class="ml-1.5" aria-hidden="true" /></button></div>
            </div>
          </section>

          <aside class="h-fit lg:sticky lg:top-6">
            <div class="border-beam rounded-3xl shadow-lg shadow-slate-900/5">
              <div class="glass-panel rounded-3xl p-5">
                <p class="dark-explicit text-xs font-semibold uppercase tracking-[0.14em] text-rose-600 dark:text-rose-300">{{ t('replay.publicFinalSummary') }}</p>
                <h2 class="mt-2 text-lg font-bold">{{ finalSummary?.result.title || manifest.workflow.title }}</h2>
                <p class="dark-explicit mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{{ t('replay.publicFinalStable') }}</p>
                <PublicReplayResult v-if="finalSummary" class="mt-5" :result="finalSummary.result" compact />
                <div v-else class="dark-explicit mt-5 rounded-xl bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-800/70 dark:text-slate-400">{{ t('replay.notGenerated') }}</div>
                <button type="button" class="mt-6 flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-rose-600 via-rose-500 to-orange-500 bg-[length:180%_180%] px-4 text-sm font-semibold text-white shadow-lg shadow-rose-600/40 transition hover:-translate-y-0.5 hover:shadow-xl hover:shadow-rose-600/50 animate-gradient-flow" @click="goCreate">{{ t('replay.publicStart') }}<AppIcon name="ArrowRight" size="sm" aria-hidden="true" /></button>
              </div>
            </div>
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

/* Header entrance — delay comes from the inline --enter-delay var. */
.replay-enter {
  opacity: 0;
  animation: replay-rise 0.7s cubic-bezier(0.22, 1, 0.36, 1) forwards;
  animation-delay: var(--enter-delay, 0ms);
}

@keyframes replay-rise {
  from {
    opacity: 0;
    transform: translateY(24px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Step-detail swap — replays each time the keyed wrapper remounts. */
.replay-swap {
  animation: replay-swap-in 0.45s cubic-bezier(0.22, 1, 0.36, 1);
}

@keyframes replay-swap-in {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Vertical replay timeline — the spine doubles as the progress indicator. */
.replay-timeline {
  padding-left: 2.9rem;
}

.timeline-spine {
  position: absolute;
  top: 0.75rem;
  bottom: 0.75rem;
  left: 1.2rem;
  width: 3px;
  border-radius: 9999px;
  background: rgb(226 232 240);
  overflow: hidden;
}

.dark .timeline-spine {
  background: rgb(30 41 59);
}

.timeline-fill {
  width: 100%;
  border-radius: inherit;
  background: linear-gradient(to bottom, #14b8a6, #22d3ee, #34d399);
  box-shadow: 0 0 12px rgb(20 184 166 / 0.55);
  transition: height 0.5s cubic-bezier(0.22, 1, 0.36, 1);
}

.timeline-node {
  position: absolute;
  top: 1.1rem;
  left: -1.66rem;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 9999px;
  font-size: 0.8rem;
  font-weight: 700;
  background: #fff;
  border: 2px solid rgb(203 213 225);
  color: rgb(100 116 139);
  transition: border-color 0.3s ease, background-color 0.3s ease, box-shadow 0.3s ease;
}

.dark .timeline-node {
  background: rgb(15 23 42);
  border-color: rgb(51 65 85);
  color: rgb(148 163 184);
}

.timeline-node-done {
  border-color: rgb(20 184 166 / 0.55);
  background: rgb(240 253 250);
  color: rgb(15 118 110);
}

.dark .timeline-node-done {
  background: rgb(20 184 166 / 0.12);
  color: rgb(94 234 212);
}

.timeline-node-active {
  background: linear-gradient(135deg, #0d9488, #22d3ee);
  border-color: transparent;
  color: #fff;
  box-shadow: 0 0 0 4px rgb(20 184 166 / 0.22), 0 0 18px rgb(20 184 166 / 0.55);
}

/* Pipeline connectors between the phase pills. */
.phase-item {
  display: flex;
  align-items: center;
}

.phase-item:not(:last-child)::after {
  content: '';
  width: 1rem;
  height: 2px;
  border-radius: 9999px;
  background: linear-gradient(to right, rgb(20 184 166 / 0.5), rgb(139 92 246 / 0.35));
}

/* RP-06: edge fade on horizontally-scrollable phase nav so off-screen items read as scrollable. */
.phase-nav-fade {
  -webkit-mask-image: linear-gradient(to right, transparent, #000 1.5rem, #000 calc(100% - 1.5rem), transparent);
  mask-image: linear-gradient(to right, transparent, #000 1.5rem, #000 calc(100% - 1.5rem), transparent);
}

@media (prefers-reduced-motion: reduce) {
  .replay-enter {
    animation: none;
    opacity: 1;
  }

  .replay-swap {
    animation: none;
  }

  .timeline-fill,
  .timeline-node {
    transition: none;
  }

  .replay-v2 .animate-pulse {
    animation: none !important;
  }

  .replay-v2 button,
  .replay-v2 a {
    transition-duration: 100ms !important;
  }
}
</style>
