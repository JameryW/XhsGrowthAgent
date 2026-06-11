<script setup lang="ts">
import { useRouter, useRoute } from 'vue-router'
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import LoadingOverlay from '@/components/LoadingOverlay.vue'
import PreLaunchChecklist from '@/components/PreLaunchChecklist.vue'
import WorkflowStartForm from '@/components/WorkflowStartForm.vue'
import ConfirmStartModal from '@/components/ConfirmStartModal.vue'
import type { WorkflowConfig, WorkflowMode } from '@/components/WorkflowStartForm.vue'
import { useWorkflowStore } from '@/stores'

const { t } = useI18n()

const router = useRouter()
const route = useRoute()
const workflowStore = useWorkflowStore()
const isStarting = ref(false)
const showConfirm = ref(false)
const startFormRef = ref<InstanceType<typeof WorkflowStartForm> | null>(null)
const checklistRef = ref<InstanceType<typeof PreLaunchChecklist> | null>(null)

// Pre-filled topic from analytics
const prefilledTopic = ref<string | null>(null)

// Form state
const formConfig = ref<WorkflowConfig>({
  accountId: 'default',
  phase: 'scouting',
  dryRun: true,
  autoPublish: false,
  niche: '母婴',
  workflowMode: 'trend' as WorkflowMode,
})

// Check for topic and niche query params from analytics
onMounted(() => {
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
  router.push('/dashboard')
}

const goToHistory = () => {
  router.push('/history')
}

const handleFormSubmit = () => {
  if (startFormRef.value) {
    formConfig.value = startFormRef.value.getConfig()
  }

  // Auto-set dry-run based on checklist recommendation
  if (checklistRef.value?.suggestedDryRun) {
    formConfig.value.dryRun = true
  }

  showConfirm.value = true
}

const confirmStart = async () => {
  isStarting.value = true
  try {
    await workflowStore.startWorkflow(
      formConfig.value.accountId,
      formConfig.value.phase,
      {
        dryRun: formConfig.value.dryRun,
        autoPublish: formConfig.value.autoPublish,
        topic: formConfig.value.topic,
        niche: formConfig.value.niche,
        workflowMode: formConfig.value.workflowMode,
        briefText: formConfig.value.briefText,
      }
    )
    showConfirm.value = false
    router.push('/dashboard')
  } finally {
    isStarting.value = false
  }
}
</script>

<template>
  <div class="min-h-[80vh] flex flex-col justify-center">
    <div class="w-full">
      <!-- Pre-filled topic from analytics -->
      <div v-if="prefilledTopic" class="mb-3 md:mb-4 p-2.5 md:p-3 rounded-lg liquid-glass-teal liquid-glass-hover flex items-center gap-2">
        <AppIcon name="Sparkles" size="sm" variant="cyan" />
        <div class="flex-1 min-w-0">
          <span class="text-[10px] md:text-xs text-teal-500 font-medium">{{ t('home.recommendedTopic') }}</span>
          <p class="text-xs md:text-sm text-teal-700 font-semibold truncate">{{ prefilledTopic }}</p>
        </div>
        <button @click="prefilledTopic = null" class="text-teal-400 hover:text-teal-600 transition-colors flex-shrink-0">
          <AppIcon name="X" size="sm" variant="cyan" />
        </button>
      </div>

      <!-- Configuration form -->
      <div class="rounded-xl md:rounded-2xl p-4 md:p-6 liquid-glass liquid-glass-hover mb-3 md:mb-4">
        <div class="flex items-center gap-2 mb-4">
          <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-rose-400 to-amber-400 flex items-center justify-center shadow-sm">
            <AppIcon name="Rocket" size="sm" variant="white" />
          </div>
          <h2 class="text-sm font-semibold text-slate-700">{{ t('home.startWorkflow') }}</h2>
        </div>
        <WorkflowStartForm ref="startFormRef" :initial-topic="prefilledTopic || undefined" />
        <div class="mt-5">
          <NeonButton
            variant="pink"
            size="md"
            class="w-full max-w-xs mx-auto group/btn"
            @click="handleFormSubmit()"
            :loading="isStarting"
            :aria-label="t('home.startWorkflow')"
          >
            <span class="inline-flex items-center gap-2 transition-transform duration-200 group-hover/btn:translate-x-1">
              <AppIcon name="Rocket" size="sm" variant="white" aria-hidden="true" />
              <span class="font-semibold">{{ t('home.startWorkflow') }}</span>
            </span>
          </NeonButton>
        </div>
      </div>

      <!-- Checklist + nav -->
      <div class="flex flex-col gap-3 md:gap-4">
        <PreLaunchChecklist ref="checklistRef" />

        <div class="flex gap-3 md:gap-4">
          <NeonButton variant="cyan" size="sm" class="flex-1" @click="goToDashboard" :disabled="isStarting" :aria-label="t('home.viewDashboard')">
            <span class="inline-flex items-center gap-1.5">
              <AppIcon name="BarChart3" size="sm" variant="white" aria-hidden="true" />
              <span class="text-xs md:text-sm">{{ t('home.viewDashboard') }}</span>
            </span>
          </NeonButton>
          <NeonButton variant="ghost" size="sm" class="flex-1" @click="goToHistory" :disabled="isStarting">
            <span class="inline-flex items-center gap-1.5">
              <AppIcon name="History" size="sm" variant="cyan" aria-hidden="true" />
              <span class="text-xs md:text-sm">{{ t('home.history') }}</span>
            </span>
          </NeonButton>
        </div>
      </div>
    </div>

    <!-- Confirmation Modal -->
    <ConfirmStartModal
      :is-open="showConfirm"
      :account-id="formConfig.accountId"
      :phase="formConfig.phase"
      :dry-run="formConfig.dryRun"
      :auto-publish="formConfig.autoPublish"
      :niche="formConfig.niche"
      :workflow-mode="formConfig.workflowMode"
      :brief-text="formConfig.briefText"
      :is-loading="isStarting"
      @confirm="confirmStart"
      @cancel="showConfirm = false"
    />

    <!-- Loading Overlay -->
    <LoadingOverlay
      :is-visible="workflowStore.isOverlayLoading"
      :message="t('home.loadingOverlay', { phase: workflowStore.currentPhase })"
      @cancel="workflowStore.cancelWorkflow"
    />
  </div>
</template>