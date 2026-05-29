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

// Optimization flow state
const showDraftInput = ref(false)

// Optimization flow computed
const isOptimizationPending = computed(() =>
  workflowStore.currentPhase === 'creating' &&
  optimizationStore.contentVersions.length > 0 &&
  !optimizationStore.selectedVersion
)

const isDraftInputPending = computed(() =>
  workflowStore.currentPhase === 'creating' &&
  !optimizationStore.draftContent &&
  !isOptimizationPending.value
)

// Operations
const startOptimization = () => {
  showDraftInput.value = true
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
  <div v-if="workflowStore.currentPhase === 'creating'" class="space-y-4" role="region" :aria-label="t('dashboard.optimization.title')">
    <!-- Optimization prompt when draft input is pending -->
    <div v-if="isDraftInputPending && !showDraftInput" class="rounded-xl p-5 bg-gradient-to-r from-neon-cyan/5 to-neon-purple/5 border border-neon-cyan/20" role="status" aria-live="polite">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <AppIcon name="Sparkles" size="md" variant="cyan" aria-hidden="true" />
          <div>
            <span class="text-sm font-medium text-slate-700">{{ t('dashboard.optimization.title') }}</span>
            <span class="text-xs text-slate-400 ml-2">{{ t('dashboard.optimization.desc') }}</span>
          </div>
        </div>
        <NeonButton variant="cyan" @click="startOptimization" :aria-label="t('dashboard.optimization.desc')">
          <AppIcon name="Wand2" size="sm" variant="white" aria-hidden="true" />
          <span>{{ t('draft.startOptimization') }}</span>
        </NeonButton>
      </div>
    </div>

    <!-- Draft Input Component -->
    <DraftInput
      v-if="showDraftInput"
      :is-loading="optimizationStore.isLoading"
      @submit="handleDraftSubmit"
    />

    <!-- Version Compare Component (when versions are available) -->
    <VersionCompare
      v-if="isOptimizationPending"
      :versions="optimizationStore.contentVersions"
      :analysis="optimizationStore.optimizationAnalysis"
      :is-loading="optimizationStore.isLoading"
      @select="handleVersionSelect"
    />
  </div>
</template>