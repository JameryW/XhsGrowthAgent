<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import { useFocusTrap } from '@/composables/useFocusTrap'
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

const rootEl = ref<HTMLElement | null>(null)
const overflowTriggerEl = ref<HTMLElement | null>(null)
const confirmDialogEl = ref<HTMLElement | null>(null)
// Shared INF-06 trap: initial focus, Tab containment, focus restore on close.
const { activate: activateConfirmTrap, deactivate: deactivateConfirmTrap } = useFocusTrap()

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
    case 'running': return 'text-teal-400'
    case 'stale': return 'text-amber-400'
    case 'awaiting_review':
    case 'awaiting_choice':
    case 'awaiting_draft':
    case 'awaiting_brief':
    case 'awaiting_ripple_decision':
    case 'awaiting_blogger_selection': return 'text-orange-400'
    case 'paused': return 'text-slate-400'
    case 'cancelled': return 'text-slate-500'
    case 'error': return 'text-rose-400'
    case 'completed': return 'text-emerald-500'
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

function startRename(tabId: string, currentLabel: string) {
  editingTabId.value = tabId
  editingLabel.value = currentLabel
}

function onTabDblClick(tabId: string, currentLabel: string) {
  startRename(tabId, currentLabel)
}

function onRenameClick(tabId: string, currentLabel: string, e: MouseEvent) {
  e.stopPropagation()
  startRename(tabId, currentLabel)
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

function closeOverflow(restoreFocus = false) {
  if (!showOverflow.value) return
  showOverflow.value = false
  if (restoreFocus) overflowTriggerEl.value?.focus()
}

function onDocumentClick(e: MouseEvent) {
  if (!showOverflow.value) return
  if (rootEl.value && !rootEl.value.contains(e.target as Node)) closeOverflow()
}

function onDocumentKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  closeOverflow(true)
}

onMounted(() => {
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onDocumentKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onDocumentKeydown)
})

// Open/close the close-tab confirm through the focus trap so it gets initial
// focus and the trigger's focus is restored afterwards.
watch(confirmCloseTabId, async (id) => {
  if (id) {
    await nextTick()
    activateConfirmTrap(confirmDialogEl.value)
  } else {
    deactivateConfirmTrap()
  }
})
</script>

<template>
  <div class="workflow-tab-bar" ref="rootEl">
    <div class="tabs-scroll" role="tablist" :aria-label="t('dashboard.tabBar.ariaLabel')">
      <div
        v-for="tab in tabs"
        :key="tab.threadId"
        class="tab-item"
        :class="{ active: isActive(tab.threadId) }"
      >
        <input
          v-if="editingTabId === tab.threadId"
          v-model="editingLabel"
          class="tab-edit-input"
          :aria-label="t('dashboard.tabBar.renameEditing')"
          @keydown.enter="finishRename"
          @keydown.escape="onCancelRename"
          @blur="finishRename"
          autofocus
          @click.stop
        />
        <button
          v-else
          type="button"
          role="tab"
          class="tab-main"
          :aria-selected="isActive(tab.threadId)"
          :title="tab.label"
          @click="onTabClick(tab.threadId)"
          @dblclick="onTabDblClick(tab.threadId, tab.label)"
        >
          <AppIcon
            :name="statusIcon(tab.status)"
            size="xs"
            :class="[statusColor(tab.status), tab.status === 'running' ? 'animate-pulse' : '']"
            class="tab-icon"
          />
          <span class="tab-label">{{ tab.label }}</span>
          <span
            v-if="isOtherAccount(tab)"
            class="ml-0.5 inline-flex h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400"
            :title="t('dashboard.tabOtherAccount')"
            aria-hidden="true"
          />
        </button>

        <button
          v-if="editingTabId !== tab.threadId"
          type="button"
          class="tab-rename min-h-11 min-w-[44px]"
          :title="t('dashboard.tabBar.rename')"
          :aria-label="t('dashboard.tabBar.rename')"
          @click="onRenameClick(tab.threadId, tab.label, $event)"
        >
          <AppIcon name="Pencil" size="xs" variant="muted" aria-hidden="true" />
        </button>

        <button
          type="button"
          class="tab-close min-h-11 min-w-[44px]"
          :title="t('workflow.closeTab')"
          :aria-label="t('workflow.closeTab')"
          @click="onCloseClick(tab.threadId, $event)"
        >
          <AppIcon name="X" size="xs" variant="muted" />
        </button>
      </div>

      <button
        v-if="hasOverflow"
        type="button"
        ref="overflowTriggerEl"
        class="tab-overflow-trigger"
        aria-haspopup="true"
        :aria-expanded="showOverflow"
        :aria-label="t('dashboard.tabBar.overflow')"
        :title="t('dashboard.tabBar.overflow')"
        @click="toggleOverflow"
      >
        <AppIcon name="ChevronDown" size="sm" variant="muted" />
        <span class="text-xs text-slate-400">{{ overflowTabs.length }}</span>
      </button>
    </div>

    <div v-if="hasOverflow && showOverflow" class="overflow-dropdown" role="menu" :aria-label="t('dashboard.tabBar.overflow')">
      <div
        v-for="tab in overflowTabs"
        :key="tab.threadId"
        class="overflow-item"
        :class="{ active: isActive(tab.threadId) }"
      >
        <div v-if="editingTabId === tab.threadId" class="overflow-edit">
          <input
            v-model="editingLabel"
            class="tab-edit-input"
            :aria-label="t('dashboard.tabBar.renameEditing')"
            @keydown.enter="finishRename"
            @keydown.escape="onCancelRename"
            @blur="finishRename"
            autofocus
            @click.stop
          />
        </div>
        <button
          v-else
          type="button"
          role="menuitem"
          class="overflow-main"
          :aria-current="isActive(tab.threadId) ? 'true' : undefined"
          :title="tab.label"
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
        </button>
        <button
          v-if="editingTabId !== tab.threadId"
          type="button"
          class="tab-rename min-h-11 min-w-[44px]"
          :title="t('dashboard.tabBar.rename')"
          :aria-label="t('dashboard.tabBar.rename')"
          @click="onRenameClick(tab.threadId, tab.label, $event)"
        >
          <AppIcon name="Pencil" size="xs" variant="muted" aria-hidden="true" />
        </button>
        <button
          type="button"
          class="tab-close min-h-11 min-w-[44px]"
          :title="t('workflow.closeTab')"
          :aria-label="t('workflow.closeTab')"
          @click="onCloseClick(tab.threadId, $event)"
        >
          <AppIcon name="X" size="xs" variant="muted" />
        </button>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="confirmCloseTabId" class="fixed inset-0 z-modal flex items-center justify-center bg-black/30 backdrop-blur-sm" @click.self="cancelClose">
        <div
          ref="confirmDialogEl"
          role="dialog"
          aria-modal="true"
          aria-labelledby="tab-close-confirm-title"
          class="bg-white rounded-xl p-5 shadow-2xl max-w-sm w-full border border-slate-200 dark-explicit dark:bg-slate-900 dark:border-slate-700"
          @keydown.escape="cancelClose"
        >
          <h3 id="tab-close-confirm-title" class="text-slate-800 font-medium mb-2">{{ t('workflow.closeTabConfirm') }}</h3>
          <p class="text-slate-500 text-sm mb-4">{{ t('workflow.closeTabHint') }}</p>
          <div class="flex gap-3 justify-end">
            <button type="button" class="px-3 py-1.5 text-sm rounded-lg bg-slate-100 text-slate-600 hover:bg-slate-200 dark-explicit dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700" @click="cancelClose">
              {{ t('common.cancel') }}
            </button>
            <button type="button" class="px-3 py-1.5 text-sm rounded-lg bg-rose-500 text-white hover:bg-rose-600" @click="confirmClose">
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
  @apply flex items-center gap-1.5 px-3 py-1.5 rounded-lg
         bg-slate-100/80 text-slate-500 hover:bg-slate-200/80 hover:text-slate-700
         transition-colors max-w-[180px] min-w-[100px] shrink-0 select-none;
}

