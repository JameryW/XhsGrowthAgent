<script setup lang="ts">
import { ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import type { WorkflowStatus, WorkflowPhase } from '@/types/workflow'
import i18n from '@/locales'

const { t } = i18n.global

const props = defineProps<{
  tabs: Array<{ threadId: string; label: string; status: WorkflowStatus; phase: WorkflowPhase; progress: number }>
  activeThreadId: string | null
  hasOverflow: boolean
  overflowTabs: Array<{ threadId: string; label: string; status: WorkflowStatus; phase: WorkflowPhase; progress: number }>
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
    case 'running': return 'loader'
    case 'stale': return 'alert-circle'
    case 'awaiting_review':
    case 'awaiting_choice':
    case 'awaiting_draft':
    case 'awaiting_brief': return 'clock'
    case 'paused': return 'pause'
    case 'cancelled': return 'x-circle'
    case 'error': return 'alert-triangle'
    case 'completed': return 'check-circle'
    default: return 'circle'
  }
}

function statusColor(status: WorkflowStatus): string {
  switch (status) {
    case 'running': return 'text-emerald-400'
    case 'stale': return 'text-amber-400'
    case 'awaiting_review':
    case 'awaiting_choice':
    case 'awaiting_draft':
    case 'awaiting_brief': return 'text-orange-400'
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

        <button
          class="tab-close"
          @click="onCloseClick(tab.threadId, $event)"
          :title="t('workflow.closeTab')"
        >
          <AppIcon name="x" size="xs" />
        </button>
      </div>

      <div v-if="hasOverflow" class="tab-overflow-trigger" @click="toggleOverflow">
        <AppIcon name="chevron-down" size="sm" />
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
        <button class="tab-close" @click="onCloseClick(tab.threadId, $event)">
          <AppIcon name="x" size="xs" />
        </button>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="confirmCloseTabId" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" @click.self="cancelClose">
        <div class="bg-slate-800 rounded-lg p-5 shadow-xl max-w-sm w-full border border-slate-700">
          <h3 class="text-white font-medium mb-2">{{ t('workflow.closeTabConfirm') }}</h3>
          <p class="text-slate-400 text-sm mb-4">{{ t('workflow.closeTabHint') }}</p>
          <div class="flex gap-3 justify-end">
            <button class="px-3 py-1.5 text-sm rounded bg-slate-700 text-slate-300 hover:bg-slate-600" @click="cancelClose">
              {{ t('common.cancel') }}
            </button>
            <button class="px-3 py-1.5 text-sm rounded bg-red-600 text-white hover:bg-red-500" @click="confirmClose">
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
  @apply flex items-center gap-1 overflow-x-auto px-2 py-1;
  scrollbar-width: thin;
}

.tab-item {
  @apply flex items-center gap-1.5 px-3 py-1.5 rounded-t-lg cursor-pointer
         bg-slate-800/60 text-slate-400 hover:bg-slate-700/60 hover:text-slate-300
         transition-colors max-w-[180px] min-w-[100px] shrink-0 select-none;
}

.tab-item.active {
  @apply bg-slate-700 text-white border-b-2 border-indigo-500;
}

.tab-icon {
  @apply shrink-0;
}

.tab-label {
  @apply truncate text-xs;
}

.tab-edit-input {
  @apply bg-slate-600 text-white text-xs px-1 py-0.5 rounded w-full outline-none border border-indigo-500;
}

.tab-close {
  @apply shrink-0 p-0.5 rounded hover:bg-slate-600 text-slate-500 hover:text-slate-300 transition-colors;
}

.tab-overflow-trigger {
  @apply flex items-center gap-1 px-2 py-1.5 rounded cursor-pointer
         hover:bg-slate-700/60 text-slate-400 hover:text-slate-300 transition-colors shrink-0;
}

.overflow-dropdown {
  @apply absolute right-2 top-full mt-1 bg-slate-800 rounded-lg border border-slate-700
         shadow-xl py-1 min-w-[200px] max-h-[300px] overflow-y-auto z-40;
}

.overflow-item {
  @apply flex items-center gap-1.5 px-3 py-2 cursor-pointer text-slate-400
         hover:bg-slate-700 hover:text-slate-300 transition-colors;
}

.overflow-item.active {
  @apply bg-slate-700/60 text-white;
}
</style>
