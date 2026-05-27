<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

interface Props {
  isOpen: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

// Focus management
const closeButtonRef = ref<HTMLButtonElement | null>(null)
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

const shortcuts = [
  { key: '?', description: '显示快捷键帮助' },
  { key: 'Esc', description: '关闭弹窗/取消操作' },
  { key: 'Enter', description: '确认选择/提交' },
  { key: 'Space', description: '选择项目/切换状态' },
  { key: 'Tab', description: '切换焦点到下一个元素' },
  { key: 'Shift+Tab', description: '切换焦点到上一个元素' },
  { key: 'R', description: '刷新状态 (Dashboard)' },
  { key: 'P', description: '暂停工作流 (Dashboard)' },
]

const handleClose = () => emit('close')
const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Escape') handleClose()
}
</script>

<template>
  <Teleport to="body">
    <Transition name="shortcuts">
      <div
        v-if="isOpen"
        class="fixed inset-0 z-50 flex items-center justify-center"
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        aria-describedby="shortcuts-desc"
        @keydown="handleKeyDown"
      >
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" @click="handleClose" aria-hidden="true" />

        <!-- Modal -->
        <div class="relative w-full max-w-md p-6 rounded-2xl bg-white/98 shadow-xl border border-slate-200/50">
          <!-- Header -->
          <div class="flex items-center gap-3 mb-4">
            <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-400 to-violet-500 flex items-center justify-center shadow-sm" aria-hidden="true">
              <AppIcon name="Keyboard" size="md" variant="white" />
            </div>
            <h2 id="shortcuts-title" class="text-lg font-semibold text-slate-800">
              快捷键帮助
            </h2>
          </div>

          <!-- Description for screen readers -->
          <p id="shortcuts-desc" class="sr-only">可用的键盘快捷键列表，帮助您快速操作应用</p>

          <!-- Shortcuts list -->
          <div class="space-y-2" role="list" aria-label="快捷键列表">
            <div
              v-for="shortcut in shortcuts"
              :key="shortcut.key"
              class="flex items-center justify-between p-2 rounded-lg bg-slate-50 hover:bg-slate-100 transition-colors"
              role="listitem"
            >
              <span class="text-sm text-slate-600">{{ shortcut.description }}</span>
              <kbd class="px-2 py-1 rounded bg-slate-200 text-slate-700 text-xs font-mono border border-slate-300 shadow-sm">
                {{ shortcut.key }}
              </kbd>
            </div>
          </div>

          <!-- Footer -->
          <div class="mt-4 pt-4 border-t border-slate-200 flex justify-center">
            <button
              ref="closeButtonRef"
              class="px-4 py-2 rounded-lg bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors text-sm font-medium"
              @click="handleClose"
            >
              关闭
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