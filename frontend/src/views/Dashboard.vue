<script setup lang="ts">
import { onMounted, onUnmounted, computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import WorkflowHeader from '@/components/dashboard/WorkflowHeader.vue'
import WorkflowTimeline from '@/components/dashboard/WorkflowTimeline.vue'
import ContentCards from '@/components/dashboard/ContentCards.vue'
import OptimizationPanel from '@/components/dashboard/OptimizationPanel.vue'
import ActionButtons from '@/components/dashboard/ActionButtons.vue'
import CelebrationModal from '@/components/CelebrationModal.vue'
import ProgressPhase from '@/components/ProgressPhase.vue'
import StepIndicator from '@/components/StepIndicator.vue'
import { DashboardSkeleton } from '@/components/skeletons'
import ErrorState from '@/components/ErrorState.vue'
import ErrorCard from '@/components/ErrorCard.vue'
import { useWorkflowStore, useToastStore, useErrorStore } from '@/stores'

const { t } = useI18n()
const router = useRouter()
const workflowStore = useWorkflowStore()
const toastStore = useToastStore()
const errorStore = useErrorStore()

const showOptimization = computed(() => workflowStore.currentPhase === 'creating')
const isLoading = computed(() => workflowStore.isLoading && !workflowStore.workflowState)
const hasError = computed(() => workflowStore.error !== null)

// Workflow steps for step indicator
const workflowSteps = computed(() => {
  const phases = ['scouting', 'planning', 'creating', 'reviewing', 'publishing', 'analyzing', 'engaging', 'completed']
  const currentPhase = workflowStore.currentPhase || 'idle'
  const currentIndex = phases.indexOf(currentPhase)
  return phases.map((phase, index) => ({
    name: phase,
    status: (index < currentIndex ? 'completed' :
            index === currentIndex ? 'active' : 'pending') as 'completed' | 'active' | 'pending'
  }))
})

// Celebration state
const showCelebration = ref(false)
const hasShownCelebration = ref(false)

// Watch for workflow completion
watch(
  () => workflowStore.currentPhase,
  (newPhase, oldPhase) => {
    if (newPhase === 'completed' && oldPhase !== 'completed' && !hasShownCelebration.value) {
      showCelebration.value = true
      hasShownCelebration.value = true
      toastStore.success(t('dashboard.completed'), t('dashboard.completedMessage'))
    }
  }
)

const handleCloseCelebration = () => {
  showCelebration.value = false
}

// ErrorCard handlers
const handleErrorRetry = () => {
  errorStore.clearError()
  workflowStore.startWorkflow('default')
}

const handleErrorDismiss = () => {
  errorStore.clearError()
}

onMounted(() => {
  if (workflowStore.currentThreadId) {
    workflowStore.refreshStatus()
    workflowStore.startPolling(5000)
  }
})

onUnmounted(() => {
  workflowStore.stopPolling()
})
</script>

<template>
  <div class="dashboard-container">
    <DashboardSkeleton v-if="isLoading" />
    <div v-else class="space-y-6">
      <ErrorState v-if="hasError" />

      <!-- ErrorCard for API errors -->
      <ErrorCard
        v-if="errorStore.hasError && errorStore.errorType"
        :type="errorStore.errorType"
        :message="errorStore.errorMessage"
        :retry-count="errorStore.retryCount"
        @retry="handleErrorRetry"
        @dismiss="handleErrorDismiss"
      />

      <!-- Publish Error Recovery -->
      <div v-if="workflowStore.publishError" class="rounded-2xl p-5 bg-rose-50/80 border border-rose-200/50 shadow-sm">
        <div class="flex items-start gap-3">
          <div class="w-10 h-10 rounded-xl bg-rose-100 flex items-center justify-center flex-shrink-0">
            <AppIcon name="AlertTriangle" size="md" variant="pink" />
          </div>
          <div class="flex-1">
            <div class="text-rose-700 font-semibold text-sm mb-1">{{ t('dashboard.publishFailed') }}</div>
            <p class="text-rose-600 text-sm mb-2">{{ workflowStore.publishError.message }}</p>
            <div v-if="workflowStore.publishError.recovery" class="space-y-2">
              <p class="text-xs text-rose-500">{{ workflowStore.publishError.recovery.hint }}</p>
              <div class="flex items-center gap-2">
                <!-- Retry (network errors) -->
                <button
                  v-if="workflowStore.publishError.recovery.action === 'retry'"
                  @click="workflowStore.resumeWorkflow()"
                  class="text-xs px-3 py-1.5 rounded-lg bg-rose-100 text-rose-600 hover:bg-rose-200 transition-colors font-medium"
                >
                  {{ workflowStore.publishError.recovery.action_label }}
                </button>
                <!-- Revise content (content violation) -->
                <button
                  v-if="workflowStore.publishError.recovery.action === 'revise_content'"
                  @click="router.push('/review')"
                  class="text-xs px-3 py-1.5 rounded-lg bg-amber-100 text-amber-600 hover:bg-amber-200 transition-colors font-medium"
                >
                  {{ workflowStore.publishError.recovery.action_label }}
                </button>
                <!-- Reconfigure (auth expired) -->
                <button
                  v-if="workflowStore.publishError.recovery.action === 'reconfigure'"
                  @click="router.push('/')"
                  class="text-xs px-3 py-1.5 rounded-lg bg-violet-100 text-violet-600 hover:bg-violet-200 transition-colors font-medium"
                >
                  {{ workflowStore.publishError.recovery.action_label }}
                </button>
                <!-- Retry later (rate limited) -->
                <button
                  v-if="workflowStore.publishError.recovery.action === 'retry_later'"
                  @click="workflowStore.resumeWorkflow()"
                  class="text-xs px-3 py-1.5 rounded-lg bg-amber-100 text-amber-600 hover:bg-amber-200 transition-colors font-medium"
                >
                  {{ workflowStore.publishError.recovery.action_label }}
                </button>
                <!-- Provide images -->
                <button
                  v-if="workflowStore.publishError.recovery.action === 'provide_images'"
                  @click="router.push('/review')"
                  class="text-xs px-3 py-1.5 rounded-lg bg-teal-100 text-teal-600 hover:bg-teal-200 transition-colors font-medium"
                >
                  {{ workflowStore.publishError.recovery.action_label }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Progress Phase and Step Indicator -->
      <div class="rounded-2xl p-5 relative overflow-hidden bg-white/98 backdrop-blur-sm border border-slate-200/50 shadow-sm">
        <ProgressPhase
          :percent="workflowStore.progressPercent"
          :current-phase="workflowStore.currentPhase"
        />
        <div class="mt-4">
          <StepIndicator :steps="workflowSteps" layout="vertical" />
        </div>
      </div>

      <WorkflowHeader />
      <!-- Workflow timeline with onboarding selector -->
      <div class="workflow-timeline">
        <WorkflowTimeline />
      </div>
      <ContentCards />
      <OptimizationPanel v-if="showOptimization" />
      <!-- Action buttons with onboarding selector -->
      <div class="action-buttons">
        <ActionButtons />
      </div>
    </div>

    <!-- Celebration Modal -->
    <CelebrationModal
      :show="showCelebration"
      @close="handleCloseCelebration"
    />
  </div>
</template>