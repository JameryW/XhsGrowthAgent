<script setup lang="ts">
import { useRouter, useRoute } from 'vue-router'
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import PreLaunchChecklist from '@/components/PreLaunchChecklist.vue'
import WorkflowStartForm from '@/components/WorkflowStartForm.vue'
import ConfirmStartModal from '@/components/ConfirmStartModal.vue'
import type { WorkflowConfig, WorkflowMode } from '@/components/WorkflowStartForm.vue'
import { useAccountsStore, useWorkflowStore } from '@/stores'
import { prefetchAgentTuiChunk } from '@/api/agent'
import { prefetchRouteChunk } from '@/utils/routePrefetch'

const { t } = useI18n()

const router = useRouter()
const route = useRoute()
const workflowStore = useWorkflowStore()
const accountsStore = useAccountsStore()
const isStarting = ref(false)
const showConfirm = ref(false)
const startFormRef = ref<InstanceType<typeof WorkflowStartForm> | null>(null)
const checklistRef = ref<InstanceType<typeof PreLaunchChecklist> | null>(null)

// Pre-filled topic from analytics
const prefilledTopic = ref<string | null>(null)
const prefilledNiche = computed(() => {
  const niche = route.query.niche
  return typeof niche === 'string' && niche.trim() ? niche : undefined
})

// Form state
const formConfig = ref<WorkflowConfig>({
  accountId: '',
  phase: 'scouting',
  dryRun: false,
  autoPublish: false,
  niche: '母婴',
  workflowMode: 'trend' as WorkflowMode,
})

// ConfirmStartModal only receives trend/brief (free mode never opens it).
// Narrow the form's WorkflowMode to the modal's strict prop type.
const confirmWorkflowMode = computed<'trend' | 'brief'>(() =>
  formConfig.value.workflowMode === 'brief' ? 'brief' : 'trend'
)
const selectedAccountName = computed(() =>
  accountsStore.accounts.find((account) => account.id === formConfig.value.accountId)?.name || ''
)
const selectedAccountNiche = computed(() =>
  accountsStore.accounts.find((account) => account.id === formConfig.value.accountId)?.niche?.trim() || formConfig.value.niche
)
const hasSelectedAccount = computed(() => Boolean(formConfig.value.accountId && selectedAccountName.value))

// Surface required-check failures near the primary CTA (hint only, no gating).
const checklistBlocked = computed(() => checklistRef.value?.readiness?.status === 'blocked')

const handleAccountChange = (accountId: string) => {
  // Keep the summary Hero in sync with the form's internal selection. The form
  // remains the source of truth for the complete submitted configuration.
  formConfig.value.accountId = accountId
}

// Check for topic and niche query params from analytics
onMounted(() => {
  // Prefetch free-mode TUI + post-start dashboard while user fills the form.
  prefetchAgentTuiChunk()
  void prefetchRouteChunk('dashboard')
  const topic = route.query.topic as string
  const niche = route.query.niche as string
  if (topic) {
    prefilledTopic.value = topic
  }
  if (niche) {
    formConfig.value.niche = niche
  }
})

const goToDashboard = () => {
  void prefetchRouteChunk('dashboard')
  router.push('/dashboard')
}

const goToHistory = () => {
  void prefetchRouteChunk('history')
  router.push('/history')
}

// Single submit entry: form emit('submit') → getConfig → branch by mode.
// Async so the free branch can guard against rapid double-clicks (router.push
// is a Promise; isStarting disables the submit button via :is-loading while
// the navigation is in flight, mirroring the trend/brief confirmStart guard).
const handleSubmit = async () => {
  if (startFormRef.value) {
    formConfig.value = startFormRef.value.getConfig()
  }
  // Trend/brief confirm dialog is about to open — warm dashboard for after start.
  if (formConfig.value.workflowMode !== 'free') {
    void prefetchRouteChunk('dashboard')
  }
  if (formConfig.value.workflowMode === 'free') {
    isStarting.value = true
    try {
      // Ensure chunk is warm before navigation (no-op if already cached).
      prefetchAgentTuiChunk()
      const query: Record<string, string> = { mode: 'free' }
      // Free Creation is a goal hand-off, not a trend topic. Keep the legacy
      // topic query as a read-only fallback so old bookmarks still work.
      const goal = formConfig.value.goal
        || prefilledTopic.value
        || (route.query.goal as string)
        || (route.query.topic as string)
      const niche = formConfig.value.niche || (route.query.niche as string)
      if (goal) query.goal = goal
      if (niche) query.niche = niche
      if (formConfig.value.accountId) query.account_id = formConfig.value.accountId
      await router.push({ name: 'tui', query })
    } finally {
      isStarting.value = false
    }
    return
  }
  showConfirm.value = true
}

