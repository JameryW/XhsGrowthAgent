<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import PageHeader from '@/components/PageHeader.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import { listWorkflows, deleteWorkflow } from '@/api/workflow'
import {
  revokeShowcaseVisibility,
  updateShowcaseVisibility,
  type ShowcaseVisibilityUpdate,
} from '@/api/publicShowcase'
import type { WorkflowListItem } from '@/types/workflow'
import { useWorkflowStore, useToastStore } from '@/stores'

const { t, locale } = useI18n()
const router = useRouter()
const workflowStore = useWorkflowStore()
const toastStore = useToastStore()

const workflows = ref<WorkflowListItem[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)
const total = ref(0)

// Delete confirmation
const showDeleteModal = ref(false)
const deleteTarget = ref<string | null>(null)
const isDeleting = ref(false)

type ShowcaseVisibility = 'private' | 'unlisted' | 'public'

// Public Showcase controls are kept on the history page because this is the
// authenticated operator's complete workflow inventory.
const showcaseTarget = ref<WorkflowListItem | null>(null)
const showcaseVisibility = ref<ShowcaseVisibility>('public')
const showcaseTitle = ref('')
const showcaseSummary = ref('')
const showcaseFeatured = ref(false)
const showcaseFeaturedRank = ref(1)
const isUpdatingShowcase = ref(false)

async function fetchWorkflows() {
  isLoading.value = true
  error.value = null
  try {
    const result = await listWorkflows({ limit: 50 })
    workflows.value = result.workflows
    total.value = result.total
  } catch (e: any) {
    error.value = e.message
  } finally {
    isLoading.value = false
  }
}

onMounted(fetchWorkflows)

const statusColor = (status: string) => {
  switch (status) {
    case 'running': return 'bg-teal-500'
    case 'completed': return 'bg-emerald-500'
    case 'error': return 'bg-rose-500'
    case 'cancelled': return 'bg-slate-400'
    default: return 'bg-slate-400'
  }
}

const statusLabel = (status: string) => {
  const key = `history.status.${status}`
  return t(key)
}

const phaseLabel = (phase: string) => {
  const map: Record<string, string> = {
    idle: 'review.emptyState.phaseIdle',
    scouting: 'dashboard.timeline.scouting',
    planning: 'dashboard.timeline.planning',
    creating: 'dashboard.timeline.creating',
    reviewing: 'dashboard.timeline.reviewing',
    publishing: 'dashboard.timeline.publishing',
    analyzing: 'dashboard.timeline.analyzing',
    engaging: 'dashboard.timeline.engaging',
    completed: 'dashboard.timeline.completed',
    error: 'dashboard.timeline.error',
    cancelled: 'review.emptyState.phaseCancelled',
  }
  return t(map[phase] || `dashboard.timeline.${phase}`)
}

