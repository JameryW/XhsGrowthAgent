<script setup lang="ts">
import { ref, onErrorCaptured, type ComponentPublicInstance } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'

const { t } = useI18n()

// Props
const props = defineProps<{
  fallbackMessage?: string
}>()

// Emits
const emit = defineEmits<{
  error: [error: Error, instance: ComponentPublicInstance, info: string]
  refresh: []
}>()

// State
const hasError = ref(false)
const errorMessage = ref('')
const errorInfo = ref('')

// Default fallback message - use only when no actual error message
const defaultMessage = t('errorBoundary.componentError')

// Error captured lifecycle hook
onErrorCaptured((error: Error, instance: ComponentPublicInstance | null, info: string) => {
  // Set error state
  hasError.value = true
  // Use custom fallback if provided, otherwise use actual error message
  errorMessage.value = props.fallbackMessage || error.message || defaultMessage
  errorInfo.value = info

  // Emit error event for parent handling
  if (instance) {
    emit('error', error, instance, info)
  }

  // Return false to prevent the error from propagating further
  return false
})

// Refresh handler - resets error state and emits refresh event
const handleRefresh = () => {
  hasError.value = false
  errorMessage.value = ''
  errorInfo.value = ''
  emit('refresh')
}
</script>

<template>
  <div class="error-boundary-wrapper">
    <!-- Fallback UI when error occurs -->
    <div
      v-if="hasError"
      class="bg-rose-50/80 border border-rose-200/50 rounded-xl p-6"
      role="alert"
      aria-live="assertive"
    >
      <div class="flex items-start gap-4">
        <!-- Error icon -->
        <div class="w-12 h-12 rounded-xl bg-rose-100 flex items-center justify-center">
          <AppIcon name="AlertTriangle" size="lg" variant="pink" />
        </div>

        <!-- Error content -->
        <div class="flex-1">
          <h3 class="text-lg font-semibold text-rose-700 mb-1">
            {{ t('errorBoundary.componentError') }}
          </h3>
          <p class="text-sm text-rose-600 mb-2">
            {{ errorMessage }}
          </p>
          <p v-if="errorInfo" class="text-xs text-rose-500 opacity-70">
            {{ t('errorBoundary.errorSource', { info: errorInfo }) }}
          </p>
        </div>

        <!-- Actions -->
        <div class="flex gap-2">
          <NeonButton
            variant="pink"
            size="sm"
            @click="handleRefresh"
          >
            <span class="inline-flex items-center gap-2">
              <AppIcon name="RefreshCw" size="sm" variant="white" />
              <span>{{ t('errorBoundary.refresh') }}</span>
            </span>
          </NeonButton>
        </div>
      </div>
    </div>

    <!-- Normal child content when no error -->
    <slot v-else />
  </div>
</template>