<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useWorkflowStore, useAuthStore, useRealtimeStore, useShortcutsStore, useAccountsStore } from '@/stores'
import { useBreakpoints } from '@/composables/useBreakpoints'
import AppIcon from '@/components/AppIcon.vue'
import HelpCenter from '@/components/HelpCenter.vue'
import LanguageSwitcher from '@/components/LanguageSwitcher.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { useCrossAccountHintsStore } from '@/stores/crossAccountHints'

const { t } = useI18n()

type NavColor = 'pink' | 'cyan' | 'purple' | 'peach'

interface NavItem {
  path: string
  icon: string
  label: string
  hint: string
  color: NavColor
  needsAttention?: boolean
  /** Optional numeric badge (e.g. multi-account pending reviews). */
  badgeCount?: number
}

interface NavSection {
  key: string
  label: string
  items: NavItem[]
}

const route = useRoute()
const router = useRouter()
const workflowStore = useWorkflowStore()
const authStore = useAuthStore()
const realtimeStore = useRealtimeStore()
const shortcutsStore = useShortcutsStore()
const accountsStore = useAccountsStore()
const crossAccountHints = useCrossAccountHintsStore()
const { isTablet } = useBreakpoints()

const currentPath = computed(() => route.path)

const multiAccountReviewCount = computed(() => crossAccountHints.reviewAwaitingCount)
const reviewNeedsAttention = computed(
  () => workflowStore.isAwaitingReview || multiAccountReviewCount.value > 0,
)

const navSections = computed<NavSection[]>(() => [
  {
    key: 'workspace',
    label: t('nav.sections.workspace'),
    items: [
      {
        path: '/dashboard',
        icon: 'Home',
        label: t('nav.dashboard'),
        hint: t('nav.hints.dashboard'),
        color: 'pink',
      },
      {
        path: '/review',
        icon: 'CheckCircle',
        label: t('nav.review'),
        hint: multiAccountReviewCount.value > 0 && !workflowStore.isAwaitingReview
          ? t('nav.hints.reviewOtherAccounts', { count: multiAccountReviewCount.value })
          : t('nav.hints.review'),
        color: 'cyan',
        needsAttention: reviewNeedsAttention.value,
        badgeCount: multiAccountReviewCount.value > 0
          ? multiAccountReviewCount.value
          : undefined,
      },
    ],
  },
  {
    key: 'insights',
    label: t('nav.sections.insights'),
    items: [
      {
        path: '/analytics',
        icon: 'BarChart3',
        label: t('nav.analytics'),
        hint: t('nav.hints.analytics'),
        color: 'purple',
      },
      {
        path: '/evaluation',
        icon: 'ClipboardCheck',
        label: t('nav.evaluation'),
        hint: t('nav.hints.evaluation'),
        color: 'pink',
      },
      {
        path: '/history',
        icon: 'History',
        label: t('nav.history'),
        hint: t('nav.hints.history'),
        color: 'peach',
      },
    ],
  },
])

const navigateTo = (path: string) => router.push(path)

const isItemActive = (path: string) =>
  currentPath.value === path || currentPath.value.startsWith(`${path}/`)

const activeNavItem = computed(() =>
  navSections.value.flatMap(section => section.items).find(item => isItemActive(item.path))
)

const currentPhase = computed(() => workflowStore.currentPhase)

const phaseLabel = computed(() => {
  if (workflowStore.isAwaitingDraft) return t('dashboard.phase.awaitingDraft')
  if (workflowStore.isAwaitingChoice) return t('dashboard.phase.awaitingChoice')
  if (workflowStore.isAwaitingReview) return t('dashboard.phase.awaitingReview')
  if (workflowStore.isAwaitingBrief) return t('dashboard.phase.awaitingBrief')
  if (workflowStore.isAwaitingRippleDecision) return t('showcase.status.awaitingRipple')
  if (workflowStore.isAwaitingBloggerSelection) return t('dashboard.phase.awaitingBlogger')

  const phase = currentPhase.value
  const key = `dashboard.phase.${phase}`
  // Only use translation if the key exists, otherwise show raw phase
  const translated = t(key)
  return translated !== key ? translated : phase
})

