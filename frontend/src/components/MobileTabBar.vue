<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import { useAccountsStore, useAuthStore, useRealtimeStore } from '@/stores'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const accountsStore = useAccountsStore()
const realtimeStore = useRealtimeStore()
const showMore = ref(false)

const tabs = computed(() => [
  { path: '/start', icon: 'Rocket', label: t('nav.startShort') },
  { path: '/dashboard', icon: 'Home', label: t('nav.dashboardShort') },
  { path: '/review', icon: 'CheckCircle', label: t('nav.reviewShort') },
])

const currentPath = computed(() => route.path)
const moreActive = computed(() => ['/settings', '/analytics', '/evaluation', '/history'].some(path => currentPath.value === path || currentPath.value.startsWith(`${path}/`)))
const isActiveTab = (path: string) => currentPath.value === path || currentPath.value.startsWith(`${path}/`)
const activeAccountName = computed(() => accountsStore.activeAccount?.name || t('nav.accountSelect'))
const accountInitial = computed(() => accountsStore.activeAccount?.name?.trim().slice(0, 1).toUpperCase() || t('nav.accountInitialFallback'))
const connectionLabel = computed(() => {
  if (realtimeStore.connectionStatus === 'connected') return t('nav.ws.connected')
  if (realtimeStore.connectionStatus === 'reconnecting') return t('nav.ws.reconnecting')
  if (realtimeStore.connectionStatus === 'connecting') return t('nav.ws.connecting')
  return t('nav.ws.disconnected')
})

onMounted(() => {
  if (!accountsStore.activeAccount) void accountsStore.fetchAccounts()
  document.addEventListener('keydown', handleMenuKeydown)
})

function handleMenuKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && showMore.value) {
    showMore.value = false
  }
}

