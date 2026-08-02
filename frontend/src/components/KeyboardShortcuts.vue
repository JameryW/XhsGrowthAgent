<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useShortcutsStore, SHORTCUTS } from '@/stores/shortcuts'
import AppIcon from '@/components/AppIcon.vue'

const { t } = useI18n()

interface Props {
  isOpen: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const shortcutsStore = useShortcutsStore()

// Focus management
const closeButtonRef = ref<HTMLButtonElement | null>(null)
const previousFocusElement = ref<HTMLElement | null>(null)

// Group shortcuts by category
const shortcutGroups = computed(() => {
  const groups: Record<string, typeof SHORTCUTS> = {
    [t('keyboard.global')]: [],
    [t('keyboard.dashboard')]: [],
    [t('keyboard.review')]: [],
  }

  for (const shortcut of SHORTCUTS) {
    if (!shortcut.pages || shortcut.pages.length === 0) {
      groups[t('keyboard.global')].push(shortcut)
    } else if (shortcut.pages.includes('dashboard') && !shortcut.pages.includes('chord_g')) {
      groups[t('keyboard.dashboard')].push(shortcut)
    } else if (shortcut.pages.includes('review') && !shortcut.pages.includes('chord_g')) {
      groups[t('keyboard.review')].push(shortcut)
    }
  }

  return groups
})

// Format shortcut key display
const formatKey = (shortcut: typeof SHORTCUTS[0]) => {
  const parts: string[] = []
  if (shortcut.ctrl) parts.push('Ctrl')
  if (shortcut.shift) parts.push('Shift')
  if (shortcut.alt) parts.push('Alt')
  parts.push(shortcut.key)
  return parts.join('+')
}

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

// Handle close
const handleClose = () => emit('close')

// Handle keyboard events
const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Escape') {
    handleClose()
  }
}

// Handle backdrop click
const handleBackdropClick = (e: MouseEvent) => {
  if (e.target === e.currentTarget) {
    handleClose()
  }
}

onMounted(() => {
  if (props.isOpen) {
    shortcutsStore.showShortcutsPanel()
  }
})

onUnmounted(() => {
  shortcutsStore.hideShortcutsPanel()
})
</script>

<template>
  <Teleport to="body">
    <Transition name="shortcuts">
      <div
        v-if="isOpen"
        class="fixed inset-0 z-modal flex items-center justify-center"
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-panel-title"
        @keydown="handleKeyDown"
        @click="handleBackdropClick"
      >
        <!-- Backdrop -->
        <div
          class="absolute inset-0 bg-slate-900/50 backdrop-blur-sm"
          aria-hidden="true"
        />

        <!-- Panel -->
        <div
          class="dark-explicit relative w-full max-w-lg bg-white/90 rounded-2xl shadow-2xl border border-slate-200/50 overflow-hidden dark:bg-slate-900/95 dark:border-slate-600/60 dark:shadow-slate-950/50"
          @click.stop
        >
          <!-- Header -->
          <div class="dark-explicit px-6 py-4 bg-gradient-to-r from-violet-50 to-purple-50 border-b border-slate-200 dark:from-violet-950/50 dark:to-slate-900 dark:border-slate-700">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-400 to-purple-500 flex items-center justify-center shadow-sm">
                  <AppIcon name="Keyboard" size="md" variant="white" />
                </div>
                <h2 id="shortcuts-panel-title" class="text-lg font-semibold text-slate-800">
                  快捷键面板
                </h2>
              </div>
              <button
                ref="closeButtonRef"
                class="dark-explicit w-8 h-8 rounded-lg hover:bg-slate-100 flex items-center justify-center transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400/50 dark:hover:bg-slate-800"
                :aria-label="t('keyboard.close')"
                @click="handleClose"
              >
                <AppIcon name="X" size="sm" variant="pink" />
              </button>
            </div>
          </div>

          <!-- Content -->
          <div class="p-4 max-h-[60vh] overflow-y-auto">
            <div
              v-for="(shortcuts, category) in shortcutGroups"
              :key="category"
              class="mb-4"
            >
              <!-- Category header -->
              <div class="flex items-center gap-2 mb-2 px-2">
                <span
                  class="text-xs font-semibold uppercase tracking-wider"
                  :class="
                    category === t('keyboard.global')
                      ? 'text-violet-500'
                      : category === t('keyboard.dashboard')
                        ? 'text-neon-cyan'
                        : 'text-neon-pink'
                  "
                >
                  {{ category }}
                </span>
                <span class="text-xs text-slate-400">
                  ({{ shortcuts.length }})
                </span>
              </div>

              <!-- Shortcuts list -->
              <div class="space-y-1">
                <div
                  v-for="shortcut in shortcuts"
                  :key="shortcut.action"
                  class="dark-explicit flex items-center justify-between p-2.5 rounded-lg bg-slate-50 hover:bg-slate-100 transition-colors group dark:bg-slate-800/70 dark:hover:bg-slate-800"
                >
                  <div class="flex-1 min-w-0">
                    <span class="text-sm text-slate-700 block truncate">
                      {{ shortcut.description }}
                    </span>
                    <span class="text-xs text-slate-400 group-hover:text-slate-500">
                      {{ shortcut.action }}
                    </span>
                  </div>
                  <kbd
                    class="dark-explicit px-2.5 py-1.5 rounded-lg bg-gradient-to-r from-slate-200 to-slate-300 text-slate-700 text-xs font-mono border border-slate-400/30 shadow-sm min-w-[60px] text-center dark:from-slate-700 dark:to-slate-600 dark:text-slate-200 dark:border-slate-500/40"
                  >
                    {{ formatKey(shortcut) }}
                  </kbd>
                </div>
              </div>
            </div>
          </div>

          <!-- Footer hint -->
          <div class="dark-explicit px-6 py-3 bg-slate-50 border-t border-slate-200 text-center dark:bg-slate-900/80 dark:border-slate-700">
            <p class="text-xs text-slate-500">
              {{ t('keyboard.escHint') }}
            </p>
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
  transform: scale(0.95) translateY(20px);
}

.shortcuts-leave-to > div:last-child {
  transform: scale(0.95) translateY(-10px);
}
</style>