const workspaceStatus = computed(() => {
  if (workflowStore.isAwaitingReview) {
    return { label: t('nav.status.reviewNeeded'), tone: 'rose' as const, icon: 'CheckCircle' }
  }
  if (
    workflowStore.isAwaitingBrief ||
    workflowStore.isAwaitingDraft ||
    workflowStore.isAwaitingChoice ||
    workflowStore.isAwaitingRippleDecision ||
    workflowStore.isAwaitingBloggerSelection
  ) {
    return { label: t('nav.status.inputNeeded'), tone: 'amber' as const, icon: 'Clock' }
  }
  if (workflowStore.currentStatus === 'running') {
    return { label: t('nav.status.running'), tone: 'cyan' as const, icon: 'Sparkles' }
  }
  if (workflowStore.currentPhase === 'completed') {
    return { label: t('nav.status.completed'), tone: 'emerald' as const, icon: 'CheckCircle' }
  }
  return { label: t('nav.status.idle'), tone: 'slate' as const, icon: 'Rocket' }
})

const activeAccountName = computed(() => accountsStore.activeAccount?.name || t('nav.accountSelect'))
const activeAccountNiche = computed(() => accountsStore.activeAccount?.niche?.trim())
const accountInitial = computed(() =>
  accountsStore.activeAccount?.name?.trim().slice(0, 1).toUpperCase() || t('nav.accountInitialFallback')
)

const statusDotClass = computed(() => ({
  'bg-emerald-400 shadow-[0_0_0_4px_rgba(52,211,153,0.14)]': realtimeStore.connectionStatus === 'connected',
  'bg-amber-400 shadow-[0_0_0_4px_rgba(251,191,36,0.14)]': realtimeStore.connectionStatus === 'connecting' || realtimeStore.connectionStatus === 'reconnecting',
  'bg-rose-400 shadow-[0_0_0_4px_rgba(251,113,133,0.14)]': realtimeStore.connectionStatus === 'disconnected',
}))

const connectionLabel = computed(() => {
  if (realtimeStore.connectionStatus === 'connected') return t('nav.ws.connected')
  if (realtimeStore.connectionStatus === 'reconnecting') return t('nav.ws.reconnecting')
  if (realtimeStore.connectionStatus === 'connecting') return t('nav.ws.connecting')
  return t('nav.ws.disconnected')
})

const navColorClasses: Record<NavColor, { icon: string; activeIcon: string; marker: string }> = {
  pink: { icon: 'text-neon-pink', activeIcon: 'bg-neon-pink/12 ring-neon-pink/20', marker: 'from-neon-pink to-neon-peach' },
  cyan: { icon: 'text-neon-cyan', activeIcon: 'bg-neon-cyan/12 ring-neon-cyan/20', marker: 'from-neon-cyan to-neon-green' },
  purple: { icon: 'text-neon-purple', activeIcon: 'bg-neon-purple/12 ring-neon-purple/20', marker: 'from-neon-purple to-neon-cyan' },
  peach: { icon: 'text-neon-peach', activeIcon: 'bg-neon-peach/12 ring-neon-peach/20', marker: 'from-neon-peach to-neon-pink' },
}

const handleAccountClick = () => router.push('/settings?tab=xhs-accounts')

// HelpCenter handlers
const handleOpenFaq = () => {
  router.push('/help')
}

const handleOpenShortcuts = () => {
  shortcutsStore.showShortcutsPanel()
}

const handleSendFeedback = () => {
  router.push({ name: 'help', query: { section: 'feedback' } })
}

// Logout handler
const handleLogout = async () => {
  await authStore.logout()
  router.push('/login')
}

onMounted(() => {
  if (!accountsStore.activeAccount) void accountsStore.fetchAccounts()
  crossAccountHints.hydrateFromSession()
  void crossAccountHints.refreshReviewAwaitingTotals()
})

