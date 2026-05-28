<script setup lang="ts">
import NeonButton from '@/components/NeonButton.vue'

interface Props {
  isVisible: boolean
  message?: string
  canCancel?: boolean
}

withDefaults(defineProps<Props>(), {
  message: '正在处理...',
  canCancel: true
})

const emit = defineEmits<{
  cancel: []
}>()

const handleCancel = () => {
  emit('cancel')
}
</script>

<template>
  <div
    v-if="isVisible"
    class="loading-overlay fixed inset-0 z-50 flex items-center justify-center"
    role="dialog"
    aria-modal="true"
    aria-labelledby="loading-message"
  >
    <!-- Semi-transparent backdrop -->
    <div class="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" />

    <!-- Content container -->
    <div class="relative bg-white rounded-2xl p-8 shadow-xl flex flex-col items-center gap-6 max-w-md mx-4">
      <!-- Rotating spinner -->
      <div
        class="w-16 h-16 rounded-full border-4 border-slate-200 border-t-rose-500 rotate-animation"
        aria-hidden="true"
      />

      <!-- Loading message -->
      <p
        id="loading-message"
        class="text-slate-700 font-semibold text-center"
      >
        {{ message }}
      </p>

      <!-- Cancel button -->
      <NeonButton
        v-if="canCancel"
        variant="ghost"
        size="sm"
        @click="handleCancel"
        aria-label="取消操作"
      >
        取消操作
      </NeonButton>
    </div>
  </div>
</template>