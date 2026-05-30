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
import type { WorkflowConfig } from '@/components/WorkflowStartForm.vue'
import { useWorkflowStore } from '@/stores'

const { t } = useI18n()

const router = useRouter()
const route = useRoute()
const workflowStore = useWorkflowStore()
const isStarting = ref(false)
const showConfirm = ref(false)
const showForm = ref(true)
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
})

// Check for topic query param from analytics
onMounted(() => {
  const topic = route.query.topic as string
  if (topic) {
    prefilledTopic.value = topic
    showForm.value = true
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
      { dryRun: formConfig.value.dryRun, autoPublish: formConfig.value.autoPublish, topic: formConfig.value.topic, niche: formConfig.value.niche }
    )
    showConfirm.value = false
    router.push('/dashboard')
  } finally {
    isStarting.value = false
  }
}

const quickStart = () => {
  // Use default config but still go through confirmation
  formConfig.value = {
    accountId: 'default',
    phase: 'scouting',
    dryRun: true,
    autoPublish: false,
    niche: '母婴',
  }
  showConfirm.value = true
}
</script>

<template>
  <div class="min-h-[80vh] flex flex-col items-center justify-center">
    <div class="w-full max-w-lg space-y-4">
      <!-- Pre-Launch Checklist -->
      <PreLaunchChecklist ref="checklistRef" />

      <!-- Main Card -->
      <div class="rounded-2xl p-8 bg-white border border-slate-200/50 shadow-sm">
        <div class="text-center mb-8">
          <div class="w-16 h-16 rounded-xl bg-gradient-to-br from-rose-400 to-rose-500 flex items-center justify-center shadow-sm mx-auto mb-4">
            <AppIcon name="Rocket" size="xl" variant="white" />
          </div>
          <h1 class="text-2xl font-bold mb-2 text-slate-800">{{ t('home.title') }}</h1>
          <p class="text-sm text-slate-500">{{ t('home.subtitle') }}</p>
        </div>

        <!-- Pre-filled topic from analytics -->
        <div v-if="prefilledTopic" class="mb-4 p-3 rounded-lg bg-teal-50 border border-teal-100 flex items-center gap-2">
          <AppIcon name="Sparkles" size="sm" variant="cyan" />
          <div class="flex-1">
            <span class="text-xs text-teal-500 font-medium">{{ t('home.recommendedTopic') }}</span>
            <p class="text-sm text-teal-700 font-semibold">{{ prefilledTopic }}</p>
          </div>
          <button @click="prefilledTopic = null" class="text-teal-400 hover:text-teal-600 transition-colors">
            <AppIcon name="X" size="sm" variant="cyan" />
          </button>
        </div>

        <!-- Configuration Form (expandable) -->
        <div v-if="showForm" class="mb-6">
          <WorkflowStartForm ref="startFormRef" :initial-topic="prefilledTopic || undefined" />
        </div>

        <div class="space-y-3">
          <!-- Primary: Start with config -->
          <NeonButton
            v-if="showForm"
            variant="pink"
            size="lg"
            class="w-full group/btn"
            @click="handleFormSubmit()"
            :aria-label="t('home.startWorkflow')"
          >
            <span class="inline-flex items-center gap-3 transition-transform duration-200 group-hover/btn:translate-x-1">
              <AppIcon name="Rocket" size="md" variant="white" aria-hidden="true" />
              <span class="font-medium">{{ t('home.startWorkflow') }}</span>
            </span>
          </NeonButton>

          <!-- Quick start or show config -->
          <template v-if="!showForm">
            <NeonButton variant="pink" size="lg" class="w-full group/btn" @click="quickStart" :loading="isStarting" :aria-label="t('home.startWorkflow')">
              <span class="inline-flex items-center gap-3 transition-transform duration-200 group-hover/btn:translate-x-1">
                <AppIcon name="Rocket" size="md" variant="white" aria-hidden="true" />
                <span class="font-medium">{{ t('home.startWorkflow') }}</span>
              </span>
            </NeonButton>

            <NeonButton variant="ghost" size="md" class="w-full" @click="showForm = true" :disabled="isStarting">
              <span class="inline-flex items-center gap-3">
                <AppIcon name="Settings" size="md" variant="cyan" aria-hidden="true" />
                <span>{{ t('home.customStart') }}</span>
              </span>
            </NeonButton>
          </template>

          <NeonButton v-if="showForm" variant="ghost" size="sm" class="w-full" @click="showForm = false">
            {{ t('home.quickStart') }}
          </NeonButton>

          <!-- Navigation buttons -->
          <div class="flex gap-3">
            <NeonButton variant="ghost" size="md" class="flex-1" @click="goToDashboard" :disabled="isStarting" :aria-label="t('home.viewDashboard')">
              <span class="inline-flex items-center gap-2">
                <AppIcon name="BarChart3" size="sm" variant="cyan" aria-hidden="true" />
                <span class="text-sm">{{ t('home.viewDashboard') }}</span>
              </span>
            </NeonButton>

            <NeonButton variant="ghost" size="md" class="flex-1" @click="goToHistory" :disabled="isStarting">
              <span class="inline-flex items-center gap-2">
                <AppIcon name="History" size="sm" variant="purple" aria-hidden="true" />
                <span class="text-sm">{{ t('home.history') }}</span>
              </span>
            </NeonButton>
          </div>
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