// Re-sync when entering review/history (Review writes totals into the shared store).
watch(
  () => route.path,
  (path) => {
    if (path.startsWith('/review') || path.startsWith('/history')) {
      crossAccountHints.hydrateFromSession()
      void crossAccountHints.refreshReviewAwaitingTotals()
    }
  },
)
</script>

<template>
  <nav
    class="app-sidebar liquid-glass-nav relative flex flex-col overflow-hidden border-r border-white/30 transition-all duration-300"
    :class="isTablet ? 'w-[76px] p-3' : 'w-[264px] p-4'"
    role="navigation"
    :aria-label="t('nav.home')"
  >
    <div class="pointer-events-none absolute -left-20 -top-20 h-56 w-56 rounded-full bg-neon-pink/10 blur-3xl" aria-hidden="true" />
    <div class="pointer-events-none absolute -bottom-24 -right-20 h-64 w-64 rounded-full bg-neon-cyan/10 blur-3xl" aria-hidden="true" />

    <!-- Logo -->
    <div class="relative mb-5">
      <div class="flex items-center" :class="isTablet ? 'justify-center' : 'gap-3'">
        <div class="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-rose-400 via-rose-500 to-amber-400 shadow-lg shadow-rose-500/25 transition-transform duration-300 hover:scale-105" aria-hidden="true">
          <AppIcon name="BookOpen" size="lg" variant="white" />
        </div>
        <div v-if="!isTablet">
          <div class="text-[10px] font-bold uppercase tracking-[0.2em] text-neon-pinkDark">{{ t('nav.brandEyebrow') }}</div>
          <div class="mt-0.5 text-lg font-bold tracking-tight text-slate-800">{{ t('nav.appName') }}</div>
        </div>
      </div>
      <div v-if="!isTablet" class="mt-4 rounded-2xl border border-white/70 bg-white/60 p-3 shadow-sm backdrop-blur-sm dark:border-slate-700/55 dark:bg-slate-900/75" role="status" aria-live="polite" :aria-label="t('nav.workspaceStatus')">
        <div class="flex items-center gap-2">
          <span class="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-900/90" aria-hidden="true">
            <AppIcon :name="workspaceStatus.icon" size="sm" variant="white" />
          </span>
          <div class="min-w-0 flex-1">
            <div class="flex items-center justify-between gap-2">
              <span class="text-[10px] font-bold uppercase tracking-wider text-slate-400">{{ t('nav.workspaceStatus') }}</span>
              <span class="h-2 w-2 rounded-full" :class="workspaceStatus.tone === 'rose' ? 'bg-rose-400' : workspaceStatus.tone === 'amber' ? 'bg-amber-400' : workspaceStatus.tone === 'cyan' ? 'bg-cyan-400' : workspaceStatus.tone === 'emerald' ? 'bg-emerald-400' : 'bg-slate-300'" aria-hidden="true" />
            </div>
            <div class="truncate text-xs font-bold text-slate-700">{{ workspaceStatus.label }}</div>
          </div>
        </div>
        <div class="mt-2 flex items-center justify-between gap-2 text-[10px] text-slate-400">
          <span class="truncate">{{ t('nav.phase') }} · {{ phaseLabel }}</span>
          <span v-if="activeNavItem" class="shrink-0 text-neon-pinkDark">{{ activeNavItem.label }}</span>
        </div>
      </div>
      <!-- Tablet: phase indicator dot only -->
      <div v-else class="mt-3 flex flex-col items-center gap-2" role="status" :aria-label="workspaceStatus.label">
        <span class="flex h-8 w-8 items-center justify-center rounded-xl bg-slate-900/90" aria-hidden="true">
          <AppIcon :name="workspaceStatus.icon" size="sm" variant="white" />
        </span>
        <span class="h-2 w-2 rounded-full" :class="workspaceStatus.tone === 'rose' ? 'bg-rose-400' : workspaceStatus.tone === 'amber' ? 'bg-amber-400' : workspaceStatus.tone === 'cyan' ? 'bg-cyan-400' : workspaceStatus.tone === 'emerald' ? 'bg-emerald-400' : 'bg-slate-300'" />
      </div>
    </div>

    <!-- 开始创作按钮 -->
    <button
      @click="router.push('/start')"
      class="group mb-5 flex min-h-12 w-full items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-rose-500 to-amber-500 p-3 text-sm font-bold text-white shadow-lg shadow-rose-500/25 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-rose-500/40 active:translate-y-0"
      :aria-label="t('nav.startWorkflow')"
      :title="isTablet ? t('nav.startWorkflow') : undefined"
    >
      <AppIcon name="Rocket" size="sm" variant="white" />
      <span v-if="!isTablet">{{ t('nav.startWorkflow') }}</span>
      <AppIcon v-if="!isTablet" name="ArrowRight" size="xs" variant="white" class="ml-auto transition-transform duration-200 group-hover:translate-x-0.5" aria-hidden="true" />
    </button>

    <!-- Grouped navigation -->
    <div class="app-nav-scroll relative min-h-0 flex-1 space-y-4 overflow-y-auto pr-0.5" role="list" :aria-label="t('nav.home')">
      <section v-for="section in navSections" :key="section.key" class="app-nav-section" :aria-labelledby="`nav-section-${section.key}`">
        <div class="app-nav-section-title mb-2 flex items-center gap-2 px-2" :class="isTablet ? 'justify-center px-0' : ''">
          <span class="h-1.5 w-1.5 rounded-full bg-slate-300" aria-hidden="true" />
          <span :id="`nav-section-${section.key}`" :class="isTablet ? 'sr-only' : 'text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400'">{{ section.label }}</span>
        </div>
        <div class="app-nav-items space-y-1.5">
          <button
            v-for="item in section.items"
            :key="item.path"
            @click="navigateTo(item.path)"
            :class="[
              'app-nav-item group relative flex min-h-12 w-full items-center rounded-2xl border text-left transition-all duration-200',
              isTablet ? 'justify-center px-2' : 'gap-3 px-3',
              isItemActive(item.path)
                ? 'border-white/80 bg-white/85 shadow-md shadow-slate-900/5 ring-1 ring-slate-200/60 dark:border-slate-600/70 dark:bg-slate-800/90 dark:ring-slate-600/50'
                : 'border-transparent hover:border-white/70 hover:bg-white/55 hover:shadow-sm dark:hover:border-slate-600/50 dark:hover:bg-slate-800/60'
            ]"
            :aria-current="isItemActive(item.path) ? 'page' : undefined"
            :aria-label="item.hint ? `${item.label}: ${item.hint}` : item.label"
            :title="isTablet ? `${item.label} · ${item.hint}` : undefined"
          >
            <span
              v-if="isItemActive(item.path)"
              class="absolute left-0 top-1/2 h-8 w-1 -translate-y-1/2 rounded-r-full bg-gradient-to-b"
              :class="navColorClasses[item.color].marker"
              aria-hidden="true"
            />
            <span
              class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ring-1 transition-all duration-200"
              :class="isItemActive(item.path) ? navColorClasses[item.color].activeIcon : 'bg-slate-100/80 ring-slate-200/60 group-hover:bg-white dark:bg-slate-800/80 dark:ring-slate-600/50 dark:group-hover:bg-slate-700'"
              aria-hidden="true"
            >
              <AppIcon :name="item.icon" size="md" :variant="isItemActive(item.path) ? item.color : 'cyan'" :class="!isItemActive(item.path) ? navColorClasses[item.color].icon : ''" />
            </span>
            <span v-if="!isTablet" class="min-w-0 flex-1">
              <span :class="['block truncate text-sm font-bold', isItemActive(item.path) ? 'text-slate-800' : 'text-slate-600 group-hover:text-slate-800']">{{ item.label }}</span>
              <span class="mt-0.5 block truncate text-[10px] text-slate-400">{{ item.hint }}</span>
            </span>
            <span
              v-if="item.badgeCount"
              class="flex h-5 min-w-5 items-center justify-center rounded-full bg-rose-100 px-1.5 text-[10px] font-bold text-rose-600"
              :aria-label="t('nav.status.reviewCount', { count: item.badgeCount })"
            >
              {{ item.badgeCount > 99 ? '99+' : item.badgeCount }}
            </span>
            <span
              v-else-if="item.needsAttention"
              class="flex h-5 min-w-5 items-center justify-center rounded-full bg-rose-100 px-1.5 text-[10px] font-bold text-rose-600"
              :aria-label="t('nav.status.reviewNeeded')"
            >
              !
            </span>
            <AppIcon v-if="isItemActive(item.path) && !isTablet" name="ChevronRight" size="sm" variant="cyan" aria-hidden="true" />
          </button>
        </div>
      </section>
    </div>

    <!-- 底部信息 -->
    <div class="mt-4 border-t border-slate-200/70 pt-4" :aria-label="t('nav.systemInfo')">
      <!-- Desktop: compact bottom section -->
      <template v-if="!isTablet">
        <button
          class="group mb-3 flex min-h-14 w-full items-center gap-3 rounded-2xl border border-white/75 bg-white/65 px-3 text-left shadow-sm dark:border-slate-700/55 dark:bg-slate-900/80 transition-all duration-200 hover:-translate-y-0.5 hover:border-cyan-200/70 hover:bg-cyan-50/70"
          :aria-label="t('nav.account')"
          :title="t('nav.accountManage')"
          @click="handleAccountClick"
        >
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-400 to-emerald-400 text-xs font-bold text-white shadow-sm" aria-hidden="true">{{ accountInitial }}</span>
          <span class="min-w-0 flex-1">
            <span class="block text-[10px] font-bold uppercase tracking-wider text-slate-400">{{ t('nav.activeAccount') }}</span>
            <span class="block truncate text-xs font-bold text-slate-700">{{ activeAccountName }}</span>
            <span class="block truncate text-[10px] text-slate-400">{{ activeAccountNiche ? t('nav.accountNiche', { niche: activeAccountNiche }) : t('nav.accountPending') }}</span>
          </span>
          <AppIcon name="Settings" size="sm" variant="cyan" class="opacity-60 transition-opacity group-hover:opacity-100" aria-hidden="true" />
        </button>

        <!-- Utilities row: realtime + language + theme -->
        <div class="mb-2 flex items-center justify-between gap-2 rounded-xl bg-slate-50/70 px-2.5 py-2 dark:bg-slate-800/70">
          <div class="flex min-w-0 items-center gap-2">
            <span class="h-2 w-2 shrink-0 rounded-full" :class="statusDotClass" aria-hidden="true" />
            <span class="truncate text-[10px] font-medium text-slate-500">{{ connectionLabel }}</span>
            <button
              v-if="realtimeStore.connectionStatus === 'disconnected'"
              @click="realtimeStore.connect()"
              class="min-h-8 shrink-0 rounded-md px-1.5 text-[10px] font-bold text-rose-500 transition-colors hover:bg-rose-50"
            >
              {{ t('nav.ws.reconnect') }}
            </button>
          </div>
          <div class="flex shrink-0 items-center gap-1">
            <LanguageSwitcher />
            <ThemeToggle />
          </div>
        </div>

        <!-- Actions: Help + Settings + Logout -->
        <div class="flex items-center gap-1.5">
          <HelpCenter
            @open-faq="handleOpenFaq"
            @open-shortcuts="handleOpenShortcuts"
            @send-feedback="handleSendFeedback"
          />
          <button
            @click="router.push('/settings')"
            class="flex min-h-10 items-center gap-1.5 rounded-lg px-2 text-xs text-slate-400 transition-colors hover:bg-cyan-50 hover:text-teal-500"
            :aria-label="t('nav.settings')"
            :title="t('nav.settings')"
          >
            <AppIcon name="Settings" size="xs" variant="cyan" />
            <span>{{ t('nav.settings') }}</span>
          </button>
          <button
            v-if="authStore.isAuthenticated"
            @click="handleLogout"
            class="ml-auto flex min-h-10 items-center gap-1.5 rounded-lg px-2 text-xs text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-500"
            :aria-label="t('nav.logout')"
          >
            <AppIcon name="LogOut" size="xs" variant="pink" />
            <span>{{ t('nav.logout') }}</span>
          </button>
        </div>
      </template>

      <!-- Tablet: compact bottom section -->
      <template v-else>
        <div class="flex flex-col items-center gap-2">
          <!-- WS status dot -->
          <div
            class="h-2 w-2 rounded-full"
            :class="statusDotClass"
            :title="connectionLabel"
          />
          <button
            class="flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-50 text-xs font-bold text-cyan-600 transition hover:bg-cyan-100"
            :aria-label="t('nav.account')"
            :title="`${t('nav.activeAccount')}: ${activeAccountName}`"
            @click="handleAccountClick"
          >
            {{ accountInitial }}
          </button>
          <!-- Settings -->
          <button
            @click="router.push('/settings')"
            class="flex h-10 w-10 items-center justify-center rounded-xl text-slate-400 transition-all hover:bg-teal-50 hover:text-teal-500"
            :aria-label="t('nav.settings')"
            :title="t('nav.settings')"
          >
            <AppIcon name="Settings" size="sm" variant="cyan" />
          </button>
          <!-- Theme -->
          <ThemeToggle />
          <!-- Logout -->
          <button
            v-if="authStore.isAuthenticated"
            @click="handleLogout"
            class="flex h-10 w-10 items-center justify-center rounded-xl text-slate-400 transition-all hover:bg-rose-50 hover:text-rose-500"
            :aria-label="t('nav.logout')"
            :title="t('nav.logout')"
          >
            <AppIcon name="LogOut" size="sm" variant="pink" />
          </button>
        </div>
      </template>
    </div>
  </nav>
