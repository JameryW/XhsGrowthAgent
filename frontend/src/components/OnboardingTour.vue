<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import type { OnboardingStep } from '@/types/onboarding'
import AppIcon from '@/components/AppIcon.vue'

const { t } = useI18n()

interface Props {
  isActive: boolean
  currentStep: OnboardingStep
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'next'): void
  (e: 'skip'): void
  (e: 'complete'): void
}>()

// Tour step configurations
const tourSteps = computed(() => [
  {
    step: 1,
    title: t('onboarding.steps.workflow.title'),
    description: t('onboarding.steps.workflow.desc'),
    targetSelector: '.workflow-timeline',
    position: 'right' as const,
  },
  {
    step: 2,
    title: t('onboarding.steps.start.title'),
    description: t('onboarding.steps.start.desc'),
    targetSelector: '.action-buttons',
    position: 'top' as const,
  },
  {
    step: 3,
    title: t('onboarding.steps.review.title'),
    description: t('onboarding.steps.review.desc'),
    targetSelector: '.review-content',
    position: 'left' as const,
  },
])

// Current step configuration
const currentStepConfig = computed(() => tourSteps.value[props.currentStep - 1])

// Highlight box position
const highlightBox = ref({
  top: 0,
  left: 0,
  width: 0,
  height: 0,
})

// Tooltip position
const tooltipPosition = ref({
  top: 0,
  left: 0,
})
const targetElementMissing = ref(false)

// Update positions based on target element
const updatePositions = async () => {
  await nextTick()
  const targetEl = document.querySelector(currentStepConfig.value.targetSelector)
  if (targetEl) {
    targetElementMissing.value = false
    const rect = targetEl.getBoundingClientRect()
    highlightBox.value = {
      top: rect.top,
      left: rect.left,
      width: rect.width,
      height: rect.height,
    }

    // Calculate tooltip position based on step position
    const tooltipWidth = 320
    const tooltipHeight = 200
    const padding = 16

    switch (currentStepConfig.value.position) {
      case 'top':
        tooltipPosition.value = {
          top: rect.top - tooltipHeight - padding,
          left: rect.left + rect.width / 2 - tooltipWidth / 2,
        }
        break
      case 'left':
        tooltipPosition.value = {
          top: rect.top + rect.height / 2 - tooltipHeight / 2,
          left: rect.left - tooltipWidth - padding,
        }
        break
      case 'right':
        tooltipPosition.value = {
          top: rect.top + rect.height / 2 - tooltipHeight / 2,
          left: rect.right + padding,
        }
        break
    }
  } else {
    // Keep the tour usable while async dashboard content is loading, but make
    // the fallback explicit instead of implying that an invisible element is
    // highlighted.
    targetElementMissing.value = true
    highlightBox.value = { top: 0, left: 0, width: 0, height: 0 }
    tooltipPosition.value = {
      top: window.innerHeight / 2 - 100,
      left: window.innerWidth / 2 - 160,
    }
  }
}

// Watch for step changes to update positions
watch(() => props.currentStep, updatePositions)
watch(() => props.isActive, async (isActive) => {
  if (isActive) {
    await updatePositions()
  }
})

// Handle window resize
const handleResize = () => {
  if (props.isActive) {
    updatePositions()
  }
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
  window.addEventListener('keydown', handleWindowKeyDown)
  if (props.isActive) {
    updatePositions()
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  window.removeEventListener('keydown', handleWindowKeyDown)
})

// Handle button clicks
const handleNext = () => emit('next')
const handleSkip = () => emit('skip')
const handleComplete = () => emit('complete')
const handleWindowKeyDown = (e: KeyboardEvent) => {
  if (props.isActive && e.key === 'Escape') emit('skip')
}

// Is last step
const isLastStep = computed(() => props.currentStep === 3)
</script>

<template>
  <Teleport to="body">
    <Transition name="onboarding">
      <div
        v-if="isActive"
        class="fixed inset-0 z-50 pointer-events-none"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        aria-describedby="tour-desc"
      >
        <!-- Overlay mask with cutout for highlight -->
        <div class="absolute inset-0 bg-slate-900/60 backdrop-blur-sm pointer-events-none">
          <!-- Highlight box cutout -->
          <div
            class="absolute rounded-lg ring-4 ring-neon-cyan ring-offset-2 ring-offset-transparent transition-all duration-300"
            :style="{
              top: `${highlightBox.top}px`,
              left: `${highlightBox.left}px`,
              width: `${highlightBox.width}px`,
              height: `${highlightBox.height}px`,
              boxShadow: '0 0 20px rgba(0, 255, 255, 0.3)',
            }"
          />
        </div>

        <!-- Tooltip card -->
        <div
          class="absolute w-80 bg-white rounded-2xl shadow-xl border border-slate-200/50 p-5 transition-all duration-300 pointer-events-auto"
          :style="{
            top: `${tooltipPosition.top}px`,
            left: `${tooltipPosition.left}px`,
          }"
        >
          <!-- Header with step indicator -->
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2">
              <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-neon-cyan to-neon-purple flex items-center justify-center">
                <AppIcon name="Compass" size="sm" variant="white" />
              </div>
              <h3 id="tour-title" class="text-lg font-semibold text-slate-800">
                {{ currentStepConfig.title }}
              </h3>
            </div>
            <!-- Step dots -->
            <div class="flex gap-1.5" role="group" :aria-label="t('onboarding.stepIndicator')">
              <span
                v-for="step in 3"
                :key="step"
                class="w-2.5 h-2.5 rounded-full transition-all"
                :class="
                  step === currentStep
                    ? 'bg-neon-cyan scale-125'
                    : step < currentStep
                      ? 'bg-neon-cyan/50'
                      : 'bg-slate-300'
                "
                :aria-label="`${t('onboarding.stepStatus', { step })}${step === currentStep ? ` (${t('onboarding.currentStep')})` : ''}`"
              />
            </div>
          </div>

          <p v-if="targetElementMissing" class="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700" role="status">
            {{ t('onboarding.targetUnavailable') }}
          </p>

          <!-- Description -->
          <p id="tour-desc" class="text-slate-600 text-sm leading-relaxed mb-4">
            {{ currentStepConfig.description }}
          </p>

          <!-- Action buttons -->
          <div class="flex items-center justify-between">
            <button
              class="px-3 py-1.5 rounded-lg text-slate-500 hover:text-slate-700 hover:bg-slate-100 transition-colors text-sm font-medium"
              @click="handleSkip"
              :aria-label="t('onboarding.skip')"
            >
              {{ t('onboarding.skip') }}
            </button>

            <button
              v-if="!isLastStep"
              class="px-4 py-2 rounded-lg bg-gradient-to-r from-neon-cyan to-neon-purple text-white font-medium hover:shadow-lg transition-all"
              @click="handleNext"
              :aria-label="t('onboarding.next')"
            >
              {{ t('onboarding.next') }}
            </button>
            <button
              v-else
              class="px-4 py-2 rounded-lg bg-gradient-to-r from-neon-pink to-neon-peach text-white font-medium hover:shadow-lg transition-all"
              @click="handleComplete"
              :aria-label="t('onboarding.finish')"
            >
              {{ t('onboarding.finish') }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.onboarding-enter-active {
  transition: opacity 0.3s ease-out;
}

.onboarding-leave-active {
  transition: opacity 0.2s ease-in;
}

.onboarding-enter-from,
.onboarding-leave-to {
  opacity: 0;
}

.onboarding-enter-from .bg-white,
.onboarding-leave-to .bg-white {
  transform: scale(0.9);
}
</style>
