<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import { listWorkflows, deleteWorkflow } from '@/api/workflow'
import type { WorkflowListItem } from '@/types/workflow'
import { useWorkflowStore, useToastStore } from '@/stores'

const { t } = useI18n()
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
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function resumeWorkflow(threadId: string) {
  workflowStore.setThreadId(threadId)
  await workflowStore.refreshStatus()
  router.push('/dashboard')
}

async function viewWorkflow(threadId: string) {
  workflowStore.setThreadId(threadId)
  await workflowStore.refreshStatus()
  router.push('/dashboard')
}

async function replayWorkflow(threadId: string) {
  workflowStore.setThreadId(threadId)
  await workflowStore.refreshStatus()
  router.push('/dashboard?replay=true')
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

const isEmpty = computed(() => !isLoading.value && workflows.value.length === 0)
</script>

<template>
  <div class="space-y-4 md:space-y-5">
    <!-- Header -->
    <div class="rounded-2xl p-4 md:p-5 relative overflow-hidden bg-white/98 backdrop-blur-sm border border-slate-200/50 shadow-sm">
      <div class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 sm:gap-4">
        <div class="flex items-center gap-4">
          <div class="w-12 h-12 rounded-xl bg-gradient-to-br from-violet-400 to-violet-500 flex items-center justify-center shadow-sm">
            <AppIcon name="History" size="xl" variant="white" />
          </div>
          <div>
            <h1 class="text-xl font-semibold text-slate-800">{{ t('history.title') }}</h1>
            <p class="text-xs text-slate-400 mt-0.5">{{ t('history.subtitle') }}</p>
          </div>
        </div>
        <div class="flex gap-2">
          <NeonButton variant="ghost" size="sm" @click="fetchWorkflows" :loading="isLoading">
            <AppIcon name="RefreshCw" size="sm" variant="cyan" />
          </NeonButton>
          <NeonButton variant="pink" size="sm" @click="router.push('/')">
            <span class="inline-flex items-center gap-1.5">
              <AppIcon name="Plus" size="sm" variant="white" />
              {{ t('history.startNew') }}
            </span>
          </NeonButton>
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="isLoading" class="space-y-3">
      <div v-for="i in 5" :key="i" class="h-20 rounded-xl bg-slate-100 animate-pulse" />
    </div>

    <!-- Error -->
    <div v-else-if="error" class="rounded-xl p-6 bg-rose-50 border border-rose-100 text-center">
      <AppIcon name="AlertTriangle" size="lg" variant="pink" />
      <p class="text-sm text-rose-600 mt-2">{{ error }}</p>
      <NeonButton variant="ghost" size="sm" class="mt-3" @click="fetchWorkflows">
        {{ t('common.retry') }}
      </NeonButton>
    </div>

    <!-- Empty State -->
    <div v-else-if="isEmpty" class="rounded-2xl p-10 bg-white/98 border border-slate-200/50 text-center">
      <div class="w-16 h-16 rounded-2xl bg-slate-100 flex items-center justify-center mx-auto mb-4">
        <AppIcon name="Inbox" size="xl" variant="cyan" />
      </div>
      <h3 class="text-lg font-semibold text-slate-700 mb-1">{{ t('history.empty') }}</h3>
      <p class="text-sm text-slate-400 mb-5">{{ t('history.emptyDesc') }}</p>
      <div class="flex justify-center gap-3">
        <NeonButton variant="pink" @click="router.push('/')">
          {{ t('history.startNew') }}
        </NeonButton>
        <NeonButton variant="ghost" @click="router.push('/')">
          {{ t('history.backHome') }}
        </NeonButton>
      </div>
    </div>

    <!-- Workflow List -->
    <div v-else class="space-y-3">
      <div
        v-for="wf in workflows"
        :key="wf.thread_id"
        class="rounded-xl p-4 bg-white/98 border border-slate-200/50 hover:border-slate-300 hover:shadow-md transition-all duration-200 cursor-pointer"
        @click="viewWorkflow(wf.thread_id)"
      >
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3 flex-1 min-w-0">
            <!-- Status dot -->
            <span :class="[statusColor(wf.status), 'w-3 h-3 rounded-full flex-shrink-0']" />

            <!-- Info -->
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="text-sm font-medium text-slate-700 truncate">{{ wf.thread_id }}</span>
                <span v-if="wf.dry_run" class="text-xs px-1.5 py-0.5 rounded bg-teal-50 text-teal-600 border border-teal-100">
                  {{ t('history.dryRun') }}
                </span>
                <span v-else class="text-xs px-1.5 py-0.5 rounded bg-rose-50 text-rose-600 border border-rose-100">
                  {{ t('history.live') }}
                </span>
              </div>
              <div class="flex items-center gap-3 mt-1 text-xs text-slate-400">
                <span>{{ phaseLabel(wf.phase) }}</span>
                <span>{{ statusLabel(wf.status) }}</span>
                <span>{{ formatDate(wf.created_at) }}</span>
              </div>
            </div>
          </div>

          <!-- Progress & Actions -->
          <div class="flex items-center gap-3 flex-shrink-0">
            <!-- Progress bar -->
            <div class="w-20 hidden sm:block">
              <div class="h-1.5 rounded-full bg-slate-100 overflow-hidden">
                <div
                  class="h-full rounded-full bg-gradient-to-r from-rose-400 to-teal-400 transition-all"
                  :style="{ width: `${wf.progress_percent}%` }"
                />
              </div>
              <span class="text-xs text-slate-400 mt-0.5 block text-right">{{ wf.progress_percent }}%</span>
            </div>

            <!-- Action buttons -->
            <div class="flex items-center gap-2">
              <NeonButton
                v-if="wf.status === 'running'"
                variant="cyan"
                size="sm"
                @click.stop="resumeWorkflow(wf.thread_id)"
              >
                {{ t('history.resume') }}
              </NeonButton>
              <NeonButton
                v-else
                variant="ghost"
                size="sm"
                @click.stop="viewWorkflow(wf.thread_id)"
              >
                {{ t('history.view') }}
              </NeonButton>
              <NeonButton
                v-if="wf.status !== 'running'"
                variant="cyan"
                size="sm"
                @click.stop="replayWorkflow(wf.thread_id)"
              >
                {{ t('history.replay') }}
              </NeonButton>
              <button
                v-if="wf.status !== 'running'"
                @click.stop="requestDelete(wf.thread_id)"
                class="p-1.5 rounded-lg text-slate-400 hover:text-rose-500 hover:bg-rose-50 transition-colors"
                :aria-label="t('history.delete')"
              >
                <AppIcon name="Trash2" size="sm" variant="pink" />
              </button>
            </div>
          </div>
        </div>

        <!-- Error message -->
        <div v-if="wf.error" class="mt-2 p-2 rounded bg-rose-50 border border-rose-100 text-xs text-rose-600">
          {{ wf.error }}
        </div>
      </div>
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
  </div>
</template>