</template>

<style scoped>
.app-sidebar {
  flex-shrink: 0;
  box-shadow:
    1px 0 2px rgba(15, 23, 42, 0.03),
    8px 0 24px rgba(15, 23, 42, 0.035),
    inset -1px 0 rgba(255, 255, 255, 0.52);
}

:global(html.dark) .app-sidebar {
  box-shadow:
    1px 0 2px rgba(2, 6, 23, 0.35),
    8px 0 24px rgba(2, 6, 23, 0.28),
    inset -1px 0 rgba(148, 163, 184, 0.1);
}

.app-nav-scroll {
  scrollbar-gutter: stable;
}

.app-nav-section {
  padding: 0.45rem 0.35rem 0.55rem;
  border: 1px solid rgba(255, 255, 255, 0.34);
  border-radius: 1.25rem;
  background: rgba(255, 255, 255, 0.16);
}

:global(html.dark) .app-nav-section {
  border-color: rgba(100, 116, 139, 0.35);
  background: rgba(15, 23, 42, 0.45);
}

.app-nav-section-title {
  min-height: 1.3rem;
}

.app-nav-item {
  box-shadow: 0 1px 1px rgba(15, 23, 42, 0.015);
}

.app-nav-item[aria-current='page'] {
  box-shadow:
    0 5px 14px rgba(15, 23, 42, 0.065),
    inset 0 1px 0 rgba(255, 255, 255, 0.78);
}

:global(html.dark) .app-nav-item[aria-current='page'] {
  box-shadow:
    0 5px 14px rgba(2, 6, 23, 0.35),
    inset 0 1px 0 rgba(148, 163, 184, 0.12);
}

.app-nav-item:not([aria-current='page']):hover {
  transform: translateX(1px);
}

@media (max-width: 1023px) {
  .app-nav-section {
    padding-inline: 0;
    border-color: transparent;
    background: transparent;
  }

  .app-nav-item:not([aria-current='page']):hover {
    transform: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .app-nav-item:not([aria-current='page']):hover {
    transform: none;
  }
}
</style>