const confirmStart = async () => {
  // ConfirmStartModal is only shown for trend/brief (free mode returns early in handleSubmit),
  // but narrow the type here so the API request type stays strict (trend|brief only).
  const mode = formConfig.value.workflowMode
  if (mode === 'free') return
  isStarting.value = true
  try {
    const result = await workflowStore.startWorkflow(
      formConfig.value.accountId,
      formConfig.value.phase,
      {
        dryRun: formConfig.value.dryRun,
        autoPublish: formConfig.value.autoPublish,
        topic: formConfig.value.topic,
        niche: formConfig.value.niche,
        workflowMode: mode,
        briefText: formConfig.value.briefText,
      }
    )
    // If a PDF was queued before the workflow started, upload it now
    const threadId = result?.thread_id
    if (threadId && threadId !== 'pending' && startFormRef.value?.pendingPdfFile) {
      await startFormRef.value.uploadPendingPdf(threadId)
    }
    showConfirm.value = false
    // Chunk should already be warm from onMounted; ensure before navigate.
    void prefetchRouteChunk('dashboard')
    router.push('/dashboard')
  } finally {
    isStarting.value = false
  }
}
</script>

<template>
  <div class="home-page min-h-[80vh] flex flex-col justify-center">
    <div class="w-full space-y-4 md:space-y-6">
      <!-- First-screen orientation: explain the job before asking for configuration. -->
      <section class="relative overflow-hidden rounded-2xl border border-slate-200/70 bg-gradient-to-br from-white via-rose-50/70 to-cyan-50/70 p-5 shadow-sm md:rounded-3xl md:p-8 dark:border-slate-700/60 dark:from-slate-900/95 dark:via-slate-900/90 dark:to-slate-950/95 dark-explicit" aria-labelledby="home-welcome-title">
        <div class="pointer-events-none absolute -right-16 -top-20 h-48 w-48 rounded-full bg-neon-pink/10 blur-3xl" aria-hidden="true" />
        <div class="pointer-events-none absolute -bottom-24 right-1/3 h-48 w-48 rounded-full bg-neon-cyan/10 blur-3xl" aria-hidden="true" />
        <div class="relative grid gap-5 md:grid-cols-[1fr_auto] md:items-end">
          <div class="max-w-2xl">
            <p class="mb-2 text-[10px] font-bold uppercase tracking-[0.2em] text-neon-pinkDark">{{ t('home.eyebrow') }}</p>
            <h1 id="home-welcome-title" class="text-2xl font-bold tracking-tight text-slate-800 md:text-4xl">{{ t('home.welcomeTitle') }}</h1>
            <p class="mt-2 max-w-xl text-sm leading-6 text-slate-500 md:text-base">{{ t('home.welcomeSubtitle') }}</p>
          </div>

          <div class="flex min-w-0 items-center gap-3 rounded-2xl border border-white/80 bg-white/80 p-3 shadow-sm backdrop-blur-sm md:min-w-[250px] dark:border-slate-700/70 dark:bg-slate-900/70 dark-explicit">
            <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-neon-cyan to-neon-green shadow-neon-cyan-sm">
              <AppIcon name="UserCheck" size="md" variant="white" aria-hidden="true" />
            </div>
            <div class="min-w-0 flex-1">
              <p class="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{{ t('home.currentContext') }}</p>
              <p class="truncate text-sm font-bold text-slate-700">{{ selectedAccountName || t('home.noAccountSelected') }}</p>
              <p class="truncate text-xs text-slate-400">
                {{ hasSelectedAccount ? t('home.accountNiche', { niche: selectedAccountNiche }) : t('home.accountPending') }}
              </p>
            </div>
            <span v-if="hasSelectedAccount" class="shrink-0 rounded-full bg-emerald-50 px-2 py-1 text-[10px] font-bold text-emerald-600">{{ t('home.readyBadge') }}</span>
          </div>
        </div>
      </section>

      <!-- Pre-filled topic from analytics -->
      <div v-if="prefilledTopic" class="p-3 md:p-4 rounded-lg liquid-glass-teal liquid-glass-hover flex items-center gap-2">
        <AppIcon name="Sparkles" size="sm" variant="cyan" />
        <div class="flex-1 min-w-0">
          <span class="text-[10px] md:text-xs text-teal-500 font-medium">{{ t('home.recommendedTopic') }}</span>
          <p class="text-xs md:text-sm text-teal-700 font-semibold truncate">{{ prefilledTopic }}</p>
        </div>
        <button
          type="button"
          @click="prefilledTopic = null"
          class="min-h-11 min-w-11 text-teal-400 hover:text-teal-600 transition-colors flex-shrink-0 inline-flex items-center justify-center"
          :aria-label="t('common.close')"
        >
          <AppIcon name="X" size="sm" variant="cyan" aria-hidden="true" />
        </button>
      </div>

      <!-- Configuration form -->
      <div class="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(220px,.65fr)] lg:items-start">
      <section class="rounded-xl md:rounded-2xl p-4 md:p-6 liquid-glass liquid-glass-hover">
        <div class="mb-1 flex items-center gap-2">
          <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-rose-400 to-amber-400 flex items-center justify-center shadow-sm">
            <AppIcon name="Rocket" size="sm" variant="white" />
          </div>
          <h2 class="text-sm font-semibold text-slate-700">{{ t('home.startWorkflow') }}</h2>
        </div>
        <p class="mb-4 pl-10 text-xs leading-5 text-slate-400">{{ t('home.formIntro') }}</p>
        <WorkflowStartForm
          ref="startFormRef"
          :initial-topic="prefilledTopic || undefined"
          :initial-niche="prefilledNiche"
          :is-loading="isStarting"
          @account-change="handleAccountChange"
          @submit="handleSubmit"
        />
        <p
          v-if="checklistBlocked"
          role="status"
          class="mt-3 flex items-start gap-1.5 rounded-lg border border-amber-200/70 bg-amber-50/80 px-3 py-2 text-xs text-amber-700 dark:border-amber-500/30 dark:bg-amber-950/40 dark:text-amber-300 dark-explicit"
        >
          <AppIcon name="AlertTriangle" size="sm" variant="peach" class="mt-0.5 shrink-0" aria-hidden="true" />
          <span>{{ t('home.checklistBlockedHint') }}</span>
        </p>
      </section>

      <aside class="rounded-xl border border-slate-200/70 bg-white/80 p-4 shadow-sm md:rounded-2xl md:p-6 dark:border-slate-700/60 dark:bg-slate-900/70 dark-explicit" aria-labelledby="home-shortcuts-title">
        <div class="mb-3 flex items-center gap-2">
          <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan-50 dark:bg-cyan-950/50 dark-explicit">
            <AppIcon name="Sparkles" size="sm" variant="cyan" aria-hidden="true" />
          </div>
          <div>
            <h2 id="home-shortcuts-title" class="text-sm font-semibold text-slate-700">{{ t('home.shortcutTitle') }}</h2>
            <p class="text-[11px] text-slate-400">{{ t('home.shortcutDescription') }}</p>
          </div>
        </div>
        <div class="space-y-2">
          <button type="button" class="flex min-h-11 w-full items-center gap-3 rounded-xl border border-cyan-100 bg-cyan-50/60 px-3 text-left transition hover:border-cyan-200 hover:bg-cyan-50 dark:border-cyan-500/25 dark:bg-cyan-950/30 dark:hover:border-cyan-400/40 dark:hover:bg-cyan-950/45 dark-explicit" @click="goToDashboard" :disabled="isStarting">
            <AppIcon name="BarChart3" size="sm" variant="cyan" aria-hidden="true" />
            <span class="min-w-0 flex-1 truncate text-xs font-semibold text-slate-700">{{ t('home.viewDashboard') }}</span>
            <AppIcon name="ArrowRight" size="sm" variant="cyan" aria-hidden="true" />
          </button>
          <button type="button" class="flex min-h-11 w-full items-center gap-3 rounded-xl border border-slate-200 bg-slate-50/70 px-3 text-left transition hover:border-slate-300 hover:bg-white dark:border-slate-600/50 dark:bg-slate-800/60 dark:hover:border-slate-500 dark:hover:bg-slate-800 dark-explicit" @click="goToHistory" :disabled="isStarting">
            <AppIcon name="History" size="sm" variant="cyan" aria-hidden="true" />
            <span class="min-w-0 flex-1 truncate text-xs font-semibold text-slate-700">{{ t('home.history') }}</span>
            <AppIcon name="ArrowRight" size="sm" variant="cyan" aria-hidden="true" />
          </button>
        </div>
      </aside>
      </div>

      <!-- Checklist + nav -->
      <div class="flex flex-col gap-3 md:gap-4">
        <PreLaunchChecklist ref="checklistRef" />
      </div>
    </div>

    <!-- Confirmation Modal -->
    <ConfirmStartModal
      :is-open="showConfirm"
      :account-id="formConfig.accountId"
      :account-name="selectedAccountName"
      :phase="formConfig.phase"
      :dry-run="formConfig.dryRun"
      :auto-publish="formConfig.autoPublish"
      :niche="formConfig.niche"
      :workflow-mode="confirmWorkflowMode"
      :brief-text="formConfig.briefText"
      :is-loading="isStarting"
      @confirm="confirmStart"
      @cancel="showConfirm = false"
    />

  </div>
</template>
