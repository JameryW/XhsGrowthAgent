<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import { useAuthStore } from '@/stores'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const showMore = ref(false)

const tabs = computed(() => [
  { path: '/start', icon: 'Rocket', label: t('nav.startShort') },
  { path: '/dashboard', icon: 'Home', label: t('nav.dashboardShort') },
  { path: '/review', icon: 'CheckCircle', label: t('nav.reviewShort') },
  { path: '/analytics', icon: 'BarChart3', label: t('nav.analyticsShort') },
  { path: '/history', icon: 'History', label: t('nav.historyShort') },
])

const currentPath = computed(() => route.path)
const moreActive = computed(() => currentPath.value === '/settings')
const isActiveTab = (path: string) => currentPath.value === path

const navigate = (path: string) => {
  showMore.value = false
  router.push(path)
}

const openSettings = () => {
  navigate('/settings')
}

const handleLogout = async () => {
  showMore.value = false
  await authStore.logout()
  router.push('/login')
}
</script>

<template>
  <nav
    class="fixed bottom-0 left-0 right-0 z-50 liquid-glass-nav border-t border-white/15 safe-area-bottom"
    role="navigation"
    :aria-label="t('nav.home')"
  >
    <div class="relative flex items-center justify-around h-16">
      <button
        v-for="tab in tabs"
        :key="tab.path"
        @click="navigate(tab.path)"
        :class="[
          'flex flex-col items-center justify-center gap-0.5 flex-1 h-full transition-colors duration-200 relative',
          isActiveTab(tab.path) ? 'text-rose-500' : 'text-slate-400'
        ]"
        :aria-current="isActiveTab(tab.path) ? 'page' : undefined"
        :aria-label="tab.label"
      >
        <!-- Active indicator -->
        <div
          v-if="isActiveTab(tab.path)"
          class="absolute top-0 left-1/2 -translate-x-1/2 w-8 h-0.5 rounded-full bg-gradient-to-r from-rose-400 to-amber-400"
          aria-hidden="true"
        />
        <AppIcon
          :name="tab.icon"
          size="md"
          :variant="isActiveTab(tab.path) ? 'pink' : 'cyan'"
        />
        <span class="max-w-full truncate px-0.5 text-[10px] font-medium leading-tight">{{ tab.label }}</span>
      </button>

      <button
        @click="showMore = !showMore"
        :class="[
          'flex flex-col items-center justify-center gap-0.5 flex-1 h-full transition-colors duration-200 relative',
          showMore || moreActive ? 'text-rose-500' : 'text-slate-400'
        ]"
        :aria-expanded="showMore"
        :aria-label="t('nav.more')"
      >
        <div
          v-if="showMore || moreActive"
          class="absolute top-0 left-1/2 -translate-x-1/2 w-8 h-0.5 rounded-full bg-gradient-to-r from-rose-400 to-amber-400"
          aria-hidden="true"
        />
        <AppIcon
          name="MoreHorizontal"
          size="md"
          :variant="showMore || moreActive ? 'pink' : 'cyan'"
        />
        <span class="max-w-full truncate px-0.5 text-[10px] font-medium leading-tight">{{ t('nav.more') }}</span>
      </button>

      <div
        v-if="showMore"
        class="absolute right-2 bottom-[calc(4rem+env(safe-area-inset-bottom,0px))] w-44 overflow-hidden rounded-xl border border-white/20 bg-white/95 shadow-xl backdrop-blur-md"
        role="menu"
      >
        <button
          class="flex w-full items-center gap-2 px-3 py-3 text-left text-sm text-slate-700 transition-colors hover:bg-slate-50"
          role="menuitem"
          @click="openSettings"
        >
          <AppIcon name="Settings" size="sm" variant="cyan" aria-hidden="true" />
          <span>{{ t('nav.settings') }}</span>
        </button>
        <button
          class="flex w-full items-center gap-2 px-3 py-3 text-left text-sm text-rose-600 transition-colors hover:bg-rose-50 disabled:opacity-60"
          role="menuitem"
          :disabled="authStore.isLoading"
          @click="handleLogout"
        >
          <AppIcon name="LogOut" size="sm" variant="pink" aria-hidden="true" />
          <span>{{ t('nav.logout') }}</span>
        </button>
      </div>
    </div>
  </nav>
</template>

<style scoped>
.safe-area-bottom {
  padding-bottom: env(safe-area-inset-bottom, 0px);
}
</style>