.tab-item.active {
  @apply bg-white/[.98] text-slate-800 shadow-sm ring-1 ring-slate-200/60;
}

.tab-main {
  @apply flex items-center gap-1.5 min-w-0 flex-1 rounded;
}

.tab-main:focus-visible {
  @apply outline-none ring-2 ring-teal-400;
}

.tab-icon {
  @apply shrink-0;
}

.tab-rename {
  @apply flex min-h-11 min-w-[44px] shrink-0 items-center justify-center rounded text-slate-400 transition-colors hover:bg-slate-200/80 hover:text-slate-600;
}

.tab-rename:focus-visible {
  @apply outline-none ring-2 ring-teal-400;
}

.tab-label {
  @apply truncate text-xs;
}

.tab-edit-input {
  @apply min-h-11 w-full rounded bg-slate-50 px-1 py-0.5 text-xs text-slate-800 outline-none ring-1 ring-rose-300;
}

.tab-close {
  /* DB-12: tap target ≥44px (icon stays small via inner span). */
  @apply shrink-0 p-0.5 rounded hover:bg-slate-200/80 text-slate-400 hover:text-slate-600 transition-colors min-w-[44px] min-h-11 flex items-center justify-center;
}

.tab-overflow-trigger {
  @apply flex items-center justify-center gap-1 px-2 py-1.5 rounded-lg
         hover:bg-slate-200/80 text-slate-400 hover:text-slate-600 transition-colors shrink-0
         min-w-[44px] min-h-11;
}

.tab-overflow-trigger:focus-visible {
  @apply outline-none ring-2 ring-teal-400;
}

.overflow-dropdown {
  @apply absolute right-2 top-full mt-1 bg-white/[.98] backdrop-blur-sm rounded-xl border border-slate-200/50 shadow-xl
         py-1 min-w-[200px] max-h-[300px] overflow-y-auto z-dropdown;
}

.overflow-item {
  @apply flex items-center gap-1.5 px-3 py-2 text-slate-500
         hover:bg-slate-50 hover:text-slate-700 transition-colors;
}

.overflow-item.active {
  @apply bg-slate-50/80 text-slate-800;
}

.overflow-main {
  @apply flex items-center gap-1.5 min-w-0 flex-1 text-left rounded;
}

.overflow-edit {
  @apply min-w-0 flex-1;
}

.overflow-main:focus-visible {
  @apply outline-none ring-2 ring-teal-400;
}

/* Dark styles for this tab bar are owned by the main.css remap rules
 * `html.dark .workflow-tab-bar .tab-item[.active/:hover]` and
 * `.overflow-item[:hover/.active]` (!important). The former scoped
 * `:global(html.dark) …` duplicates here compiled to bare `html.dark`
 * and could never win over the !important layer, so they were removed. */
</style>
