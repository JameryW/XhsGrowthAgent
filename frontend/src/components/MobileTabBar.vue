<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const tabs = computed(() => [
  { path: '/dashboard', icon: 'Home', label: t('nav.dashboard') },
  { path: '/review', icon: 'CheckCircle', label: t('nav.review') },
  { path: '/analytics', icon: 'BarChart3', label: t('nav.analytics') },
  { path: '/history', icon: 'History', label: t('nav.history') },
])

const currentPath = computed(() => route.path)

const navigate = (path: string) => {
  router.push(path)
}
</script>

<template>
  <nav
    class="fixed bottom-0 left-0 right-0 z-50 bg-white/90 backdrop-blur-xl border-t border-slate-200/60 safe-area-bottom"
    role="navigation"
    :aria-label="t('nav.home')"
  >
    <div class="flex items-center justify-around h-16">
      <button
        v-for="tab in tabs"
        :key="tab.path"
        @click="navigate(tab.path)"
        :class="[
          'flex flex-col items-center justify-center gap-0.5 flex-1 h-full transition-colors duration-200 relative',
          currentPath === tab.path ? 'text-rose-500' : 'text-slate-400'
        ]"
        :aria-current="currentPath === tab.path ? 'page' : undefined"
        :aria-label="tab.label"
      >
        <!-- Active indicator -->
        <div
          v-if="currentPath === tab.path"
          class="absolute top-0 left-1/2 -translate-x-1/2 w-8 h-0.5 rounded-full bg-gradient-to-r from-rose-400 to-amber-400"
          aria-hidden="true"
        />
        <AppIcon
          :name="tab.icon"
          size="md"
          :variant="currentPath === tab.path ? 'pink' : 'cyan'"
        />
        <span class="text-[10px] font-medium leading-tight">{{ tab.label }}</span>
      </button>
    </div>
  </nav>
</template>

<style scoped>
.safe-area-bottom {
  padding-bottom: env(safe-area-inset-bottom, 0px);
}
</style>
