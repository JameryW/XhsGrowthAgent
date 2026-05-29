<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'

const { t } = useI18n()

const props = defineProps<{
  isOpen: boolean
  accountId: string
  phase: string
  dryRun: boolean
  autoPublish: boolean
  isLoading: boolean
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

const phaseLabels: Record<string, string> = {
  scouting: '趋势发现',
  planning: '策略规划',
  creating: '内容创作',
  reviewing: '内容审核',
}

const allSteps = [
  { phase: 'scouting', label: '趋势发现' },
  { phase: 'planning', label: '策略规划' },
  { phase: 'creating', label: '文案创作' },
  { phase: 'visual', label: '视觉设计' },
  { phase: 'reviewing', label: '人工审核' },
  { phase: 'publishing', label: '发布' },
]

const expectedSteps = computed(() => {
  const phaseOrder = ['scouting', 'planning', 'creating', 'visual', 'reviewing', 'publishing']
  const startIdx = phaseOrder.indexOf(props.phase)
  if (startIdx < 0) return allSteps
  return allSteps.slice(startIdx)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="isOpen" class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" @click="emit('cancel')" />

        <!-- Modal -->
        <div class="relative bg-white rounded-2xl shadow-2xl max-w-md w-full overflow-hidden">
          <!-- Header -->
          <div class="p-5 border-b border-slate-100">
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-rose-400 to-amber-400 flex items-center justify-center">
                <AppIcon name="Rocket" size="md" variant="white" />
              </div>
              <div>
                <h3 class="text-lg font-semibold text-slate-800">{{ t('home.confirm.title') }}</h3>
                <p class="text-xs text-slate-400">{{ t('home.confirm.subtitle') }}</p>
              </div>
            </div>
          </div>

          <!-- Config Summary -->
          <div class="p-5 space-y-3">
            <div class="flex items-center justify-between py-2">
              <span class="text-sm text-slate-500">{{ t('home.form.accountId') }}</span>
              <span class="text-sm font-medium text-slate-700">{{ accountId }}</span>
            </div>
            <div class="flex items-center justify-between py-2">
              <span class="text-sm text-slate-500">{{ t('home.form.startPhase') }}</span>
              <span class="text-sm font-medium text-slate-700">{{ phaseLabels[phase] || phase }}</span>
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
            <div v-if="!dryRun" class="mt-3 p-3 rounded-lg bg-amber-50 border border-amber-100">
              <div class="flex items-start gap-2">
                <AppIcon name="AlertTriangle" size="sm" variant="peach" />
                <p class="text-xs text-amber-700">{{ t('home.confirm.liveWarning') }}</p>
              </div>
            </div>
            <div v-if="autoPublish" class="mt-2 p-3 rounded-lg bg-rose-50 border border-rose-100">
              <div class="flex items-start gap-2">
                <AppIcon name="AlertTriangle" size="sm" variant="pink" />
                <p class="text-xs text-rose-700">{{ t('home.confirm.autoPublishWarning') }}</p>
              </div>
            </div>

            <!-- Steps preview -->
            <div class="mt-3 p-3 rounded-lg bg-slate-50 border border-slate-100">
              <p class="text-xs font-medium text-slate-500 mb-2">{{ t('home.confirm.expectedSteps') }}</p>
              <div class="flex flex-wrap gap-1.5">
                <span v-for="(step, idx) in expectedSteps" :key="step.phase"
                  class="text-xs px-2 py-1 rounded border text-slate-600"
                  :class="idx === 0 ? 'bg-rose-50 border-rose-200 text-rose-600 font-medium' : 'bg-white border-slate-200'">
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
            <NeonButton variant="pink" class="flex-1" @click="emit('confirm')" :loading="isLoading">
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
