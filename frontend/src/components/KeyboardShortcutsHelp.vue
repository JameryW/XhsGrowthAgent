<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'

const { t } = useI18n()

interface Props {
  isOpen: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

// Focus management
const closeButtonRef = ref<HTMLButtonElement | null>(null)
const dialogRef = ref<HTMLElement | null>(null)
const previousFocusElement = ref<HTMLElement | null>(null)

// Save and restore focus when modal opens/closes
watch(() => props.isOpen, async (isOpen) => {
  if (isOpen) {
    previousFocusElement.value = document.activeElement as HTMLElement
    await nextTick()
    closeButtonRef.value?.focus()
  } else {
    previousFocusElement.value?.focus()
  }
})

import { computed } from 'vue'

const shortcuts = computed(() => [
  { key: '?', description: t('help.shortcutDescriptions.show') },
  { key: 'Esc', description: t('help.shortcutDescriptions.close') },
  { key: 'Enter', description: t('help.shortcutDescriptions.confirm') },
  { key: 'Space', description: t('help.shortcutDescriptions.confirm') },
  { key: 'Tab', description: t('help.shortcutDescriptions.next') },
  { key: 'Shift+Tab', description: t('help.shortcutDescriptions.previous') },
  { key: 'R', description: t('dashboard.actionButtons.refresh') },
  { key: 'P', description: t('dashboard.actionButtons.pause') },
])

const handleClose = () => emit('close')
const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Escape') handleClose()
  if (e.key !== 'Tab') return
  const focusable = Array.from(
    dialogRef.value?.querySelectorAll<HTMLElement>('button, [href], input') ?? []
  ).filter((el) => !el.hasAttribute('disabled'))
  if (focusable.length < 2) return
  const current = focusable.indexOf(document.activeElement as HTMLElement)
  const next = e.shiftKey
    ? (current <= 0 ? focusable.length - 1 : current - 1)
    : (current === focusable.length - 1 ? 0 : current + 1)
  e.preventDefault()
  focusable[next]?.focus()
}
</script>

<template>
  <Teleport to="body">
    <Transition name="shortcuts">
      <div
        v-if="isOpen"
        ref="dialogRef"
        class="fixed inset-0 z-modal flex items-center justify-center"
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        aria-describedby="shortcuts-desc"
        @keydown="handleKeyDown"
      >
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" @click="handleClose" aria-hidden="true" />

        <!-- Modal -->
        <div class="dark-explicit relative w-full max-w-md p-6 rounded-2xl bg-white/90 shadow-xl border border-slate-200/50 dark:bg-slate-900/95 dark:border-slate-600/60 dark:shadow-slate-950/50">
          <!-- Header -->
          <div class="flex items-center gap-3 mb-4">
            <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-400 to-violet-500 flex items-center justify-center shadow-sm" aria-hidden="true">
              <AppIcon name="Keyboard" size="md" variant="white" />
            </div>
            <h2 id="shortcuts-title" class="text-lg font-semibold text-slate-800">
              {{ t('help.shortcuts') }}
            </h2>
          </div>

          <!-- Description for screen readers -->
          <p id="shortcuts-desc" class="sr-only">{{ t('help.shortcuts') }}</p>

          <!-- Shortcuts list -->
          <div class="space-y-2" role="list" :aria-label="t('help.shortcuts')">
            <div
              v-for="shortcut in shortcuts"
              :key="shortcut.key"
              class="dark-explicit flex items-center justify-between p-2 rounded-lg bg-slate-50 hover:bg-slate-100 transition-colors dark:bg-slate-800/70 dark:hover:bg-slate-800"
              role="listitem"
            >
              <span class="text-sm text-slate-600">{{ shortcut.description }}</span>
              <kbd class="dark-explicit px-2 py-1 rounded bg-slate-200 text-slate-700 text-xs font-mono border border-slate-300 shadow-sm dark:bg-slate-700 dark:text-slate-200 dark:border-slate-500">
                {{ shortcut.key }}
              </kbd>
            </div>
          </div>

          <!-- Footer -->
          <div class="dark-explicit mt-4 pt-4 border-t border-slate-200 flex justify-center dark:border-slate-700">
            <button
              ref="closeButtonRef"
              class="dark-explicit px-4 py-2 rounded-lg bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors text-sm font-medium dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
              @click="handleClose"
            >
              {{ t('common.close') }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.shortcuts-enter-active {
  transition: all 0.3s ease-out;
}

.shortcuts-leave-active {
  transition: all 0.2s ease-in;
}

.shortcuts-enter-from {
  opacity: 0;
}

.shortcuts-leave-to {
  opacity: 0;
}

.shortcuts-enter-from > div:last-child {
  transform: scale(0.95) translateY(10px);
}

.shortcuts-leave-to > div:last-child {
  transform: scale(0.95) translateY(-10px);
}
</style>
