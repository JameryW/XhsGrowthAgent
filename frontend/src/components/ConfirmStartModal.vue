<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import { useFocusTrap } from '@/composables/useFocusTrap'

const { t } = useI18n()

const props = defineProps<{
  isOpen: boolean
  accountId: string
  accountName?: string
  phase: string
  dryRun: boolean
  autoPublish: boolean
  niche?: string
  workflowMode?: 'trend' | 'brief'
  briefText?: string
  isLoading: boolean
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

// Dialog semantics: trap Tab inside while open, focus the primary action on
// open, and restore focus to the trigger element on close (composable-owned).
const focusTrap = useFocusTrap()
const modalRef = ref<HTMLElement | null>(null)
const confirmButtonRef = ref<InstanceType<typeof NeonButton> | null>(null)

watch(() => props.isOpen, async (isOpen) => {
  if (isOpen) {
    await nextTick()
    await focusTrap.activate(modalRef.value)
    // Focus the primary action rather than the first focusable (cancel).
    ;(confirmButtonRef.value?.$el as HTMLElement | undefined)?.focus()
  } else {
    focusTrap.deactivate()
  }
})

const phaseLabel = (phase: string) => {
  const map: Record<string, string> = {
    scouting: 'dashboard.timeline.scouting',
    planning: 'dashboard.timeline.planning',
    creating: 'dashboard.timeline.creating',
    visual: 'dashboard.timeline.visual',
    reviewing: 'dashboard.timeline.reviewing',
    publishing: 'dashboard.timeline.publishing',
  }
  return t(map[phase] || `dashboard.timeline.${phase}`)
}

const allSteps = computed(() => {
  if (props.workflowMode === 'brief') {
    return [
      { phase: 'briefing', label: t('dashboard.phase.briefing') },
      { phase: 'creating', label: t('dashboard.timeline.creating') },
      { phase: 'visual', label: t('dashboard.timeline.visual') },
      { phase: 'ripple', label: t('dashboard.ripple.title') },
    ]
  }
  return [
    { phase: 'scouting', label: t('dashboard.timeline.scouting') },
    { phase: 'planning', label: t('dashboard.timeline.planning') },
    { phase: 'creating', label: t('dashboard.timeline.creating') },
    { phase: 'visual', label: t('dashboard.timeline.visual') },
    { phase: 'reviewing', label: t('dashboard.timeline.reviewing') },
    { phase: 'publishing', label: t('dashboard.timeline.publishing') },
  ]
})

const expectedSteps = computed(() => {
  if (props.workflowMode === 'brief') {
    // Brief mode always starts from briefing
    return allSteps.value
  }
  const phaseOrder = ['scouting', 'planning', 'creating', 'visual', 'reviewing', 'publishing']
  const startIdx = phaseOrder.indexOf(props.phase)
  if (startIdx < 0) return allSteps.value
  return allSteps.value.slice(startIdx)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="isOpen"
        class="fixed inset-0 z-50 flex items-center justify-center p-4"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-start-title"
        @keydown.esc="emit('cancel')"
      >
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" aria-hidden="true" @click="emit('cancel')" />

        <!-- Modal -->
        <div ref="modalRef" class="relative liquid-glass-elevated rounded-2xl max-w-md w-full overflow-hidden">
          <!-- Header -->
          <div class="p-5 border-b border-slate-100">
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-rose-400 to-amber-400 flex items-center justify-center">
                <AppIcon name="Rocket" size="md" variant="white" />
              </div>
              <div>
                <h3 id="confirm-start-title" class="text-lg font-semibold text-slate-800">{{ t('home.confirm.title') }}</h3>
                <p class="text-xs text-slate-400">{{ t('home.confirm.subtitle') }}</p>
              </div>
            </div>
          </div>

          <!-- Config Summary -->
          <div class="p-5 space-y-3">
            <div class="flex items-center justify-between py-2">
              <span class="text-sm text-slate-500">{{ t('home.form.workflowMode') }}</span>
              <span class="text-sm font-medium text-rose-600 bg-rose-50 px-2 py-0.5 rounded">
                {{ workflowMode === 'brief' ? t('home.briefMode') : t('home.trendMode') }}
              </span>
            </div>
            <div class="flex items-center justify-between py-2">
              <span class="text-sm text-slate-500">{{ t('home.form.accountId') }}</span>
              <span class="max-w-[65%] truncate text-sm font-medium text-slate-700" :title="accountName || accountId">
                {{ accountName || accountId }}
              </span>
            </div>
            <div v-if="niche" class="flex items-center justify-between py-2">
              <span class="text-sm text-slate-500">{{ t('home.form.niche') }}</span>
              <span class="text-sm font-medium text-rose-600 bg-rose-50 px-2 py-0.5 rounded">{{ niche }}</span>
            </div>
            <div v-if="workflowMode !== 'brief'" class="flex items-center justify-between py-2">
              <span class="text-sm text-slate-500">{{ t('home.form.startPhase') }}</span>
              <span class="text-sm font-medium text-slate-700">{{ phaseLabel(phase) }}</span>
            </div>
            <div v-if="workflowMode === 'brief' && briefText" class="py-2">
              <span class="text-sm text-slate-500 block mb-1">{{ t('home.form.briefText') }}</span>
              <p class="text-xs text-slate-600 bg-slate-50 rounded-lg p-2 max-h-24 overflow-y-auto line-clamp-4 dark:bg-slate-800/70 dark:text-slate-300">{{ briefText }}</p>
            </div>
            <div class="flex items-center justify-between py-2">
              <span class="text-sm text-slate-500">{{ t('home.form.dryRun') }}</span>
              <span :class="['text-sm font-medium', dryRun ? 'text-teal-600' : 'text-slate-700']">
                {{ dryRun ? t('home.confirm.enabled') : t('home.confirm.disabled') }}
              </span>
            </div>
            <div class="flex items-center justify-between py-2">
              <span class="text-sm text-slate-500">{{ t('home.form.autoPublish') }}</span>
              <span :class="['text-sm font-medium', autoPublish ? 'text-rose-600' : 'text-slate-700']">
                {{ autoPublish ? t('home.confirm.enabled') : t('home.confirm.disabled') }}
              </span>
            </div>

            <!-- Warnings -->
            <div v-if="!dryRun" class="mt-3 p-3 rounded-lg liquid-glass-amber liquid-glass-hover">
              <div class="flex items-start gap-2">
                <AppIcon name="AlertTriangle" size="sm" variant="peach" />
                <p class="text-xs text-amber-700">{{ t('home.confirm.liveWarning') }}</p>
              </div>
            </div>
            <div v-if="autoPublish" class="mt-2 p-3 rounded-lg liquid-glass-rose liquid-glass-hover">
              <div class="flex items-start gap-2">
                <AppIcon name="AlertTriangle" size="sm" variant="pink" />
                <p class="text-xs text-rose-700">{{ t('home.confirm.autoPublishWarning') }}</p>
              </div>
            </div>

            <!-- Steps preview -->
            <div class="mt-3 p-3 rounded-lg liquid-glass-inset">
              <p class="text-xs font-medium text-slate-500 mb-2">{{ t('home.confirm.expectedSteps') }}</p>
              <div class="flex flex-wrap gap-1.5">
                <span v-for="(step, idx) in expectedSteps" :key="step.phase"
                  class="text-xs px-2 py-1 rounded border text-slate-600"
                  :class="idx === 0 ? 'bg-rose-50 border-rose-200 text-rose-600 font-medium dark:bg-rose-950/40 dark:border-rose-500/30 dark:text-rose-300' : 'bg-white border-slate-200 dark:bg-slate-900 dark:border-slate-600'">
                  {{ step.label }}
                </span>
              </div>
            </div>
          </div>

          <!-- Actions -->
          <div class="p-5 border-t border-slate-100 flex gap-3">
            <NeonButton variant="ghost" class="flex-1" @click="emit('cancel')" :disabled="isLoading">
              {{ t('common.cancel') }}
            </NeonButton>
            <NeonButton ref="confirmButtonRef" variant="pink" class="flex-1" @click="emit('confirm')" :loading="isLoading">
              <span class="inline-flex items-center gap-2">
                <AppIcon name="Rocket" size="sm" variant="white" />
                {{ t('home.confirm.start') }}
              </span>
            </NeonButton>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: all 0.2s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
.modal-enter-from > div:last-child,
.modal-leave-to > div:last-child {
  transform: scale(0.95);
}
</style>
