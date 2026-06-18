<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import DraftInput from '@/components/DraftInput.vue'
import VersionCompare from '@/components/VersionCompare.vue'
import { useWorkflowStore, useOptimizationStore } from '@/stores'
import type { DraftContent, VersionChoice } from '@/types/optimization'

const { t } = useI18n()
const workflowStore = useWorkflowStore()
const optimizationStore = useOptimizationStore()

// Replay-aware: use effectiveState when in replay mode
const es = computed(() =>
  (workflowStore.isReplayMode ? workflowStore.effectiveState : workflowStore.workflowState) as any
)

// Optimization flow state
const showDraftInput = ref(false)

// Optimization flow computed
const workflowVersions = computed(() =>
  es.value?.content_versions || []
)
const optimizationStoreMatchesThread = computed(() =>
  optimizationStore.activeThreadId === workflowStore.currentThreadId
)
const contentVersions = computed(() =>
  optimizationStoreMatchesThread.value && optimizationStore.contentVersions.length > 0
    ? optimizationStore.contentVersions
    : workflowVersions.value
)
const optimizationAnalysis = computed(() =>
  (optimizationStoreMatchesThread.value ? optimizationStore.optimizationAnalysis : null) ||
  es.value?.optimization_analysis ||
  null
)
const generatedDraft = computed<DraftContent | null>(() => {
  const copy = workflowStore.copyContent
  const text = copy.body_text?.trim()
  if (!text) return null

  return {
    title: copy.selected_title || copy.title_candidates?.[0] || undefined,
    text,
    hashtags: copy.hashtags || undefined,
  }
})
const hasGeneratedDraft = computed(() => !!generatedDraft.value?.text)

const isOptimizationPending = computed(() =>
  workflowStore.isAwaitingChoice &&
  contentVersions.value.length > 0 &&
  !(optimizationStoreMatchesThread.value && optimizationStore.selectedVersion)
)

const isDraftInputPending = computed(() =>
  workflowStore.isAwaitingDraft &&
  !isOptimizationPending.value
)

const shouldShowDraftInput = computed(() =>
  workflowStore.isAwaitingDraft && (showDraftInput.value || isDraftInputPending.value)
)

// Operations

const useGeneratedDraft = () => {
  if (!generatedDraft.value) return

  optimizationStore.submitDraft({
    ...generatedDraft.value,
    provided_at: new Date().toISOString(),
  }, [])
}

const handleDraftSubmit = (draft: DraftContent, viralLinks: string[]) => {
  optimizationStore.submitDraft(draft, viralLinks)
  showDraftInput.value = false
  // Workflow continues to viral_matcher node automatically
}

const handleVersionSelect = (choice: VersionChoice) => {
  optimizationStore.selectVersion(choice)
  // Workflow continues to visual_designer node automatically
}
</script>

<template>
  <div v-if="shouldShowDraftInput || isOptimizationPending" class="space-y-4" role="region" :aria-label="t('dashboard.optimization.title')">
    <!-- Draft input when awaiting draft -->
    <div v-if="isDraftInputPending && !showDraftInput" class="rounded-xl p-3 md:p-5 bg-gradient-to-r from-neon-cyan/5 to-neon-purple/5 border border-neon-cyan/20" role="status" aria-live="polite">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <AppIcon name="Sparkles" size="md" variant="cyan" aria-hidden="true" />
          <div>
            <span class="text-sm font-medium text-slate-700">{{ t('dashboard.optimization.title') }}</span>
            <span class="text-xs text-slate-400 ml-2">{{ t('dashboard.optimization.desc') }}</span>
          </div>
        </div>
        <div class="flex gap-2">
          <NeonButton
            v-if="hasGeneratedDraft"
            variant="cyan"
            :loading="optimizationStore.isLoading"
            @click="useGeneratedDraft"
            :aria-label="t('draft.useGeneratedDraft')"
          >
            <AppIcon name="Sparkles" size="sm" variant="white" aria-hidden="true" />
            <span>{{ t('draft.useGeneratedDraft') }}</span>
          </NeonButton>
          <NeonButton
            :variant="hasGeneratedDraft ? 'ghost' : 'cyan'"
            @click="showDraftInput = true"
            :aria-label="hasGeneratedDraft ? t('draft.editGeneratedDraft') : t('dashboard.optimization.desc')"
          >
            <AppIcon name="Wand2" size="sm" :variant="hasGeneratedDraft ? 'cyan' : 'white'" aria-hidden="true" />
            <span>{{ hasGeneratedDraft ? t('draft.editGeneratedDraft') : t('draft.startOptimization') }}</span>
          </NeonButton>
        </div>
      </div>
    </div>

    <!-- Draft Input Component -->
    <DraftInput
      v-if="showDraftInput"
      :is-loading="optimizationStore.isLoading"
      :initial-draft="generatedDraft"
      @submit="handleDraftSubmit"
    />

    <!-- Version Compare Component (when versions are available) -->
    <VersionCompare
      v-if="isOptimizationPending"
      :versions="contentVersions"
      :analysis="optimizationAnalysis"
      :is-loading="optimizationStore.isLoading"
      @select="handleVersionSelect"
    />
  </div>
</template>
