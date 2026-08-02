<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'

const { t } = useI18n()

interface Props {
  faqUrl?: string
  shortcutsUrl?: string
  feedbackEmail?: string
}

withDefaults(defineProps<Props>(), {
  faqUrl: '/help',
  shortcutsUrl: '/help?section=shortcuts',
  feedbackEmail: '',
})

const emit = defineEmits<{
  (e: 'open-faq'): void
  (e: 'open-shortcuts'): void
  (e: 'send-feedback'): void
}>()

// Dropdown state
const isOpen = ref(false)

// Toggle dropdown
const toggleDropdown = () => {
  isOpen.value = !isOpen.value
}

// Close dropdown
const closeDropdown = () => {
  isOpen.value = false
}

// Handle menu item clicks
const handleOpenFaq = () => {
  emit('open-faq')
  closeDropdown()
}

const handleOpenShortcuts = () => {
  emit('open-shortcuts')
  closeDropdown()
}

const handleSendFeedback = () => {
  emit('send-feedback')
  closeDropdown()
}

// Handle keyboard navigation
const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Escape') {
    closeDropdown()
  }
}

// Close dropdown on outside click
const handleClickOutside = (e: MouseEvent) => {
  const target = e.target as HTMLElement
  if (!target.closest('.help-center-container')) {
    closeDropdown()
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  document.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('keydown', handleKeyDown)
})
</script>

<template>
  <div class="help-center-container relative">
    <!-- Help button -->
    <button
      class="dark-explicit w-10 h-10 rounded-xl bg-slate-100 hover:bg-slate-200 flex items-center justify-center transition-colors focus:outline-none focus-visible:ring-2 dark:bg-slate-800 dark:hover:bg-slate-700 focus-visible:ring-slate-400/50"
      :aria-expanded="isOpen"
      aria-haspopup="true"
      :aria-label="t('help.center')"
      @click="toggleDropdown"
    >
      <AppIcon name="HelpCircle" size="md" variant="pink" />
    </button>

    <!-- Dropdown menu -->
    <Transition name="dropdown">
      <div
        v-if="isOpen"
        class="dark-explicit absolute right-0 mt-2 w-48 bg-white rounded-xl shadow-lg border border-slate-200/50 py-2 z-dropdown dark:bg-slate-900/85 dark:border-slate-700/50"
        role="menu"
        :aria-label="t('help.menu')"
      >
        <!-- FAQ link -->
        <button
          class="dark-explicit w-full px-4 py-2.5 text-left text-sm text-slate-700 hover:bg-slate-100 flex items-center gap-2 transition-colors dark:text-slate-200 dark:hover:bg-slate-800"
          role="menuitem"
          @click="handleOpenFaq"
        >
          <AppIcon name="BookOpen" size="sm" variant="cyan" />
          <span>{{ t('help.faq') }}</span>
        </button>

        <!-- Shortcuts link -->
        <button
          class="dark-explicit w-full px-4 py-2.5 text-left text-sm text-slate-700 hover:bg-slate-100 flex items-center gap-2 transition-colors dark:text-slate-200 dark:hover:bg-slate-800"
          role="menuitem"
          @click="handleOpenShortcuts"
        >
          <AppIcon name="Keyboard" size="sm" variant="purple" />
          <span>{{ t('help.shortcuts') }}</span>
        </button>

        <!-- Divider -->
        <div class="my-1 border-t border-slate-200" />

        <!-- Feedback link -->
        <button
          class="dark-explicit w-full px-4 py-2.5 text-left text-sm text-slate-700 hover:bg-slate-100 flex items-center gap-2 transition-colors dark:text-slate-200 dark:hover:bg-slate-800"
          role="menuitem"
          @click="handleSendFeedback"
        >
          <AppIcon name="MessageCircle" size="sm" variant="peach" />
          <span>{{ t('help.feedback') }}</span>
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.dropdown-enter-active {
  transition: all 0.2s ease-out;
}

.dropdown-leave-active {
  transition: all 0.15s ease-in;
}

.dropdown-enter-from {
  opacity: 0;
  transform: translateY(-8px);
}

.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
