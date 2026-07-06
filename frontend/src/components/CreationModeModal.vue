<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'

const { t } = useI18n()

defineProps<{
  isOpen: boolean
  isLoading: boolean
}>()

const emit = defineEmits<{
  simple: []
  free: []
  cancel: []
}>()
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="isOpen" class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" @click="emit('cancel')" />

        <div class="relative liquid-glass-elevated rounded-2xl max-w-lg w-full overflow-hidden">
          <div class="p-5 border-b border-slate-100">
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-rose-400 to-amber-400 flex items-center justify-center">
                <AppIcon name="Sparkles" size="md" variant="white" />
              </div>
              <div>
                <h3 class="text-lg font-semibold text-slate-800">{{ t('home.creationMode.title') }}</h3>
                <p class="text-xs text-slate-400">{{ t('home.creationMode.subtitle') }}</p>
              </div>
            </div>
          </div>

          <div class="p-5 grid gap-3">
            <button
              type="button"
              class="w-full rounded-xl border border-rose-100 bg-white/80 px-4 py-3 text-left transition hover:border-rose-200 hover:bg-rose-50/70 focus:outline-none focus:ring-2 focus:ring-rose-300"
              :disabled="isLoading"
              @click="emit('simple')"
            >
              <div class="flex items-start gap-3">
                <div class="mt-0.5 w-9 h-9 rounded-lg bg-rose-100 flex items-center justify-center shrink-0">
                  <AppIcon name="Workflow" size="sm" variant="pink" />
                </div>
                <div class="min-w-0">
                  <div class="text-sm font-semibold text-slate-800">{{ t('home.creationMode.simpleTitle') }}</div>
                  <p class="mt-1 text-xs leading-5 text-slate-500">{{ t('home.creationMode.simpleDesc') }}</p>
                </div>
              </div>
            </button>

            <button
              type="button"
              class="w-full rounded-xl border border-teal-100 bg-white/80 px-4 py-3 text-left transition hover:border-teal-200 hover:bg-teal-50/70 focus:outline-none focus:ring-2 focus:ring-teal-300"
              :disabled="isLoading"
              @click="emit('free')"
            >
              <div class="flex items-start gap-3">
                <div class="mt-0.5 w-9 h-9 rounded-lg bg-teal-100 flex items-center justify-center shrink-0">
                  <AppIcon name="Terminal" size="sm" variant="cyan" />
                </div>
                <div class="min-w-0">
                  <div class="text-sm font-semibold text-slate-800">{{ t('home.creationMode.freeTitle') }}</div>
                  <p class="mt-1 text-xs leading-5 text-slate-500">{{ t('home.creationMode.freeDesc') }}</p>
                </div>
              </div>
            </button>
          </div>

          <div class="p-5 border-t border-slate-100">
            <NeonButton variant="ghost" class="w-full" @click="emit('cancel')" :disabled="isLoading">
              {{ t('common.cancel') }}
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