watch(() => route.path, () => {
  showMore.value = false
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleMenuKeydown)
})

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
    class="app-mobile-tabbar fixed bottom-0 left-0 right-0 z-50 liquid-glass-nav border-t border-white/15 safe-area-bottom"
    role="navigation"
    :aria-label="t('nav.home')"
  >
    <div class="app-mobile-tabbar-inner relative flex h-[4.5rem] items-stretch justify-around px-1">
      <button
        v-for="tab in tabs"
        :key="tab.path"
        @click="navigate(tab.path)"
        :class="[
          'relative flex min-h-11 flex-1 flex-col items-center justify-center gap-1 rounded-xl px-1 transition-all duration-200',
          isActiveTab(tab.path) ? 'text-rose-500' : 'text-slate-400'
        ]"
        :aria-current="isActiveTab(tab.path) ? 'page' : undefined"
        :aria-label="tab.label"
      >
        <span :class="['flex h-8 w-10 items-center justify-center rounded-xl transition-all duration-200', isActiveTab(tab.path) ? 'bg-rose-50 shadow-sm ring-1 ring-rose-100' : '']" aria-hidden="true">
          <AppIcon :name="tab.icon" size="md" :variant="isActiveTab(tab.path) ? 'pink' : 'cyan'" />
        </span>
        <span class="max-w-full truncate px-0.5 text-[10px] font-medium leading-tight">{{ tab.label }}</span>
        <span v-if="isActiveTab(tab.path)" class="absolute bottom-1 h-1 w-1 rounded-full bg-rose-500" aria-hidden="true" />
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
        <span :class="['flex h-8 w-10 items-center justify-center rounded-xl transition-all duration-200', showMore || moreActive ? 'bg-rose-50 shadow-sm ring-1 ring-rose-100' : '']" aria-hidden="true">
          <AppIcon name="MoreHorizontal" size="md" :variant="showMore || moreActive ? 'pink' : 'cyan'" />
        </span>
        <span class="max-w-full truncate px-0.5 text-[10px] font-medium leading-tight">{{ t('nav.more') }}</span>
        <span v-if="moreActive" class="absolute bottom-1 h-1 w-1 rounded-full bg-rose-500" aria-hidden="true" />
      </button>

      <div
        v-if="showMore"
        class="app-mobile-more-menu absolute bottom-[calc(4.5rem+env(safe-area-inset-bottom,0px))] right-2 w-64 overflow-hidden rounded-2xl border border-white/70 bg-white/95 shadow-xl shadow-slate-900/10 backdrop-blur-md"
        role="menu"
      >
        <div class="border-b border-slate-100 bg-gradient-to-r from-cyan-50/80 to-white px-4 py-3 dark:border-slate-700/60 dark:from-cyan-950/40 dark:to-slate-900/90" role="status" :aria-label="t('nav.activeAccount')">
          <div class="flex items-center gap-3">
            <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-400 to-emerald-400 text-xs font-bold text-white" aria-hidden="true">{{ accountInitial }}</span>
            <div class="min-w-0 flex-1">
              <div class="text-[10px] font-bold uppercase tracking-wider text-slate-400">{{ t('nav.activeAccount') }}</div>
              <div class="truncate text-xs font-bold text-slate-700">{{ activeAccountName }}</div>
              <div class="flex items-center gap-1.5 text-[10px] text-slate-400">
                <span class="h-1.5 w-1.5 rounded-full" :class="realtimeStore.connectionStatus === 'connected' ? 'bg-emerald-400' : realtimeStore.connectionStatus === 'disconnected' ? 'bg-rose-400' : 'bg-amber-400'" aria-hidden="true" />
                {{ connectionLabel }}
              </div>
            </div>
          </div>
        </div>
        <button
          class="flex min-h-11 w-full items-center gap-2 px-4 py-3 text-left text-sm text-slate-700 transition-colors hover:bg-slate-50"
          role="menuitem"
          @click="navigate('/analytics')"
        >
          <AppIcon name="BarChart3" size="sm" variant="cyan" aria-hidden="true" />
          <span>{{ t('nav.analytics') }}</span>
        </button>
        <button
          class="flex min-h-11 w-full items-center gap-2 px-4 py-3 text-left text-sm text-slate-700 transition-colors hover:bg-slate-50"
          role="menuitem"
          @click="navigate('/evaluation')"
        >
          <AppIcon name="ClipboardCheck" size="sm" variant="purple" aria-hidden="true" />
          <span>{{ t('nav.evaluation') }}</span>
        </button>
        <button
          class="flex min-h-11 w-full items-center gap-2 px-4 py-3 text-left text-sm text-slate-700 transition-colors hover:bg-slate-50"
          role="menuitem"
          @click="navigate('/history')"
        >
          <AppIcon name="History" size="sm" variant="cyan" aria-hidden="true" />
          <span>{{ t('nav.history') }}</span>
        </button>
        <button
          class="flex min-h-11 w-full items-center gap-2 px-4 py-3 text-left text-sm text-slate-700 transition-colors hover:bg-slate-50"
          role="menuitem"
          @click="openSettings"
        >
          <AppIcon name="Settings" size="sm" variant="cyan" aria-hidden="true" />
          <span>{{ t('nav.settings') }}</span>
        </button>
        <button
          class="flex min-h-11 w-full items-center gap-2 px-4 py-3 text-left text-sm text-rose-600 transition-colors hover:bg-rose-50 disabled:opacity-60"
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
.app-mobile-tabbar {
  box-shadow:
    0 -1px 2px rgba(15, 23, 42, 0.04),
    0 -10px 24px rgba(15, 23, 42, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

.app-mobile-tabbar::before {
  content: '';
  position: absolute;
  top: -1px;
  right: 12%;
  left: 12%;
  height: 2px;
  border-radius: 999px;
  background: linear-gradient(90deg, transparent, rgba(244, 63, 94, 0.44), rgba(20, 184, 166, 0.34), transparent);
  pointer-events: none;
}

.app-mobile-tabbar-inner {
  max-width: 32rem;
  margin-inline: auto;
}

.app-mobile-more-menu {
  box-shadow:
    0 8px 18px rgba(15, 23, 42, 0.08),
    0 24px 48px rgba(15, 23, 42, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.82);
  animation: mobile-menu-in 0.2s ease-out;
}

@keyframes mobile-menu-in {
  from { opacity: 0; transform: translateY(8px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

.safe-area-bottom {
  padding-bottom: env(safe-area-inset-bottom, 0px);
}

@media (prefers-reduced-motion: reduce) {
  .app-mobile-more-menu {
    animation: none;
  }
}
</style>
