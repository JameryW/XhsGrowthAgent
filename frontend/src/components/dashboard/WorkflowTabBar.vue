<script setup lang="ts">
import { ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import type { WorkflowStatus, WorkflowPhase } from '@/types/workflow'
import i18n from '@/locales'

const { t } = i18n.global

const props = defineProps<{
  tabs: Array<{
    threadId: string
    label: string
    status: WorkflowStatus
    phase: WorkflowPhase
    progress: number
    accountId?: string | null
  }>
  activeThreadId: string | null
  hasOverflow: boolean
  overflowTabs: Array<{
    threadId: string
    label: string
    status: WorkflowStatus
    phase: WorkflowPhase
    progress: number
    accountId?: string | null
  }>
  /** Workspace active account — tabs for other accounts get a subtle marker. */
  workspaceAccountId?: string | null
}>()

const emit = defineEmits<{
  switch: [threadId: string]
  close: [threadId: string]
  rename: [threadId: string, newLabel: string]
}>()

const showOverflow = ref(false)
const editingTabId = ref<string | null>(null)
const editingLabel = ref('')
const confirmCloseTabId = ref<string | null>(null)

function statusIcon(status: WorkflowStatus): string {
  switch (status) {
    case 'running': return 'Loader'
    case 'stale': return 'AlertCircle'
    case 'awaiting_review':
    case 'awaiting_choice':
    case 'awaiting_draft':
    case 'awaiting_brief':
    case 'awaiting_ripple_decision':
    case 'awaiting_blogger_selection': return 'Clock'
    case 'paused': return 'Pause'
    case 'cancelled': return 'XCircle'
    case 'error': return 'AlertTriangle'
    case 'completed': return 'CheckCircle'
    default: return 'Circle'
  }
}

function statusColor(status: WorkflowStatus): string {
  switch (status) {
    case 'running': return 'text-emerald-400'
    case 'stale': return 'text-amber-400'
    case 'awaiting_review':
    case 'awaiting_choice':
    case 'awaiting_draft':
    case 'awaiting_brief':
    case 'awaiting_ripple_decision':
    case 'awaiting_blogger_selection': return 'text-orange-400'
    case 'paused': return 'text-slate-400'
    case 'cancelled': return 'text-slate-500'
    case 'error': return 'text-red-400'
    case 'completed': return 'text-slate-500'
    default: return 'text-slate-500'
  }
}

function isActive(tabId: string): boolean {
  return tabId === props.activeThreadId
}

function isOtherAccount(tab: { accountId?: string | null }): boolean {
  const workspace = props.workspaceAccountId
  const owner = tab.accountId
  return !!(workspace && owner && workspace !== owner)
}

function onTabClick(tabId: string) {
  if (editingTabId.value === tabId) return
  emit('switch', tabId)
}

function onTabDblClick(tabId: string, currentLabel: string) {
  editingTabId.value = tabId
  editingLabel.value = currentLabel
}

function finishRename() {
  if (editingTabId.value && editingLabel.value.trim()) {
    emit('rename', editingTabId.value, editingLabel.value.trim())
  }
  editingTabId.value = null
  editingLabel.value = ''
}

function onCancelRename() {
  editingTabId.value = null
  editingLabel.value = ''
}

function onCloseClick(tabId: string, e: MouseEvent) {
  e.stopPropagation()
  confirmCloseTabId.value = tabId
}

function confirmClose() {
  if (confirmCloseTabId.value) {
    emit('close', confirmCloseTabId.value)
    confirmCloseTabId.value = null
  }
}

function cancelClose() {
  confirmCloseTabId.value = null
}

function toggleOverflow() {
  showOverflow.value = !showOverflow.value
}
</script>

<template>
  <div class="workflow-tab-bar">
    <div class="tabs-scroll">
      <div
        v-for="tab in tabs"
        :key="tab.threadId"
        class="tab-item"
        :class="{ active: isActive(tab.threadId) }"
        @click="onTabClick(tab.threadId)"
        @dblclick="onTabDblClick(tab.threadId, tab.label)"
        :title="tab.label"
      >
        <AppIcon
          :name="statusIcon(tab.status)"
          size="xs"
          :class="[statusColor(tab.status), tab.status === 'running' ? 'animate-pulse' : '']"
          class="tab-icon"
        />

        <input
          v-if="editingTabId === tab.threadId"
          v-model="editingLabel"
          class="tab-edit-input"
          @keydown.enter="finishRename"
          @keydown.escape="onCancelRename"
          @blur="finishRename"
          autofocus
          @click.stop
        />
        <span v-else class="tab-label">{{ tab.label }}</span>
        <span
          v-if="isOtherAccount(tab)"
          class="ml-0.5 inline-flex h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400"
          :title="t('dashboard.tabOtherAccount')"
          aria-hidden="true"
        />

        <button
          class="tab-close"
          @click="onCloseClick(tab.threadId, $event)"
          :title="t('workflow.closeTab')"
        >
          <AppIcon name="X" size="xs" />
        </button>
      </div>

      <div v-if="hasOverflow" class="tab-overflow-trigger" @click="toggleOverflow">
        <AppIcon name="ChevronDown" size="sm" />
        <span class="text-xs text-slate-400">{{ overflowTabs.length }}</span>
      </div>
    </div>

    <div v-if="hasOverflow && showOverflow" class="overflow-dropdown">
      <div
        v-for="tab in overflowTabs"
        :key="tab.threadId"
        class="overflow-item"
        :class="{ active: isActive(tab.threadId) }"
        @click="onTabClick(tab.threadId); showOverflow = false"
      >
        <AppIcon
          :name="statusIcon(tab.status)"
          size="xs"
          :class="[statusColor(tab.status), tab.status === 'running' ? 'animate-pulse' : '']"
        />
        <span class="tab-label">{{ tab.label }}</span>
        <span
          v-if="isOtherAccount(tab)"
          class="ml-0.5 inline-flex h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400"
          :title="t('dashboard.tabOtherAccount')"
          aria-hidden="true"
        />
        <button class="tab-close" @click="onCloseClick(tab.threadId, $event)">
          <AppIcon name="X" size="xs" />
        </button>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="confirmCloseTabId" class="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm" @click.self="cancelClose">
        <div class="bg-white rounded-xl p-5 shadow-2xl max-w-sm w-full border border-slate-200 dark:bg-slate-900 dark:border-slate-700">
          <h3 class="text-slate-800 font-medium mb-2">{{ t('workflow.closeTabConfirm') }}</h3>
          <p class="text-slate-500 text-sm mb-4">{{ t('workflow.closeTabHint') }}</p>
          <div class="flex gap-3 justify-end">
            <button class="px-3 py-1.5 text-sm rounded-lg bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700" @click="cancelClose">
              {{ t('common.cancel') }}
            </button>
            <button class="px-3 py-1.5 text-sm rounded-lg bg-rose-500 text-white hover:bg-rose-600" @click="confirmClose">
              {{ t('workflow.closeTab') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.workflow-tab-bar {
  @apply relative;
}

.tabs-scroll {
  @apply flex items-center gap-1.5 overflow-x-auto px-1 py-1;
  scrollbar-width: thin;
}

.tab-item {
  @apply flex items-center gap-1.5 px-3 py-1.5 rounded-lg cursor-pointer
         bg-slate-100/80 text-slate-500 hover:bg-slate-200/80 hover:text-slate-700
         transition-colors max-w-[180px] min-w-[100px] shrink-0 select-none;
}

.tab-item.active {
  @apply bg-white/[.98] text-slate-800 shadow-sm ring-1 ring-slate-200/60;
}

.tab-icon {
  @apply shrink-0;
}

.tab-label {
  @apply truncate text-xs;
}

.tab-edit-input {
  @apply bg-slate-50 text-slate-800 text-xs px-1 py-0.5 rounded w-full outline-none ring-1 ring-rose-300;
}

.tab-close {
  /* DB-12: tap target ≥44px (icon stays small via inner span). */
  @apply shrink-0 p-0.5 rounded hover:bg-slate-200/80 text-slate-400 hover:text-slate-600 transition-colors min-w-[44px] min-h-[44px] flex items-center justify-center;
}

.tab-overflow-trigger {
  @apply flex items-center gap-1 px-2 py-1.5 rounded-lg cursor-pointer
         hover:bg-slate-200/80 text-slate-400 hover:text-slate-600 transition-colors shrink-0;
}

.overflow-dropdown {
  @apply absolute right-2 top-full mt-1 bg-white/[.98] backdrop-blur-sm rounded-xl border border-slate-200/50 shadow-xl
         py-1 min-w-[200px] max-h-[300px] overflow-y-auto z-40;
}

.overflow-item {
  @apply flex items-center gap-1.5 px-3 py-2 cursor-pointer text-slate-500
         hover:bg-slate-50 hover:text-slate-700 transition-colors;
}

.overflow-item.active {
  @apply bg-slate-50/80 text-slate-800;
}

:global(html.dark) .tab-item {
  background: rgba(30, 41, 59, 0.75);
  color: #94a3b8;
}
:global(html.dark) .tab-item:hover {
  background: rgba(51, 65, 85, 0.85);
  color: #e2e8f0;
}
:global(html.dark) .tab-item.active {
  background: rgba(15, 23, 42, 0.95);
  color: #f1f5f9;
}
:global(html.dark) .overflow-item:hover {
  background: rgba(30, 41, 59, 0.9);
  color: #e2e8f0;
}
</style>