function formatDate(iso: string) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString(locale.value, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function resumeWorkflow(threadId: string) {
  workflowStore.setThreadId(threadId)
  await workflowStore.refreshStatus()
  router.push({ name: 'dashboard', params: { threadId } })
}

async function viewWorkflow(threadId: string) {
  workflowStore.setThreadId(threadId)
  await workflowStore.refreshStatus()
  router.push({ name: 'dashboard', params: { threadId } })
}

async function replayWorkflow(threadId: string) {
  workflowStore.setThreadId(threadId)
  await workflowStore.refreshStatus()
  router.push({ name: 'dashboard', params: { threadId }, query: { replay: 'true' } })
}

function requestDelete(threadId: string) {
  deleteTarget.value = threadId
  showDeleteModal.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  isDeleting.value = true
  try {
    await deleteWorkflow(deleteTarget.value)
    // Clean up workflow store state for the deleted thread
    workflowStore.closeTab(deleteTarget.value)
    workflows.value = workflows.value.filter(w => w.thread_id !== deleteTarget.value)
    total.value--
    toastStore.success(t('history.deleteSuccess'), deleteTarget.value)
  } catch (e: any) {
    toastStore.error(t('history.deleteFailed'), e.message)
  } finally {
    isDeleting.value = false
    showDeleteModal.value = false
    deleteTarget.value = null
  }
}

function openShowcaseSettings(workflow: WorkflowListItem) {
  showcaseTarget.value = workflow
  showcaseVisibility.value = workflow.showcase_visibility && workflow.showcase_visibility !== 'private'
    ? workflow.showcase_visibility
    : 'public'
  showcaseTitle.value = workflow.public_title || workflow.label || ''
  showcaseSummary.value = workflow.public_summary || ''
  showcaseFeatured.value = Boolean(workflow.showcase_featured)
  showcaseFeaturedRank.value = workflow.featured_rank ?? 1
}

function closeShowcaseSettings() {
  if (isUpdatingShowcase.value) return
  showcaseTarget.value = null
}

function showcaseVisibilityLabel(workflow: WorkflowListItem): string {
  if (workflow.showcase_visibility === 'public') return t('history.showcasePublic')
  if (workflow.showcase_visibility === 'unlisted') return t('history.showcaseUnlisted')
  return t('history.showcasePrivate')
}

async function saveShowcaseSettings() {
  const workflow = showcaseTarget.value
  if (!workflow || isUpdatingShowcase.value) return
  if (!workflow.showcase_public_id) {
    toastStore.error(t('history.showcaseUpdateFailed'), t('common.retry'))
    return
  }

  isUpdatingShowcase.value = true
  try {
    if (showcaseVisibility.value === 'private') {
      await revokeShowcaseVisibility(workflow.showcase_public_id)
      workflow.showcase_visibility = 'private'
      workflow.showcase_featured = false
      workflow.featured_rank = null
    } else {
      const payload: ShowcaseVisibilityUpdate = {
        visibility: showcaseVisibility.value,
        public_title: showcaseTitle.value.trim() || null,
        public_summary: showcaseSummary.value.trim() || null,
        featured: showcaseVisibility.value === 'public' && showcaseFeatured.value,
        featured_rank: showcaseVisibility.value === 'public' && showcaseFeatured.value
          ? Math.max(0, Math.min(1000, Math.round(showcaseFeaturedRank.value || 1)))
          : null,
      }
      const response = await updateShowcaseVisibility(workflow.showcase_public_id, payload)
      workflow.showcase_visibility = payload.visibility
      workflow.public_title = payload.public_title
      // When the summary was left blank, the server generates one from the
      // workflow content; sync it back so the dialog shows the real value.
      workflow.public_summary = !payload.public_summary && response.summary_auto_generated
        ? response.case?.summary ?? null
        : payload.public_summary
      workflow.showcase_featured = Boolean(payload.featured)
      workflow.featured_rank = payload.featured_rank
    }
    toastStore.success(t('history.showcaseUpdateSuccess'), workflow.label)
    showcaseTarget.value = null
  } catch (e: any) {
    toastStore.error(t('history.showcaseUpdateFailed'), e?.message)
  } finally {
    isUpdatingShowcase.value = false
  }
}

const isEmpty = computed(() => !isLoading.value && workflows.value.length === 0)

const modeLabel = (mode: string) => mode === 'brief' ? t('home.briefMode') : t('home.trendMode')
const modeColor = (mode: string) => mode === 'brief' ? 'bg-pink-50 text-pink-600 border-pink-100' : 'bg-cyan-50 text-cyan-600 border-cyan-100'
</script>

<template>
  <div class="app-page-content space-y-4 md:space-y-6">
    <PageHeader
      :title="t('history.title')"
      :description="t('history.subtitle')"
      :eyebrow="t('nav.sections.insights')"
      icon="History"
      tone="purple"
    >
      <template #meta>
        <span>{{ t('history.records', { count: total }) }}</span>
      </template>
      <template #actions>
        <NeonButton variant="ghost" size="sm" class="min-h-11" @click="fetchWorkflows" :loading="isLoading">
          <AppIcon name="RefreshCw" size="sm" variant="cyan" />
          <span class="hidden sm:inline">{{ t('history.refresh') }}</span>
        </NeonButton>
      </template>
    </PageHeader>

    <!-- Loading -->
    <div v-if="isLoading" class="space-y-3">
      <div v-for="i in 5" :key="i" class="h-20 rounded-xl bg-slate-100 animate-pulse dark:bg-slate-800" />
    </div>

    <!-- Error -->
    <div v-else-if="error" class="rounded-xl p-4 md:p-6 liquid-glass-rose liquid-glass-hover text-center">
      <AppIcon name="AlertTriangle" size="lg" variant="pink" />
      <p class="text-sm text-rose-600 mt-2">{{ error }}</p>
      <NeonButton variant="ghost" size="sm" class="mt-3" @click="fetchWorkflows">
        {{ t('common.retry') }}
      </NeonButton>
    </div>

    <!-- Empty State -->
    <div v-else-if="isEmpty" class="rounded-xl md:rounded-2xl p-6 md:p-10 liquid-glass text-center">
      <div class="w-12 h-12 md:w-16 md:h-16 rounded-xl md:rounded-2xl bg-slate-100 flex items-center justify-center mx-auto mb-3 md:mb-4 dark:bg-slate-800">
        <AppIcon name="Inbox" size="lg" variant="cyan" class="md:hidden" />
        <AppIcon name="Inbox" size="xl" variant="cyan" class="hidden md:block" />
      </div>
      <h3 class="text-base md:text-lg font-semibold text-slate-700 mb-1">{{ t('history.empty') }}</h3>
      <p class="text-xs md:text-sm text-slate-400 mb-4 md:mb-5">{{ t('history.emptyDesc') }}</p>
      <div class="flex justify-center gap-3">
        <NeonButton variant="pink" size="sm" @click="router.push('/start')">
          {{ t('history.startNew') }}
        </NeonButton>
        <NeonButton variant="ghost" size="sm" @click="router.push('/dashboard')">
          {{ t('history.backHome') }}
        </NeonButton>
      </div>
    </div>

    <!-- Workflow List -->
    <div v-else class="space-y-2 md:space-y-3">
      <article
        v-for="wf in workflows"
        :key="wf.thread_id"
        class="rounded-xl p-3 md:p-4 liquid-glass liquid-glass-hover hover:border-slate-300 transition-all duration-200"
        :aria-labelledby="`history-workflow-${wf.thread_id}`"
      >
        <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 sm:gap-2">
          <div class="flex items-center gap-2 md:gap-3 flex-1 min-w-0">
            <!-- Status dot -->
            <span :class="[statusColor(wf.status), 'w-2.5 h-2.5 md:w-3 md:h-3 rounded-full flex-shrink-0']" />

            <!-- Info -->
            <div class="flex-1 min-w-0 overflow-hidden">
              <div class="flex items-center gap-1.5 md:gap-2 flex-wrap min-w-0">
                <span :id="`history-workflow-${wf.thread_id}`" class="text-xs md:text-sm font-medium text-slate-700 truncate">{{ wf.label || wf.thread_id.slice(-8) }}</span>
                <span class="text-[10px] md:text-xs font-mono text-slate-400 hidden sm:inline truncate">{{ wf.thread_id }}</span>
                <span v-if="wf.dry_run" class="text-[10px] md:text-xs px-1 md:px-1.5 py-0.5 rounded bg-teal-50 text-teal-600 border border-teal-100 dark:bg-teal-950/45 dark:text-teal-300 dark:border-teal-500/30">
                  {{ t('history.dryRun') }}
                </span>
                <span v-else class="text-[10px] md:text-xs px-1 md:px-1.5 py-0.5 rounded bg-rose-50 text-rose-600 border border-rose-100 dark:bg-rose-950/45 dark:text-rose-300 dark:border-rose-500/30">
                  {{ t('history.live') }}
                </span>
                <span v-if="wf.workflow_mode" class="text-[10px] md:text-xs px-1 md:px-1.5 py-0.5 rounded border"
                  :class="modeColor(wf.workflow_mode)">
                  {{ modeLabel(wf.workflow_mode) }}
                </span>
                <span
                  class="text-[10px] md:text-xs px-1 md:px-1.5 py-0.5 rounded border"
                  :class="wf.showcase_visibility === 'public'
                    ? 'bg-teal-50 text-teal-600 border-teal-100 dark:bg-teal-950/45 dark:text-teal-300 dark:border-teal-500/30'
                    : wf.showcase_visibility === 'unlisted'
                      ? 'bg-amber-50 text-amber-600 border-amber-100 dark:bg-amber-950/45 dark:text-amber-300 dark:border-amber-500/30'
                      : 'bg-slate-50 text-slate-400 border-slate-200 dark:bg-slate-800/60 dark:text-slate-400 dark:border-slate-700'"
                >
                  {{ showcaseVisibilityLabel(wf) }}
                </span>
              </div>
              <div class="flex items-center gap-2 md:gap-3 mt-0.5 md:mt-1 text-[10px] md:text-xs text-slate-400">
                <span>{{ phaseLabel(wf.phase) }}</span>
                <!-- Status is only shown when it adds information beyond the
                     phase label (both read "已完成" for finished runs). -->
                <span v-if="statusLabel(wf.status) !== phaseLabel(wf.phase)">{{ statusLabel(wf.status) }}</span>
                <span>{{ formatDate(wf.created_at) }}</span>
              </div>
            </div>
          </div>

          <!-- Progress & Actions -->
          <div class="flex items-center gap-2 md:gap-3 flex-shrink-0 flex-wrap">
            <!-- Progress bar -->
            <div class="w-16 md:w-20 hidden sm:block">
              <div class="h-1 md:h-1.5 rounded-full bg-slate-100 overflow-hidden dark:bg-slate-800">
                <div
                  class="h-full rounded-full bg-gradient-to-r from-rose-400 to-teal-400 transition-all"
                  :style="{ width: `${wf.progress_percent}%` }"
                />
              </div>
              <span class="text-[10px] md:text-xs text-slate-400 mt-0.5 block text-right">{{ wf.progress_percent }}%</span>
            </div>

            <!-- Action buttons -->
            <div class="flex items-center gap-1.5 md:gap-2">
                <NeonButton
                  v-if="wf.status === 'running'"
                  variant="cyan"
                  size="sm"
                  class="min-h-11"
                  @click.stop="resumeWorkflow(wf.thread_id)"
              >
                {{ t('history.resume') }}
              </NeonButton>
              <NeonButton
                v-else
                  variant="ghost"
                  size="sm"
                  class="min-h-11"
                  @click.stop="viewWorkflow(wf.thread_id)"
              >
                {{ t('history.view') }}
              </NeonButton>
              <NeonButton
                v-if="wf.status !== 'running'"
                  variant="cyan"
                  size="sm"
                  class="min-h-11"
                  @click.stop="replayWorkflow(wf.thread_id)"
              >
                {{ t('history.replay') }}
              </NeonButton>
              <NeonButton
                variant="ghost"
                size="sm"
                class="min-h-11"
                @click.stop="openShowcaseSettings(wf)"
              >
                <AppIcon name="Eye" size="sm" variant="cyan" />
                <span class="hidden md:inline">{{ t('history.showcaseManage') }}</span>
              </NeonButton>
              <button
                v-if="wf.status !== 'running'"
                @click.stop="requestDelete(wf.thread_id)"
                class="min-h-11 min-w-11 rounded-lg text-slate-400 hover:text-rose-500 hover:bg-rose-50 transition-colors"
                :aria-label="t('history.delete')"
              >
                <AppIcon name="Trash2" size="sm" variant="pink" />
              </button>
            </div>
          </div>
        </div>

        <!-- Error message -->
        <div v-if="wf.error" class="mt-1.5 md:mt-2 p-1.5 md:p-2 rounded liquid-glass-rose text-[10px] md:text-xs text-rose-600">
          {{ wf.error }}
        </div>
      </article>
    </div>

    <!-- Delete Confirmation Modal -->
    <ConfirmModal
      :is-open="showDeleteModal"
      :title="t('history.deleteTitle')"
      :message="t('history.deleteMessage')"
      :confirm-action="t('history.deleteConfirm')"
      variant="danger"
      @confirm="confirmDelete"
      @cancel="showDeleteModal = false; deleteTarget = null"
    />

    <!-- Public Showcase visibility management -->
    <div
      v-if="showcaseTarget"
      class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm"
      role="presentation"
      @click.self="closeShowcaseSettings"
    >
      <section
        class="w-full max-w-lg rounded-2xl border border-slate-200/80 bg-white p-5 shadow-2xl dark:border-slate-700 dark:bg-slate-900 md:p-6"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="`showcase-settings-${showcaseTarget.thread_id}`"
      >
        <div class="flex items-start justify-between gap-4">
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.16em] text-teal-600 dark:text-teal-300">{{ t('history.showcaseManage') }}</p>
            <h2 :id="`showcase-settings-${showcaseTarget.thread_id}`" class="mt-1 text-lg font-semibold text-slate-800 dark:text-slate-100">{{ t('history.showcaseTitle') }}</h2>
            <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ showcaseTarget.label || showcaseTarget.thread_id }}</p>
          </div>
          <button
            type="button"
            class="min-h-11 min-w-11 rounded-xl text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
            :aria-label="t('common.close')"
            :disabled="isUpdatingShowcase"
            @click="closeShowcaseSettings"
          >
            <AppIcon name="X" size="sm" aria-hidden="true" />
          </button>
        </div>

        <div class="mt-5 space-y-4">
          <label class="block">
            <span class="mb-1.5 block text-xs font-semibold text-slate-600 dark:text-slate-300">{{ t('history.showcaseVisibility') }}</span>
            <select
              v-model="showcaseVisibility"
              class="min-h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
              :disabled="isUpdatingShowcase"
            >
              <option value="public">{{ t('history.showcaseVisibilityPublic') }}</option>
              <option value="unlisted">{{ t('history.showcaseVisibilityUnlisted') }}</option>
              <option value="private">{{ t('history.showcaseVisibilityPrivate') }}</option>
            </select>
          </label>

          <template v-if="showcaseVisibility !== 'private'">
            <label class="block">
              <span class="mb-1.5 block text-xs font-semibold text-slate-600 dark:text-slate-300">{{ t('history.showcaseTitleLabel') }}</span>
              <input
                v-model="showcaseTitle"
                type="text"
                maxlength="120"
                class="min-h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
                :placeholder="t('history.showcaseTitlePlaceholder')"
                :disabled="isUpdatingShowcase"
              />
            </label>
            <label class="block">
              <span class="mb-1.5 block text-xs font-semibold text-slate-600 dark:text-slate-300">{{ t('history.showcaseSummaryLabel') }}</span>
              <textarea
                v-model="showcaseSummary"
                rows="3"
                maxlength="360"
                class="w-full resize-y rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-700 outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
                :placeholder="t('history.showcaseSummaryPlaceholder')"
                :disabled="isUpdatingShowcase"
              />
            </label>
            <label v-if="showcaseVisibility === 'public'" class="flex min-h-11 items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
              <input v-model="showcaseFeatured" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500" :disabled="isUpdatingShowcase" />
              <span>{{ t('history.showcaseFeatured') }}</span>
            </label>
            <label v-if="showcaseVisibility === 'public' && showcaseFeatured" class="block">
              <span class="mb-1.5 block text-xs font-semibold text-slate-600 dark:text-slate-300">{{ t('history.showcaseFeaturedRank') }}</span>
              <input v-model.number="showcaseFeaturedRank" type="number" min="0" max="1000" class="min-h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200" :disabled="isUpdatingShowcase" />
            </label>
          </template>
        </div>

        <div class="mt-6 flex justify-end gap-2">
          <button type="button" class="min-h-11 rounded-xl px-4 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800" :disabled="isUpdatingShowcase" @click="closeShowcaseSettings">{{ t('history.showcaseCancel') }}</button>
          <button type="button" class="min-h-11 rounded-xl bg-teal-600 px-4 text-sm font-semibold text-white shadow-sm hover:bg-teal-700 disabled:cursor-wait disabled:opacity-60" :disabled="isUpdatingShowcase" @click="saveShowcaseSettings">{{ isUpdatingShowcase ? t('common.loadingState') : t('history.showcaseSave') }}</button>
        </div>
      </section>
    </div>
  </div>
</template>
