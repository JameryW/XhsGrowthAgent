<script setup lang="ts">
import { onMounted, onUnmounted, computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import WorkflowTabBar from '@/components/dashboard/WorkflowTabBar.vue'
import WorkflowHeader from '@/components/dashboard/WorkflowHeader.vue'
import WorkflowTimeline from '@/components/dashboard/WorkflowTimeline.vue'
import ContentCards from '@/components/dashboard/ContentCards.vue'
import OptimizationPanel from '@/components/dashboard/OptimizationPanel.vue'
import ShootingPlanPanel from '@/components/dashboard/ShootingPlanPanel.vue'
import ActionButtons from '@/components/dashboard/ActionButtons.vue'
import BriefFileUpload from '@/components/BriefFileUpload.vue'
import CelebrationModal from '@/components/CelebrationModal.vue'
import { DashboardSkeleton } from '@/components/skeletons'
import ErrorState from '@/components/ErrorState.vue'
import ErrorCard from '@/components/ErrorCard.vue'
import { useWorkflowStore, useToastStore, useErrorStore } from '@/stores'

const { t } = useI18n()
const router = useRouter()
const workflowStore = useWorkflowStore()
const toastStore = useToastStore()
const errorStore = useErrorStore()

const showOptimization = computed(() =>
  workflowStore.currentPhase === 'creating' ||
  workflowStore.isAwaitingDraft ||
  workflowStore.isAwaitingChoice
)
const showShootingPlan = computed(() =>
  !!workflowStore.workflowState?.shooting_plan &&
  Object.keys(workflowStore.workflowState.shooting_plan).length > 0
)
const showBriefUpload = computed(() =>
  workflowStore.isAwaitingBrief ||
  (workflowStore.currentPhase === 'briefing' && !workflowStore.briefUploadedText)
)
const isLoading = computed(() => workflowStore.isLoading && !workflowStore.workflowState)
const hasError = computed(() => workflowStore.error !== null)

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

async function handleBriefConfirm(_text: string) {
  // Upload already updated state; resume workflow to proceed with brief_analyzer
  await workflowStore.resumeWorkflow()
  toastStore.success(t('brief.uploadSuccess'), t('brief.confirmed'))
}

function handleBriefClear() {
  workflowStore.clearBriefUpload()
}

onMounted(async () => {
  if (workflowStore.openTabIds.length > 0) {
    await workflowStore.refreshAllTabs()
    workflowStore.startPolling(5000)
  } else if (workflowStore.activeThreadId) {
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
    <!-- Workflow Tab Bar -->
    <WorkflowTabBar
      v-if="workflowStore.openTabIds.length > 0"
      :tabs="workflowStore.visibleTabs"
      :active-thread-id="workflowStore.activeThreadId"
      :has-overflow="workflowStore.hasOverflow"
      :overflow-tabs="workflowStore.overflowTabs"
      @switch="workflowStore.switchTab($event)"
      @close="workflowStore.closeTab($event)"
      @rename="(id, label) => workflowStore.renameTab(id, label)"
    />

    <DashboardSkeleton v-if="isLoading" />
    <div v-else class="space-y-4 md:space-y-6">
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

      <!-- Stale Workflow Recovery -->
      <div v-if="workflowStore.isStale" class="rounded-2xl p-4 bg-amber-50 border border-amber-200">
        <div class="flex items-start gap-3">
          <div class="w-10 h-10 rounded-lg bg-amber-100 flex items-center justify-center flex-shrink-0">
            <AppIcon name="AlertTriangle" size="md" variant="peach" />
          </div>
          <div class="flex-1">
            <div class="text-amber-700 font-semibold text-sm mb-1">{{ t('workflow.staleDetected') }}</div>
            <p class="text-amber-600 text-sm mb-2">{{ t('workflow.staleHint') }}</p>
            <div class="flex items-center gap-2">
              <button
                @click="workflowStore.resumeWorkflow()"
                class="btn-sm bg-amber-100 text-amber-600 hover:bg-amber-200"
              >
                {{ t('dashboard.actionButtons.resume') }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Publish Error Recovery -->
      <div v-if="workflowStore.publishError" class="card-error">
        <div class="flex items-start gap-3">
          <div class="w-10 h-10 rounded-lg bg-rose-100 flex items-center justify-center flex-shrink-0">
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
                  class="btn-sm bg-rose-100 text-rose-600 hover:bg-rose-200"
                >
                  {{ workflowStore.publishError.recovery.action_label }}
                </button>
                <!-- Revise content (content violation) -->
                <button
                  v-if="workflowStore.publishError.recovery.action === 'revise_content'"
                  @click="router.push('/review')"
                  class="btn-sm bg-amber-100 text-amber-600 hover:bg-amber-200"
                >
                  {{ workflowStore.publishError.recovery.action_label }}
                </button>
                <!-- Reconfigure (auth expired) -->
                <button
                  v-if="workflowStore.publishError.recovery.action === 'reconfigure'"
                  @click="router.push('/')"
                  class="btn-sm bg-violet-100 text-violet-600 hover:bg-violet-200"
                >
                  {{ workflowStore.publishError.recovery.action_label }}
                </button>
                <!-- Retry later (rate limited) -->
                <button
                  v-if="workflowStore.publishError.recovery.action === 'retry_later'"
                  @click="workflowStore.resumeWorkflow()"
                  class="btn-sm bg-amber-100 text-amber-600 hover:bg-amber-200"
                >
                  {{ workflowStore.publishError.recovery.action_label }}
                </button>
                <!-- Provide images -->
                <button
                  v-if="workflowStore.publishError.recovery.action === 'provide_images'"
                  @click="router.push('/review')"
                  class="btn-sm bg-teal-100 text-teal-600 hover:bg-teal-200"
                >
                  {{ workflowStore.publishError.recovery.action_label }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <WorkflowHeader />

      <!-- Brief PDF Upload (shown when awaiting brief input) -->
      <div v-if="showBriefUpload" class="rounded-2xl p-4 bg-gradient-to-br from-neon-pink/5 to-neon-peach/5 border border-neon-pink/20">
        <BriefFileUpload
          :is-uploading="workflowStore.isBriefUploading"
          :uploaded-text="workflowStore.briefUploadedText"
          :source-type="workflowStore.briefSourceType"
          :thread-id="workflowStore.currentThreadId || ''"
          @upload="(file: File) => workflowStore.uploadBriefPdf(workflowStore.currentThreadId!, file)"
          @confirm="handleBriefConfirm"
          @clear="handleBriefClear"
        />
      </div>

      <!-- Workflow timeline with onboarding selector -->
      <div class="workflow-timeline">
        <WorkflowTimeline />
      </div>
      <ContentCards />
      <ShootingPlanPanel v-if="showShootingPlan" />
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
