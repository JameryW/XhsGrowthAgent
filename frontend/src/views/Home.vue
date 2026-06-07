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
const showForm = ref(false)
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
    showForm.value = true
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

const quickStart = () => {
  formConfig.value = {
    accountId: 'default',
    phase: 'scouting',
    dryRun: true,
    autoPublish: false,
    niche: '母婴',
    workflowMode: 'trend' as WorkflowMode,
  }
  showConfirm.value = true
}
</script>

<template>
  <div class="min-h-[80vh] flex flex-col justify-center">
    <div class="w-full max-w-3xl mx-auto px-3 md:px-8">
      <!-- Hero: title + primary CTA -->
      <div class="text-center mb-6 md:mb-8">
        <div class="w-10 h-10 md:w-14 md:h-14 rounded-lg md:rounded-xl bg-gradient-to-br from-rose-400 to-rose-500 flex items-center justify-center shadow-sm mx-auto mb-3 md:mb-4">
          <AppIcon name="Rocket" size="md" variant="white" class="md:hidden" />
          <AppIcon name="Rocket" size="lg" variant="white" class="hidden md:block" />
        </div>
        <h1 class="text-xl md:text-2xl font-bold text-slate-800 mb-1">{{ t('home.title') }}</h1>
        <p class="text-xs md:text-sm text-slate-400">{{ t('home.subtitle') }}</p>
      </div>

      <!-- Pre-filled topic from analytics -->
      <div v-if="prefilledTopic" class="mb-3 md:mb-4 p-2.5 md:p-3 rounded-lg bg-teal-50 border border-teal-100 flex items-center gap-2">
        <AppIcon name="Sparkles" size="sm" variant="cyan" />
        <div class="flex-1 min-w-0">
          <span class="text-[10px] md:text-xs text-teal-500 font-medium">{{ t('home.recommendedTopic') }}</span>
          <p class="text-xs md:text-sm text-teal-700 font-semibold truncate">{{ prefilledTopic }}</p>
        </div>
        <button @click="prefilledTopic = null" class="text-teal-400 hover:text-teal-600 transition-colors flex-shrink-0">
          <AppIcon name="X" size="sm" variant="cyan" />
        </button>
      </div>

      <!-- Primary action card -->
      <div class="rounded-xl md:rounded-2xl p-4 md:p-6 lg:p-8 bg-white border border-slate-200/50 shadow-sm mb-3 md:mb-4">
        <!-- Quick start (default) -->
        <template v-if="!showForm">
          <NeonButton
            variant="pink"
            size="md"
            class="w-full group/btn md:size-lg"
            @click="quickStart"
            :loading="isStarting"
            :aria-label="t('home.startWorkflow')"
          >
            <span class="inline-flex items-center gap-3 transition-transform duration-200 group-hover/btn:translate-x-1">
              <AppIcon name="Rocket" size="md" variant="white" aria-hidden="true" />
              <span class="font-semibold">{{ t('home.startWorkflow') }}</span>
            </span>
          </NeonButton>
          <div class="mt-3 md:mt-4 flex items-center justify-center gap-3">
            <div class="h-px flex-1 bg-slate-100" />
            <span class="text-xs text-slate-400">{{ t('home.form.options') }}</span>
            <div class="h-px flex-1 bg-slate-100" />
          </div>
          <button
            class="mt-2 md:mt-3 w-full text-center text-xs md:text-sm text-slate-500 hover:text-cyan-600 transition-colors flex items-center justify-center gap-1.5"
            @click="showForm = true"
          >
            <AppIcon name="Settings" size="sm" variant="cyan" />
            <span>{{ t('home.customStart') }}</span>
          </button>
        </template>

        <!-- Configuration form (expanded) -->
        <template v-else>
          <div class="flex items-center justify-between mb-4">
            <h2 class="text-sm font-semibold text-slate-700">{{ t('home.customStart') }}</h2>
            <button
              class="text-xs text-slate-400 hover:text-slate-600 transition-colors flex items-center gap-1"
              @click="showForm = false"
            >
              <AppIcon name="Zap" size="sm" variant="cyan" />
              <span>{{ t('home.quickStart') }}</span>
            </button>
          </div>
          <WorkflowStartForm ref="startFormRef" :initial-topic="prefilledTopic || undefined" />
          <div class="mt-5">
            <NeonButton
              variant="pink"
              size="md"
              class="w-full group/btn md:size-lg"
              @click="handleFormSubmit()"
              :aria-label="t('home.startWorkflow')"
            >
              <span class="inline-flex items-center gap-3 transition-transform duration-200 group-hover/btn:translate-x-1">
                <AppIcon name="Rocket" size="md" variant="white" aria-hidden="true" />
                <span class="font-semibold">{{ t('home.startWorkflow') }}</span>
              </span>
            </NeonButton>
          </div>
        </template>
      </div>

      <!-- Secondary row: checklist + nav -->
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 md:gap-4">
        <!-- Pre-Launch Checklist -->
        <div class="rounded-xl p-3 md:p-4 bg-white/80 border border-slate-200/40">
          <PreLaunchChecklist ref="checklistRef" />
        </div>

        <!-- Navigation shortcuts -->
        <div class="rounded-xl p-3 md:p-4 bg-white/80 border border-slate-200/40 flex flex-col gap-2 md:gap-3">
          <span class="text-[10px] md:text-xs font-medium text-slate-500 uppercase tracking-wide">{{ t('home.systemStatus') }}</span>
          <NeonButton variant="cyan" size="sm" class="w-full md:size-md" @click="goToDashboard" :disabled="isStarting" :aria-label="t('home.viewDashboard')">
            <span class="inline-flex items-center gap-1.5 md:gap-2">
              <AppIcon name="BarChart3" size="sm" variant="white" aria-hidden="true" />
              <span class="text-xs md:text-sm">{{ t('home.viewDashboard') }}</span>
            </span>
          </NeonButton>
          <NeonButton variant="ghost" size="sm" class="w-full md:size-md" @click="goToHistory" :disabled="isStarting">
            <span class="inline-flex items-center gap-1.5 md:gap-2">
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
